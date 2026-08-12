"""Cross-entity cascades and the epoch sweep. All mutations are atomic within the
triggering request; every touched entity gets updated_at refreshed and version += 1."""

import calc
import clock
from db import db
from helpers import touch, recompute_posture, recompute_envelope


# ---------------------------------------------------------------------------
# Union decertification cascade
# ---------------------------------------------------------------------------

def decertify_cascade(union):
    now = clock.now()
    for agreement in db.agreements.values():
        if agreement["union_id"] == union["id"] and agreement["status"] == "DRAFT":
            agreement["status"] = "ARCHIVED"
            agreement["posture"] = "CLOSED"
            touch(agreement)
    for session in db.sessions.values():
        owner = db.agreements.get(session["agreement_id"])
        if owner is not None and owner["union_id"] == union["id"] and session["status"] == "SCHEDULED":
            session["status"] = "CANCELLED"
            session["cancel_reason"] = "UNION_DECERTIFIED"
            touch(session)


# ---------------------------------------------------------------------------
# Agreement activation: incumbent supersession
# ---------------------------------------------------------------------------

def supersede_incumbents(agreement):
    """Other agreements of the same union in ACTIVE/EXTENDED become REPLACED."""
    for other in db.agreements.values():
        if other["id"] == agreement["id"]:
            continue
        if other["union_id"] == agreement["union_id"] and other["status"] in ("ACTIVE", "EXTENDED"):
            other["status"] = "REPLACED"
            other["posture"] = "CLOSED"
            touch(other)


# ---------------------------------------------------------------------------
# Clause cascades
# ---------------------------------------------------------------------------

def clause_supersede_cascade(clause, superseded_letter_id):
    """An EXECUTED side letter on this clause became SUPERSEDED: clause returns to
    UNDER_REVIEW from INTERPRETED/DISPUTED/RESOLVED; resolved_by_ref cleared when it
    referenced the superseded letter."""
    if clause["interpretation_status"] in ("INTERPRETED", "DISPUTED", "RESOLVED"):
        clause["interpretation_status"] = "UNDER_REVIEW"
        if clause["resolved_by_ref"] == superseded_letter_id:
            clause["resolved_by_ref"] = None
        touch(clause)


# ---------------------------------------------------------------------------
# Proposal implementation cascade (Proposal ACCEPTED -> IMPLEMENTED side effects)
# ---------------------------------------------------------------------------

def proposal_implementation_cascade(proposal, agreement):
    """Every EXECUTED SideLetter on this proposal's clause whose closed effective
    window overlaps the agreement window becomes SUPERSEDED; each supersession
    re-triggers the clause cascade."""
    if proposal["clause_id"] is None:
        return
    agr_start = agreement["effective_date"]
    agr_end = agreement["expiration_date"]
    for letter in db.letters.values():
        if letter["clause_id"] != proposal["clause_id"] or letter["status"] != "EXECUTED":
            continue
        # closed-interval overlap: touching boundaries conflict
        if letter["effective_start"] <= agr_end and agr_start <= letter["effective_end"]:
            letter["status"] = "SUPERSEDED"
            touch(letter)
            clause = db.clauses.get(letter["clause_id"])
            if clause is not None:
                clause_supersede_cascade(clause, letter["id"])


# ---------------------------------------------------------------------------
# Ratification cascades
# ---------------------------------------------------------------------------

def ratified_cascade(vote, agreement):
    """Depth-5 activation cascade. Returns the list of proposals that became
    IMPLEMENTED (for the retro payout)."""
    # Link 1: agreement DRAFT -> ACTIVE, posture recomputed
    agreement["status"] = "ACTIVE"
    recompute_posture(agreement)
    touch(agreement)
    # Link 2: incumbent supersession for the same union
    supersede_incumbents(agreement)
    # Link 3: every ACCEPTED proposal of the agreement becomes IMPLEMENTED
    implemented = []
    for proposal in db.proposals.values():
        if proposal["agreement_id"] == agreement["id"] and proposal["status"] == "ACCEPTED":
            proposal["status"] = "IMPLEMENTED"
            touch(proposal)
            implemented.append(proposal)
    recompute_envelope(agreement)
    # Links 4+5: side-letter supersession and clause re-review
    for proposal in implemented:
        proposal_implementation_cascade(proposal, agreement)
    return implemented


