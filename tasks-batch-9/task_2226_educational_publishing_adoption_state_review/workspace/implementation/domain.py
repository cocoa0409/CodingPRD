"""Cross-entity domain helpers: lookups, derived counters, cascades and sweeps."""

from datetime import timedelta
from decimal import Decimal

import calc
from db import apply_changes, db, now, ordered, touch
from errors import fail

LIVE_REVIEW_STATUSES = ("FILED", "SCHEDULED", "PRESENTED")
OCCUPYING_SLOT_STATUSES = ("RESERVED", "PRESENTED", "TALLIED", "NO_SHOW")
HOLDING_SLOT_STATUSES = ("RESERVED", "PRESENTED", "TALLIED")

PHASE_ORDER = (
    "SCHEDULED",
    "OPEN",
    "CLOSED_FOR_SUBMISSION",
    "IN_REVIEW",
    "PUBLIC_COMMENT",
    "DECIDED",
    "ARCHIVED",
)

PHASE_GATE = {
    "OPEN": "submission_open_at",
    "CLOSED_FOR_SUBMISSION": "submission_deadline_at",
    "IN_REVIEW": "committee_review_at",
    "PUBLIC_COMMENT": "public_comment_start_at",
    "DECIDED": "adoption_decision_at",
}


# --- lookups ---------------------------------------------------------------
def find_state(state_id, error_id="ERR_STATE_PROFILE_NOT_FOUND"):
    record = db.state_profiles.get(state_id)
    if record is None:
        fail(error_id, "State profile %s does not exist." % state_id)
    return record


def find_cycle(cycle_id, error_id="ERR_ADOPTION_CYCLE_NOT_FOUND"):
    record = db.adoption_cycles.get(cycle_id)
    if record is None:
        fail(error_id, "Adoption cycle %s does not exist." % cycle_id)
    return record


def find_title(title_id, error_id="ERR_TITLE_NOT_FOUND"):
    record = db.titles.get(title_id)
    if record is None:
        fail(error_id, "Title %s does not exist." % title_id)
    return record


def find_bundle(bundle_id, error_id="ERR_REFERENCED_RESOURCE_NOT_FOUND"):
    record = db.ancillary_bundles.get(bundle_id)
    if record is None:
        fail(error_id, "Ancillary bundle %s does not exist." % bundle_id)
    return record


def find_content_edit(edit_id, error_id="ERR_CONTENT_EDIT_NOT_FOUND"):
    record = db.content_edits.get(edit_id)
    if record is None:
        fail(error_id, "Content edit %s does not exist." % edit_id)
    return record


def find_submission(submission_id, error_id="ERR_SUBMISSION_NOT_FOUND"):
    record = db.submissions.get(submission_id)
    if record is None:
        fail(error_id, "Submission %s does not exist." % submission_id)
    return record


def find_panel(panel_id, error_id="ERR_COMMITTEE_PANEL_NOT_FOUND"):
    record = db.committee_panels.get(panel_id)
    if record is None:
        fail(error_id, "Committee panel %s does not exist." % panel_id)
    return record


def find_slot(slot_id, error_id="ERR_PRESENTATION_SLOT_NOT_FOUND"):
    record = db.presentation_slots.get(slot_id)
    if record is None:
        fail(error_id, "Presentation slot %s does not exist." % slot_id)
    return record


def find_proposal(proposal_id, error_id="ERR_PRICING_PROPOSAL_NOT_FOUND"):
    record = db.pricing_proposals.get(proposal_id)
    if record is None:
        fail(error_id, "Pricing proposal %s does not exist." % proposal_id)
    return record


def find_order(order_id, error_id="ERR_DISTRICT_ORDER_NOT_FOUND"):
    record = db.district_orders.get(order_id)
    if record is None:
        fail(error_id, "District order %s does not exist." % order_id)
    return record


def find_comment(comment_id, error_id="ERR_PUBLIC_COMMENT_NOT_FOUND"):
    record = db.public_comments.get(comment_id)
    if record is None:
        fail(error_id, "Public comment %s does not exist." % comment_id)
    return record


def submission_context(submission):
    cycle = db.adoption_cycles[submission["cycle_id"]]
    title = db.titles[submission["title_id"]]
    state = db.state_profiles[cycle["state_id"]]
    return cycle, title, state


def cycle_state_id(cycle):
    return cycle["state_id"]


def panel_state_id(panel):
    return db.adoption_cycles[panel["cycle_id"]]["state_id"]


def slot_state_id(slot):
    return panel_state_id(db.committee_panels[slot["panel_id"]])


# --- collection helpers ----------------------------------------------------
def standards_of_state(state_id):
    return ordered(
        [s for s in db.state_standards.values() if s["state_id"] == state_id]
    )


def submissions_of_cycle(cycle_id):
    return ordered(
        [s for s in db.submissions.values() if s["cycle_id"] == cycle_id]
    )


def submissions_of_title(title_id):
    return ordered(
        [s for s in db.submissions.values() if s["title_id"] == title_id]
    )


