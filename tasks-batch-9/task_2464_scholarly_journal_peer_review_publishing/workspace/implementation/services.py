"""Cascades, conserved counters and shared state guards.

Every mutation a request performs - including rows it touches only as a side
effect - runs through touch(), so each mutated row's version advances by
exactly 1 per request (PRD Section 2.9).
"""

import calc
from db import add_days, now, now_iso, ordered, parse_ts, stamp_new, store, touch
from errors import ApiError

MANUSCRIPT_TERMINAL = ("DESK_REJECTED", "RETRACTED")
ASSIGNMENT_TERMINAL = ("RECUSED", "RELEASED")
INVITATION_CLOSED = ("DECLINED", "EXPIRED", "SUBMITTED", "WITHDRAWN")
APPEAL_TERMINAL = ("UPHELD", "OVERTURNED")
ETHICS_TERMINAL = ("RESOLVED_NO_ACTION", "CORRECTION_ISSUED", "RETRACTION_APPROVED")
INVOICE_TERMINAL = ("PAID", "WAIVED", "CANCELLED")


# ==========================================================================
# terminal-state guards (ladder rule 14)
# ==========================================================================
def guard_manuscript_terminal(manuscript):
    if manuscript["status"] in MANUSCRIPT_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def guard_assignment_terminal(assignment):
    if assignment["state"] in ASSIGNMENT_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def guard_invitation_terminal(invitation):
    if invitation["state"] in INVITATION_CLOSED:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def guard_appeal_terminal(appeal):
    if appeal["state"] in APPEAL_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def guard_ethics_terminal(case):
    if case["state"] in ETHICS_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def guard_invoice_terminal(invoice):
    if invoice["status"] in INVOICE_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def guard_job_terminal(job):
    if job["content_stage"] == "TERMINATED" or job["clearance_stage"] == "WITHDRAWN":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")


def require_active_assignment(manuscript, actor):
    """Exactly one ACTIVE assignment on the manuscript, held by the caller."""
    assignment = calc.active_assignment_of(manuscript["id"])
    if assignment is None or assignment["editor_id"] != actor.user_id:
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")
    return assignment


# ==========================================================================
# small mutators
# ==========================================================================
def set_field(row, key, value):
    """Assign only when the value actually changes, so version never drifts."""
    if row.get(key) == value:
        return False
    row[key] = value
    touch(row)
    return True


def set_manuscript_status(manuscript, status):
    manuscript["status"] = status
    touch(manuscript)


# ==========================================================================
# reviewer reliability and shortfall
# ==========================================================================
def recompute_reliability(reviewer):
    """Write both variants, then reconsider the reviewer's status.

    Returns True when this recomputation moved the reviewer ACTIVE -> PROBATION.
    """
    rolling, rolling_closed = calc.reliability_score(reviewer["id"], "ROLLING")
    lifetime, _ = calc.reliability_score(reviewer["id"], "LIFETIME")
    reviewer["reliability_score_rolling"] = rolling
    reviewer["reliability_score_lifetime"] = lifetime
    demoted = False
    if reviewer["status"] == "ACTIVE":
        if rolling < calc.PROBATION_FLOOR and rolling_closed >= calc.PROBATION_MIN_CLOSED:
            reviewer["status"] = "PROBATION"
            demoted = True
    elif reviewer["status"] == "PROBATION":
        if rolling >= calc.REINSTATE_CEILING:
            reviewer["status"] = "ACTIVE"
    touch(reviewer)
    return demoted


def recompute_shortfall(manuscript):
    """Returns True only when the flag flipped from false to true."""
    value = calc.shortfall_value(manuscript)
    if bool(manuscript["review_shortfall_flag"]) == value:
        return False
    manuscript["review_shortfall_flag"] = value
    touch(manuscript)
    return value


# ==========================================================================
# invitation closure
# ==========================================================================
def close_invitation(invitation, state, closed_reason):
    invitation["state"] = state
    invitation["closed_reason"] = closed_reason
    touch(invitation)


def release_open_load(reviewer):
    reviewer["open_invitation_count"] = max(0, int(reviewer["open_invitation_count"]) - 1)


def withdraw_open_invitations(manuscript, closed_reason):
    """Decision cascade links 2-4, in invitation created_at ascending order."""
    demoted = 0
    for invitation in ordered(calc.open_invitations_of_manuscript(manuscript["id"])):
        close_invitation(invitation, "WITHDRAWN", closed_reason)
        reviewer = store.reviewers.get(invitation["reviewer_id"])
        if reviewer is None:
            continue
        release_open_load(reviewer)
        if recompute_reliability(reviewer):
            demoted += 1
    return demoted


# ==========================================================================
# editor assignments
# ==========================================================================
def create_assignment(manuscript, editor, selected_by, replaced_assignment_id=None):
    row = {
        "manuscript_id": manuscript["id"],
        "editor_id": editor["id"],
        "selected_by": selected_by,
        "state": "PROPOSED",
        "declared_conflict": None,
        "conflict_type": None,
        "replaced_assignment_id": replaced_assignment_id,
        "released_reason": None,
    }
    stamp_new(row)
    store.assignments[row["id"]] = row
    editor["active_assignment_count"] = int(editor["active_assignment_count"]) + 1
    touch(editor)
    return row


def run_replacement_selection(manuscript, replaced_assignment_id=None, exclude_editor_ids=()):
    """Selector inside a cascade: an empty pool sets handling_gap_flag, no error."""
    editor = calc.select_editor(manuscript, exclude_editor_ids)
    if editor is None:
        set_field(manuscript, "handling_gap_flag", True)
        return None
    return create_assignment(manuscript, editor, "SELECTOR", replaced_assignment_id)


