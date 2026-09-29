"""Ledger discipline (PRD §2.10) and the involuntary cascades (PRD §2.9, §3.3)."""
import clock
import db
from constants import MEMOS, REVIEWABLE_STATUSES
from services import calculations


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
def append_ledger(application, entry_type, amount_cents):
    entry = db.make_row({
        "application_id": application["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "memo": MEMOS[entry_type],
    }, audited=False)
    db.ledger_entries[entry["id"]] = entry
    return entry


def recompute_balance(application):
    application["fee_balance_cents"] = calculations.fee_balance_cents(
        application["id"])


# ---------------------------------------------------------------------------
# permits
# ---------------------------------------------------------------------------
def active_permits(application_id):
    return db.ordered([p for p in db.permits.values()
                       if p["application_id"] == application_id
                       and p["status"] == "ACTIVE"])


def revoke_permit(permit, reason_code):
    """TemporaryPermit ACTIVE -> REVOKED with its full (never prorated) reversal."""
    now = clock.now()
    permit["status"] = "REVOKED"
    permit["revoked_at"] = now
    permit["expires_at"] = now
    permit["revocation_reason_code"] = reason_code
    db.touch(permit)
    application = db.applications[permit["application_id"]]
    append_ledger(application, "PERMIT_FEE_REVERSAL", -permit["permit_fee_cents"])
    recompute_balance(application)
    db.touch(application)
    return permit


def convert_permit(permit, license_row):
    """TemporaryPermit ACTIVE -> CONVERTED (approval cascade links 2 and 3).

    The application's own version is bumped once by the approval as a whole,
    so this helper deliberately does not touch it.
    """
    now = clock.now()
    pre_truncation_expires_at = permit["expires_at"]
    permit["status"] = "CONVERTED"
    permit["converted_at"] = now
    permit["expires_at"] = now
    db.touch(permit)
    application = db.applications[permit["application_id"]]
    credit = calculations.permit_conversion_credit_cents(
        permit, pre_truncation_expires_at, now)
    append_ledger(application, "CONVERSION_CREDIT", -credit)
    recompute_balance(application)
    if license_row.get("converted_from_permit_id") is None:
        license_row["converted_from_permit_id"] = permit["id"]
    return permit


# ---------------------------------------------------------------------------
# review assignments
# ---------------------------------------------------------------------------
def open_assignments(application_id):
    return db.ordered([a for a in db.assignments.values()
                       if a["application_id"] == application_id
                       and a["status"] == "ASSIGNED"])


def _close_assignment(assignment, status):
    assignment["status"] = status
    assignment["closed_at"] = clock.now()
    db.touch(assignment)
    evaluator = db.evaluators.get(assignment["evaluator_id"])
    if evaluator is not None:
        calculations.refresh_open_assignment_count(evaluator)
        db.touch(evaluator)


def release_assignments(application_id):
    for assignment in open_assignments(application_id):
        _close_assignment(assignment, "RELEASED")


def complete_assignments(application_id):
    for assignment in open_assignments(application_id):
        _close_assignment(assignment, "COMPLETED")


# ---------------------------------------------------------------------------
# leaving the reviewable set (PRD §2.9)
# ---------------------------------------------------------------------------
def leave_reviewable_cascade(application, reason_code):
    for permit in active_permits(application["id"]):
        revoke_permit(permit, reason_code)
    release_assignments(application["id"])


# ---------------------------------------------------------------------------
# disciplinary recomputation and its cascades (PRD §3.3)
# ---------------------------------------------------------------------------
def _applications_of(applicant_id):
    return db.ordered([a for a in db.applications.values()
                       if a["applicant_id"] == applicant_id])


def _suspend_cascade(applicant):
    for application in _applications_of(applicant["id"]):
        if application["status"] in REVIEWABLE_STATUSES:
            application["status"] = "SUSPENDED_REVIEW"
            db.touch(application)
            leave_reviewable_cascade(application, "DISCIPLINARY_ACTION")


def _restore_cascade(applicant):
    for application in _applications_of(applicant["id"]):
        if application["status"] == "SUSPENDED_REVIEW":
            has_evaluation = any(
                e["application_id"] == application["id"]
                for e in db.evaluations.values())
            application["status"] = "UNDER_REVIEW" if has_evaluation else "SUBMITTED"
            db.touch(application)


def recompute_applicant_discipline(applicant):
    """Recompute both risk-index variants and good_standing_flag, increment the
    applicant's version, and run whichever cascade the flag transition demands."""
    before = applicant["good_standing_flag"]
    reported, effective, good_standing = calculations.disciplinary_risk_indexes(
        applicant["id"])
    applicant["disciplinary_risk_index_reported"] = reported
    applicant["disciplinary_risk_index_effective"] = effective
    applicant["good_standing_flag"] = good_standing
    db.touch(applicant)
    if before and not good_standing:
        _suspend_cascade(applicant)
    elif (not before) and good_standing:
        _restore_cascade(applicant)