def entries_of_submission(submission_id):
    return ordered(
        [e for e in db.correlation_entries.values()
         if e["submission_id"] == submission_id]
    )


def comments_of_submission(submission_id):
    return ordered(
        [c for c in db.public_comments.values()
         if c["submission_id"] == submission_id]
    )


def slots_of_panel(panel_id):
    return ordered(
        [s for s in db.presentation_slots.values() if s["panel_id"] == panel_id]
    )


def slots_of_submission(submission_id):
    return ordered(
        [s for s in db.presentation_slots.values()
         if s["submission_id"] == submission_id]
    )


def votes_of_slot(slot_id):
    return ordered(
        [v for v in db.committee_votes.values() if v["slot_id"] == slot_id]
    )


def proposals_of_submission(submission_id):
    return ordered(
        [p for p in db.pricing_proposals.values()
         if p["submission_id"] == submission_id]
    )


# --- correlation coverage --------------------------------------------------
def denominator_set(cycle, title):
    """Standards of the cycle's state and subject whose grade band overlaps the title."""
    result = []
    for standard in db.state_standards.values():
        if standard["state_id"] != cycle["state_id"]:
            continue
        if standard["subject"] != cycle["subject"]:
            continue
        if standard["grade_high"] < title["grade_low"]:
            continue
        if standard["grade_low"] > title["grade_high"]:
            continue
        result.append(standard)
    return ordered(result)


def _coverage(submission, cycle, title, verdicts):
    standards = denominator_set(cycle, title)
    denominator = sum(s["weight"] for s in standards)
    if denominator == 0:
        return Decimal("0.00")
    entries = entries_of_submission(submission["id"])
    numerator = Decimal(0)
    for standard in standards:
        candidates = [
            e for e in entries
            if e["standard_code"] == standard["standard_code"]
            and e["reviewer_verdict"] in verdicts
        ]
        if not candidates:
            continue
        best = max(
            candidates,
            key=lambda e: (calc.DEPTH_MULTIPLIERS[e["depth_level"]], -e["_seq"]),
        )
        numerator += Decimal(standard["weight"]) * calc.DEPTH_MULTIPLIERS[
            best["depth_level"]
        ]
    pct = calc.round_half_up(Decimal(100) * numerator / Decimal(denominator), 2)
    return min(Decimal("100.00"), pct)


def coverage_values(submission):
    cycle, title, _state = submission_context(submission)
    self_reported = _coverage(submission, cycle, title, ("PENDING", "ACCEPTED"))
    verified = _coverage(submission, cycle, title, ("ACCEPTED",))
    return self_reported, verified


# --- compliance counters --------------------------------------------------
def content_counters(submission):
    cycle, title, state = submission_context(submission)
    applied = [
        e for e in db.content_edits.values()
        if e["title_id"] == submission["title_id"]
        and e["state_id"] == cycle["state_id"]
        and e["status"] == "APPLIED"
    ]
    neutralised = {
        e["topic_code"] for e in applied if e["edit_type"] == "REMOVE_PROHIBITED_TAG"
    }
    supplied = set(title["content_tags"]) | {
        e["topic_code"] for e in applied if e["edit_type"] == "ADD_REQUIRED_TOPIC"
    }
    present = set(title["content_tags"])
    prohibited_hits = len(
        [t for t in state["prohibited_content_tags"]
         if t in present and t not in neutralised]
    )
    missing = len([t for t in state["required_topics"] if t not in supplied])
    return prohibited_hits, missing


def comment_counters(submission):
    comments = comments_of_submission(submission["id"])
    unresolved_critical = len(
        [c for c in comments
         if c["severity"] == "CRITICAL" and c["status"] in ("OPEN", "ESCALATED")]
    )
    overdue = len(
        [c for c in comments
         if c["status"] == "ESCALATED"
         or (c["status"] == "RESPONDED" and c["was_overdue_at_response"])]
    )
    return unresolved_critical, overdue


def recompute_submission(submission, coverage=True, comments=True, content=True,
                         extra=None, bump=True):
    """Recompute derived submission fields, then compliance_score / adoption_blocked.

    ``bump`` is False while a submission is still being created, so that the fresh
    record keeps ``version`` 1 instead of being counted as an immediate mutation.
    """
    changes = {}
    if extra:
        changes.update(extra)
    if coverage:
        self_reported, verified = coverage_values(submission)
        changes["self_reported_coverage_pct"] = self_reported
        changes["verified_coverage_pct"] = verified
    if content:
        prohibited_hits, missing = content_counters(submission)
        changes["prohibited_hit_count"] = prohibited_hits
        changes["missing_required_topic_count"] = missing
    if comments:
        unresolved_critical, overdue = comment_counters(submission)
        changes["unresolved_critical_count"] = unresolved_critical
        changes["overdue_response_count"] = overdue

    merged = dict(submission)
    merged.update(changes)
    score = calc.compliance_score(
        merged["prohibited_hit_count"],
        merged["missing_required_topic_count"],
        merged["unresolved_critical_count"],
        merged["overdue_response_count"],
    )
    changes["compliance_score"] = score
    changes["adoption_blocked"] = calc.is_adoption_blocked(
        score, merged["prohibited_hit_count"], merged["content_pin_stale"]
    )
    if not bump:
        submission.update(changes)
        return False
    return apply_changes(submission, changes)


