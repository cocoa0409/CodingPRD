"""Transitive cascades (PRD 2.7).

A link here fires because the previous link fired, not because the caller asked
for it.  Every row a cascade mutates is handed to ``db.touch`` so its ``version``
is bumped exactly once for the whole request, no matter how many links reach it.
"""

import calc
import db


def cancel_scheduled_exams(group_id):
    """PRD 314: leaving PRE_OPENING cancels every SCHEDULED exam of the group."""
    for exam in calc.exams_of(group_id):
        if exam["status"] == "SCHEDULED":
            exam["status"] = "CANCELLED"
            db.touch(exam)


def group_left_pre_opening(group, reason):
    """Shared final link: PRE_OPENING -> CONDITIONALLY_APPROVED + exam wipe."""
    if group is None or group["stage"] != "PRE_OPENING":
        return
    group["stage"] = "CONDITIONALLY_APPROVED"
    group["opening_blocked_reason"] = reason
    db.touch(group)
    cancel_scheduled_exams(group["id"])


def filing_posture_cascade(filing):
    """Recompute a filing's posture and run the system-driven regression.

    PRD 256: when a CONDITIONALLY_APPROVED filing sees open_blocking_condition_count
    rise from 0 to a positive number the filing itself falls back to
    ADDITIONAL_INFO_REQUESTED and consumes one information round from the same
    three-round budget an examiner would have used (PRD 248).  The caller owns the
    filing's own ``db.touch`` for the plain recompute case; this helper touches it
    only when the regression actually fires.
    """
    previous = filing.get("open_blocking_condition_count") or 0
    calc.recompute_filing_posture(filing)
    current = filing["open_blocking_condition_count"]
    if previous != 0 or current <= 0:
        return
    if filing["status"] != "CONDITIONALLY_APPROVED":
        return
    if filing["info_request_round"] + 1 > calc.MAX_INFO_ROUNDS:
        # The round budget is exhausted; the filing holds its status and simply
        # loses pre-opening clearance (already false after the recompute).
        return
    filing["status"] = "ADDITIONAL_INFO_REQUESTED"
    filing["info_request_round"] += 1
    calc.recompute_filing_posture(filing)
    db.touch(filing)
    group_left_pre_opening(db.get("groups", filing["group_id"]), "FILING_INFO_REQUESTED")


def raise_shortfall_cascade(raise_row):
    """PRD 228: cleared escrow falling below the minimum unwinds the project.

    ESCROW_LOCKED -> OPEN, the group is flagged ESCROW_SHORTFALL, every SATISFIED
    CAPITAL condition on either filing returns to OPEN with adjudication_count
    incremented, and each affected filing re-derives its posture (which may itself
    pull the filing and then the group backwards).
    """
    if raise_row["status"] != "ESCROW_LOCKED":
        return
    if raise_row["cleared_escrow_cents"] >= raise_row["minimum_gross_cents"]:
        return
    raise_row["status"] = "OPEN"
    db.touch(raise_row)
    group = db.get("groups", raise_row["group_id"])
    if group is not None:
        group["opening_blocked_reason"] = "ESCROW_SHORTFALL"
        db.touch(group)
    for filing in calc.filings_of(raise_row["group_id"]):
        reopened = False
        for cond in calc.conditions_of(filing["id"]):
            if cond["category"] == "CAPITAL" and cond["status"] == "SATISFIED":
                cond["status"] = "OPEN"
                cond["adjudication_count"] += 1
                db.touch(cond)
                reopened = True
        if reopened:
            filing_posture_cascade(filing)
            db.touch(filing)


def policy_rejected_cascade(policy):
    """PRD 283: the deepest chain in the service.

    Reaches only the CHARTERING_AUTHORITY filing and only POLICY-category
    conditions that were SATISFIED; a merely OPEN policy condition is left alone
    and the deposit insurer's filing is untouched.
    """
    filing = calc.filing_by_authority(policy["group_id"], "CHARTERING_AUTHORITY")
    if filing is None:
        return
    failed = False
    for cond in calc.conditions_of(filing["id"]):
        if cond["category"] == "POLICY" and cond["status"] == "SATISFIED":
            cond["status"] = "FAILED"
            cond["adjudication_count"] += 1
            db.touch(cond)
            failed = True
    if failed:
        filing_posture_cascade(filing)
        db.touch(filing)


def filing_denied_cascade(filing):
    """PRD 252: a denial reverts the group and un-pins every PINNED plan."""
    group = db.get("groups", filing["group_id"])
    if group is None:
        return
    if group["stage"] == "UNDER_REVIEW":
        group["stage"] = "ORGANIZING"
        group["opening_blocked_reason"] = "FILING_INFO_REQUESTED"
        db.touch(group)
    for plan in calc.plans_of(group["id"]):
        if plan["status"] == "PINNED":
            plan["status"] = "SUBMITTED"
            db.touch(plan)


def contract_terminated_cascade(contract):
    """PRD 286: termination cancels live windows and empties active_window_count."""
    for window in calc.windows_of(contract["id"]):
        if window["status"] in ("RESERVED", "CONFIRMED"):
            window["status"] = "CANCELLED"
            db.touch(window)
    calc.recompute_contract_windows(contract)


def exam_deficient_cascade(group):
    """PRD 302: a DEFICIENT result knocks the group out of PRE_OPENING.

    The deficient examination has already left SCHEDULED by the time this runs, so
    the shared exam wipe leaves it in place as the audit record.
    """
    group_left_pre_opening(group, "EXAM_DEFICIENT")


def group_abandoned_cascade(group):
    """PRD 238: abandonment refunds every funded subscription and the raise."""
    raise_row = calc.raise_in(group["id"], ("STRUCTURING", "OPEN", "ESCROW_LOCKED"))
    if raise_row is None:
        return
    for sub in calc.subscriptions_of(raise_row["id"]):
        if sub["funding_state"] == "FUNDED":
            sub["funding_state"] = "REFUNDED"
            db.touch(sub)
    calc.recompute_raise(raise_row)
    raise_row["status"] = "REFUNDED"
    db.touch(raise_row)
