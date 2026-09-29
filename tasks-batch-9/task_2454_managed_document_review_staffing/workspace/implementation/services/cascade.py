"""State transitions, cascades and the two append-only streams."""

from db import audit_row, db, touch
from services import compute
from services.compute import (
    ACTIVE_ASSIGNMENT_STATUSES,
    STRIKE_DELTA_BY_EVENT_TYPE,
)


# ---------------------------------------------------------------------------
# Append-only streams
# ---------------------------------------------------------------------------
def append_ledger(matter_id, assignment_id, entry_type, amount_cents, batch_number):
    row = audit_row()
    row.update({
        "matter_id": matter_id,
        "assignment_id": assignment_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "description": "%s for batch %s" % (entry_type, batch_number),
    })
    db.ledger_entries[row["id"]] = row
    return row


def append_scorecard_event(reviewer_id, event_type, note, source_batch_number):
    row = audit_row()
    row.update({
        "reviewer_id": reviewer_id,
        "event_type": event_type,
        "strike_delta": STRIKE_DELTA_BY_EVENT_TYPE[event_type],
        "note": note,
        "source_batch_number": source_batch_number,
    })
    db.scorecard_events[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Matter staffing (PRD 3.5)
# ---------------------------------------------------------------------------
def sync_matter_staffing(matter):
    count = compute.staffed_reviewer_count(matter)
    if matter["status"] == "STAFFING":
        if count >= matter["min_staffed_reviewers"] and compute.approved_protocol(matter["id"]):
            matter["status"] = "IN_REVIEW"
            touch(matter)
    elif matter["status"] == "IN_REVIEW":
        if count < matter["min_staffed_reviewers"]:
            matter["status"] = "STAFFING"
            touch(matter)
    return matter


def sync_staffing_for_reviewer_matters(reviewer_id):
    """Every matter on which this reviewer holds a CLEARED screening."""
    matter_ids = []
    for screening in db.screenings.values():
        if screening["reviewer_id"] == reviewer_id and screening["status"] == "CLEARED":
            if screening["matter_id"] not in matter_ids:
                matter_ids.append(screening["matter_id"])
    for matter_id in matter_ids:
        matter = db.matters.get(matter_id)
        if matter is not None:
            sync_matter_staffing(matter)


# ---------------------------------------------------------------------------
# Reviewer engagement axis
# ---------------------------------------------------------------------------
def engage_reviewer(reviewer):
    if reviewer["engagement_status"] == "CLEARED":
        reviewer["engagement_status"] = "ENGAGED"
        touch(reviewer)


def clear_reviewer(reviewer):
    if reviewer["engagement_status"] == "SOURCED":
        reviewer["engagement_status"] = "CLEARED"
        touch(reviewer)


def recompute_engagement(reviewer):
    """Falls ENGAGED/CLEARED -> SOURCED when no cleared+executed pair remains."""
    if reviewer["engagement_status"] in ("ENGAGED", "CLEARED"):
        if not compute.holds_cleared_and_executed_pair(reviewer["id"]):
            reviewer["engagement_status"] = "SOURCED"
            touch(reviewer)


# ---------------------------------------------------------------------------
# Lazy confidentiality expiry (PRD 3.5)
# ---------------------------------------------------------------------------
def apply_lazy_expiry(agreement):
    if agreement["status"] != "EXECUTED":
        return False
    if agreement["_coverage_end_dt"] >= db.now():
        return False
    agreement["status"] = "EXPIRED"
    touch(agreement)
    matter = db.matters.get(agreement["matter_id"])
    if matter is not None:
        sync_matter_staffing(matter)
    return True


def apply_lazy_expiry_many(agreements):
    for agreement in list(agreements):
        apply_lazy_expiry(agreement)


# ---------------------------------------------------------------------------
# Assignment voiding (PRD 3.6)
# ---------------------------------------------------------------------------
def void_assignment(assignment, void_reason, unconditional_batch_reset=False,
                    reset_batch=True):
    batch = compute.batch_of_assignment(assignment)
    matter = compute.matter_of_batch(batch)
    assignment["status"] = "VOIDED"
    assignment["voided_at"] = db.now_iso()
    assignment["void_reason"] = void_reason
    touch(assignment)
    if assignment["billable_amount_cents"] == 0:
        append_ledger(matter["id"], assignment["id"], "REVERSAL",
                      -assignment["committed_amount_cents"], batch["batch_number"])
    if reset_batch and batch["status"] in ("ASSIGNED", "IN_PROGRESS"):
        reset = unconditional_batch_reset
        if not reset:
            remaining = [a for a in compute.assignments_of_batch(batch["id"])
                         if a["pass_type"] == assignment["pass_type"]
                         and a["status"] != "VOIDED"]
            reset = len(remaining) == 0
        if reset:
            batch["status"] = "CREATED"
            touch(batch)
    return matter


# ---------------------------------------------------------------------------
# Removal (PRD 3.3)
# ---------------------------------------------------------------------------
def evaluate_removal(reviewer):
    if reviewer["engagement_status"] not in ("ENGAGED", "CLEARED"):
        return False
    if not compute.removal_grounds_met(reviewer["id"]):
        return False
    remove_reviewer(reviewer)
    return True


def remove_reviewer(reviewer):
    strikes = compute.scorecard_strikes(reviewer["id"])
    append_scorecard_event(
        reviewer["id"], "REMOVAL",
        "Reviewer removed from engagement at %d strikes." % strikes,
        None,
    )
    reviewer["engagement_status"] = "REMOVED"
    reviewer["removed_at"] = db.now_iso()
    touch(reviewer)
    affected = []
    for assignment in compute.assignments_of_reviewer(reviewer["id"]):
        if assignment["status"] in ACTIVE_ASSIGNMENT_STATUSES:
            matter = void_assignment(assignment, "REVIEWER_REMOVED",
                                     unconditional_batch_reset=True)
            if matter["id"] not in [m["id"] for m in affected]:
                affected.append(matter)
    for matter in affected:
        sync_matter_staffing(matter)
    # A removal also drops the reviewer out of every matter's staffed count.
    sync_staffing_for_reviewer_matters(reviewer["id"])


# ---------------------------------------------------------------------------
# Blocked re-screening cascade (PRD 3.4)
# ---------------------------------------------------------------------------
def blocked_screening_cascade(screening):
    reviewer = db.reviewers[screening["reviewer_id"]]
    matter = db.matters[screening["matter_id"]]

    # Link 2 - revoke the confidentiality paper.
    revoked_executed = False
    for agreement in compute.agreements_of_pair(reviewer["id"], matter["id"]):
        if agreement["status"] in ("PENDING", "EXECUTED"):
            if agreement["status"] == "EXECUTED":
                revoked_executed = True
            agreement["status"] = "REVOKED"
            agreement["revocation_reason"] = "CONFLICTS_BLOCKED"
            touch(agreement)

    if not revoked_executed:
        # Only an executed agreement was ever counted or relied upon (PRD 3.5).
        return

    # Link 3 - revoke environment access, then recompute staffing.
    for session in compute.sessions_of_pair(reviewer["id"], matter["id"]):
        if session["status"] in ("SCHEDULED", "ACTIVE"):
            session["status"] = "REVOKED"
            session["closed_at"] = db.now_iso()
            touch(session)
    sync_matter_staffing(matter)

    # Link 4 - void live assignments on this matter, in created_at order.
    for assignment in compute.assignments_of_matter(matter["id"]):
        if assignment["reviewer_id"] != reviewer["id"]:
            continue
        if assignment["status"] not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        void_assignment(assignment, "CONFLICTS_BLOCKED", unconditional_batch_reset=True)
    recompute_engagement(reviewer)