# --- cycle counters -------------------------------------------------------
def recount_cycle(cycle):
    submissions = [
        s for s in db.submissions.values() if s["cycle_id"] == cycle["id"]
    ]
    submission_count = len(
        [s for s in submissions if s["review_status"] in LIVE_REVIEW_STATUSES]
    )
    scheduled = len([s for s in submissions if s["review_status"] == "SCHEDULED"])
    adopted = len(
        [s for s in submissions
         if s["review_status"] in ("ADOPTED", "ADOPTED_WITH_CONDITIONS")]
    )
    apply_changes(
        cycle,
        {
            "submission_count": submission_count,
            "scheduled_submission_count": scheduled,
            "adopted_count": adopted,
        },
    )


def recount_panel_minutes(panel):
    total = sum(
        slot["duration_minutes"]
        for slot in db.presentation_slots.values()
        if slot["panel_id"] == panel["id"]
        and slot["status"] in OCCUPYING_SLOT_STATUSES
    )
    apply_changes(panel, {"reserved_minutes": total})


# --- slot / submission cascades -------------------------------------------
def cancel_slot(slot):
    """RESERVED -> CANCELLED, returning the minutes to the panel's budget."""
    apply_changes(slot, {"status": "CANCELLED"})
    recount_panel_minutes(db.committee_panels[slot["panel_id"]])


def no_show_slot(slot):
    """RESERVED -> NO_SHOW; reserved_minutes are deliberately left untouched."""
    apply_changes(slot, {"status": "NO_SHOW"})


def holds_slot(submission):
    return any(
        slot["submission_id"] == submission["id"]
        and slot["status"] in HOLDING_SLOT_STATUSES
        for slot in db.presentation_slots.values()
    )


def demote_if_unslotted(submission):
    """SCHEDULED -> FILED once the submission keeps no live slot."""
    if submission["review_status"] != "SCHEDULED":
        return
    if holds_slot(submission):
        return
    apply_changes(submission, {"review_status": "FILED"})
    recount_cycle(db.adoption_cycles[submission["cycle_id"]])


def cascade_content_revision(title):
    """Hops 2-4 of the content-edit apply cascade (PRD 3.3)."""
    affected = []
    for submission in submissions_of_title(title["id"]):
        if submission["review_status"] not in LIVE_REVIEW_STATUSES:
            continue
        pinned = submission["pinned_content_revision"]
        if pinned is None or pinned >= title["content_revision"]:
            continue
        affected.append(submission)

    # HOP 2
    for submission in affected:
        recompute_submission(
            submission,
            coverage=True,
            comments=False,
            content=True,
            extra={"content_pin_stale": True},
        )
    # HOP 3
    for submission in affected:
        for slot in slots_of_submission(submission["id"]):
            if slot["status"] == "RESERVED":
                cancel_slot(slot)
    # HOP 4
    for submission in affected:
        demote_if_unslotted(submission)


def recompute_live_submissions_of_title(title):
    """Used by the content-edit revert arc (PRD 3.3).

    ``content_pin_stale`` is a live comparison of the pin against the edition's
    current ``content_revision``, which is why a revert bumps the revision rather
    than restoring the previous number.
    """
    for submission in submissions_of_title(title["id"]):
        if submission["review_status"] not in LIVE_REVIEW_STATUSES:
            continue
        pinned = submission["pinned_content_revision"]
        stale = pinned is not None and pinned < title["content_revision"]
        recompute_submission(
            submission,
            coverage=True,
            comments=False,
            content=True,
            extra={"content_pin_stale": stale},
        )


# --- epoch sweep ----------------------------------------------------------
def epoch_sweep(cycle):
    submissions = submissions_of_cycle(cycle["id"])
    clock = now()

    # S1: overdue OPEN comments escalate.
    for submission in submissions:
        for comment in comments_of_submission(submission["id"]):
            if comment["status"] == "OPEN" and clock >= comment["response_due_at"]:
                apply_changes(
                    comment,
                    {"status": "ESCALATED", "was_overdue_at_response": True},
                )

    # S2: every submission recomputes its counters.
    for submission in submissions:
        recompute_submission(submission, coverage=True, comments=True, content=True)

    # S3: RESERVED slots of newly blocked submissions are cancelled.
    for submission in submissions:
        if not submission["adoption_blocked"]:
            continue
        for slot in slots_of_submission(submission["id"]):
            if slot["status"] == "RESERVED":
                cancel_slot(slot)
        demote_if_unslotted(submission)


def archive_due_at(cycle):
    return cycle["adoption_decision_at"] + timedelta(days=calc.ARCHIVE_DELAY_DAYS)