def recuse_assignment(assignment, manuscript):
    assignment["state"] = "RECUSED"
    assignment["released_reason"] = "RECUSAL"
    touch(assignment)
    editor = store.editors.get(assignment["editor_id"])
    if editor is not None:
        editor["active_assignment_count"] = max(0, int(editor["active_assignment_count"]) - 1)
        touch(editor)
    run_replacement_selection(manuscript, assignment["id"])


def release_active_assignment(manuscript):
    for assignment in calc.assignments_of_manuscript(manuscript["id"]):
        if assignment["state"] != "ACTIVE":
            continue
        assignment["state"] = "RELEASED"
        assignment["released_reason"] = "DECISION_FINAL"
        touch(assignment)
        editor = store.editors.get(assignment["editor_id"])
        if editor is not None:
            editor["active_assignment_count"] = max(
                0, int(editor["active_assignment_count"]) - 1
            )
            touch(editor)


# ==========================================================================
# ethics cases
# ==========================================================================
def open_ethics_case(manuscript, case_type, severity, description, opened_by, opener_user_id):
    row = {
        "manuscript_id": manuscript["id"],
        "case_type": case_type,
        "severity": severity,
        "opened_by": opened_by,
        "state": "OPEN",
        "description": description,
        "resolution_statement": None,
        "resolved_at": None,
    }
    stamp_new(row)
    row["_opened_by_user_id"] = opener_user_id
    store.ethics_cases[row["id"]] = row
    return row


def retraction_cascade(manuscript):
    """Links 2-4 of the retraction cascade; link 1 is the case's own resolution."""
    manuscript["status"] = "RETRACTED"
    manuscript["retracted_at"] = now_iso()
    touch(manuscript)
    job = calc.production_job_of_manuscript(manuscript["id"])
    if job is not None:
        job["content_stage"] = "TERMINATED"
        job["clearance_stage"] = "WITHDRAWN"
        job["indexing_status"] = "WITHDRAWN"
        touch(job)
    journal = calc.journal_of(manuscript)
    journal["published_article_count"] = max(0, int(journal["published_article_count"]) - 1)
    journal["retracted_article_count"] = int(journal["retracted_article_count"]) + 1
    touch(journal)


# ==========================================================================
# production and fees
# ==========================================================================
def create_production_job(manuscript):
    row = {
        "manuscript_id": manuscript["id"],
        "content_stage": "COPYEDITING",
        "clearance_stage": "LICENSE_PENDING",
        "proof_round": 0,
        "slot_start": None,
        "slot_end": None,
        "archival_repository": None,
        "deposit_reference": None,
        "indexing_status": "NOT_INDEXED",
        "issue_label": None,
        "published_at": None,
    }
    stamp_new(row)
    store.production_jobs[row["id"]] = row
    return row


def advance_fee_clearance(manuscript, ignore_invoice_id=None):
    """LICENSE_PENDING -> FEE_CLEARED once no invoice of the manuscript is ISSUED.

    A zero-total invoice "needs no settlement at all", so its own ISSUED status
    does not hold the clearance dimension back at its issuance (PRD 3.9).
    """
    job = calc.production_job_of_manuscript(manuscript["id"])
    if job is None:
        return None
    if job["clearance_stage"] != "LICENSE_PENDING":
        return None
    if any(
        i["status"] == "ISSUED" and i["id"] != ignore_invoice_id
        for i in calc.invoices_of_manuscript(manuscript["id"])
    ):
        return None
    job["clearance_stage"] = "FEE_CLEARED"
    touch(job)
    return job


# ==========================================================================
# reminder and expiry sweep
# ==========================================================================
def run_reminder_sweep(journal):
    reminded = 0
    expired = 0
    demoted = 0
    shortfall_ids = []

    candidates = []
    for invitation in store.invitations.values():
        if invitation["state"] != "INVITED":
            continue
        manuscript = store.manuscripts.get(invitation["manuscript_id"])
        if manuscript is None or manuscript["journal_id"] != journal["id"]:
            continue
        candidates.append(invitation)

    for invitation in ordered(candidates):
        due_at = parse_ts(invitation["due_at"])
        if due_at is not None and now() >= due_at:
            close_invitation(invitation, "EXPIRED", "SWEEP_EXPIRY")
            expired += 1
            reviewer = store.reviewers.get(invitation["reviewer_id"])
            if reviewer is not None:
                reviewer["expired_count"] = int(reviewer["expired_count"]) + 1
                release_open_load(reviewer)
                if recompute_reliability(reviewer):
                    demoted += 1
            manuscript = store.manuscripts.get(invitation["manuscript_id"])
            if manuscript is not None and recompute_shortfall(manuscript):
                if manuscript["id"] not in shortfall_ids:
                    shortfall_ids.append(manuscript["id"])
            continue

        anchor = parse_ts(invitation["last_reminder_at"]) or parse_ts(invitation["invited_at"])
        if anchor is None:
            continue
        if int(invitation["reminder_count"]) >= int(journal["max_reminders_per_invitation"]):
            continue
        if now() < add_days(anchor, int(journal["reminder_cadence_days"])):
            continue
        invitation["reminder_count"] = int(invitation["reminder_count"]) + 1
        invitation["last_reminder_at"] = now_iso()
        touch(invitation)
        reminded += 1

    return {
        "reminded_invitation_count": reminded,
        "expired_invitation_count": expired,
        "probation_reviewer_count": demoted,
        "shortfall_manuscript_ids": shortfall_ids,
    }