def rejected_cascade(agreement):
    """Compensation revert: every ACCEPTED proposal of the agreement reverts to
    ON_TABLE; the envelope is recomputed (accepts rolled back)."""
    reverted = False
    for proposal in db.proposals.values():
        if proposal["agreement_id"] == agreement["id"] and proposal["status"] == "ACCEPTED":
            proposal["status"] = "ON_TABLE"
            touch(proposal)
            reverted = True
    if reverted:
        recompute_envelope(agreement)
        touch(agreement)


# ---------------------------------------------------------------------------
# Epoch sweep (pinned order, PRD section 2.12)
# ---------------------------------------------------------------------------

def run_epoch_sweep(new_now):
    counts = {
        "agreements_expired": 0,
        "sessions_no_show": 0,
        "side_letters_expired": 0,
        "past_practices_abandoned": 0,
        "information_requests_overdue": 0,
        "expiration_tasks_missed": 0,
        "agreements_posture_refreshed": 0,
    }

    # Step 1: agreements ACTIVE/EXTENDED strictly past expiration -> EXPIRED
    for agreement in db.agreements.values():
        if agreement["status"] in ("ACTIVE", "EXTENDED") and agreement["expiration_date"] < new_now:
            agreement["status"] = "EXPIRED"
            recompute_posture(agreement)  # -> UNCOVERED
            touch(agreement)
            counts["agreements_expired"] += 1

    # Step 2: SCHEDULED sessions strictly past end_at -> NO_SHOW
    for session in db.sessions.values():
        if session["status"] == "SCHEDULED" and session["end_at"] < new_now:
            session["status"] = "NO_SHOW"
            touch(session)
            counts["sessions_no_show"] += 1

    # Step 3: EXECUTED side letters strictly past effective_end -> EXPIRED
    for letter in db.letters.values():
        if letter["status"] == "EXECUTED" and letter["effective_end"] < new_now:
            letter["status"] = "EXPIRED"
            touch(letter)
            counts["side_letters_expired"] += 1

    # Step 4: NOTICE_GIVEN practices at/past abandon_effective_date -> ABANDONED + ripple
    for practice in db.practices.values():
        if (practice["status"] == "NOTICE_GIVEN"
                and practice["abandon_effective_date"] is not None
                and practice["abandon_effective_date"] <= new_now):
            practice["status"] = "ABANDONED"
            touch(practice)
            counts["past_practices_abandoned"] += 1
            for clause in db.clauses.values():
                if clause["resolved_by_ref"] == practice["id"] and clause["interpretation_status"] == "RESOLVED":
                    clause["interpretation_status"] = "DISPUTED"
                    touch(clause)

    # Step 5: information requests strictly past due_at -> is_overdue = true
    for info in db.requests.values():
        if (info["status"] in ("RECEIVED", "ACKNOWLEDGED", "IN_PROGRESS", "OBJECTED")
                and info["due_at"] is not None and info["due_at"] < new_now
                and not info["is_overdue"]):
            info["is_overdue"] = True
            touch(info)
            counts["information_requests_overdue"] += 1

    # Step 6: PENDING/IN_PROGRESS expiration tasks strictly past due_date -> MISSED
    for task in db.tasks.values():
        if task["status"] in ("PENDING", "IN_PROGRESS") and task["due_date"] < new_now:
            task["status"] = "MISSED"
            touch(task)
            counts["expiration_tasks_missed"] += 1

    # Step 7: posture refresh for remaining ACTIVE/EXTENDED agreements
    for agreement in db.agreements.values():
        if agreement["status"] in ("ACTIVE", "EXTENDED"):
            new_posture = calc.compute_posture(agreement, new_now)
            if new_posture != agreement["posture"]:
                agreement["posture"] = new_posture
                touch(agreement)
                counts["agreements_posture_refreshed"] += 1

    return counts
