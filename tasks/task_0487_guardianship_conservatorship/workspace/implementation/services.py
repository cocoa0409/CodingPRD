"""Cross-entity domain services: derived-field recomputation, FK resolution,
posture, restricted-account balance, accounting period bucketing, and the
revoke/close cascade shared by terminate and restore.
"""

from datetime import timedelta

from clock import clock, parse_iso
from db import db, stamp_update
from errors import err
from calculations import ACCOUNTING_PERIOD_DAYS


# ---------------------------------------------------------------------------
# FK resolution helpers (priority 4: ERR_REFERENCE_NOT_FOUND on create bodies).
# ---------------------------------------------------------------------------
def resolve_ref(collection, ref_id):
    """Resolve a body FK in `collection`; missing -> ERR_REFERENCE_NOT_FOUND (422)."""
    if not isinstance(ref_id, str) or ref_id not in collection:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource does not exist")
    return collection[ref_id]


def resolve_path(collection, res_id):
    """Resolve a path id; missing -> ERR_NOT_FOUND (404)."""
    if res_id not in collection:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return collection[res_id]


# ---------------------------------------------------------------------------
# Children lookups by case.
# ---------------------------------------------------------------------------
def appointments_for_case(case_id):
    return [a for a in db.appointments.values() if a["case_id"] == case_id]


def accounts_for_case(case_id):
    return [a for a in db.restricted_accounts.values() if a["case_id"] == case_id]


def expenditures_for_case(case_id):
    return [e for e in db.expenditures.values() if e["case_id"] == case_id]


def accountings_for_case(case_id):
    return [a for a in db.accountings.values() if a["case_id"] == case_id]


def reviews_for_case(case_id):
    return [r for r in db.reviews.values() if r["case_id"] == case_id]


def care_plans_for_case(case_id):
    return [c for c in db.care_plans.values() if c["case_id"] == case_id]


def budgets_for_case(case_id):
    return [b for b in db.budgets.values() if b["case_id"] == case_id]


# ---------------------------------------------------------------------------
# Restricted account balance (PRD §2.9, calc restricted_account_available).
# available = principal - encumbered. We maintain principal/encumbered as the
# transitions fire and derive available here.
# ---------------------------------------------------------------------------
def recompute_account_available(account):
    account["available_balance_cents"] = (
        account["principal_balance_cents"] - account["encumbered_cents"]
    )


def touch_account(account):
    recompute_account_available(account)
    stamp_update(account)


# ---------------------------------------------------------------------------
# CarePlan expiry is re-derived on read/operation (PRD §3.8): an ACTIVE plan
# whose window_end has passed (clock now >= window_end) reads as EXPIRED.
# ---------------------------------------------------------------------------
def derive_care_plan_status(plan):
    if plan["status"] == "ACTIVE":
        try:
            end = parse_iso(plan["window_end_iso"])
        except (ValueError, TypeError):
            return plan
        if clock.now_dt() >= end:
            plan["status"] = "EXPIRED"
    return plan


# ---------------------------------------------------------------------------
# Accounting period bucketing: an expenditure's disbursed_at year buckets it.
# ---------------------------------------------------------------------------
def disbursed_year(expenditure):
    if not expenditure.get("disbursed_at"):
        return None
    try:
        return parse_iso(expenditure["disbursed_at"]).year
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# overdue_accounting_count + protection_posture (PRD §2.7, calc
# case_protection_posture). RED > AMBER > GREEN precedence.
# ---------------------------------------------------------------------------
def _period_has_submitted_or_approved_accounting(case):
    """True if any AccountingReport for the current due period is SUBMITTED/APPROVED.

    The "current period" is keyed by the year of next_accounting_due_iso when set.
    """
    due_iso = case.get("next_accounting_due_iso")
    if not due_iso:
        return False
    try:
        due_year = parse_iso(due_iso).year
    except (ValueError, TypeError):
        return False
    for ar in accountings_for_case(case["id"]):
        if ar["period_year"] == due_year and ar["status"] in ("SUBMITTED", "APPROVED"):
            return True
    return False


def recompute_overdue_accounting_count(case):
    count = 0
    if case["status"] in ("ACTIVE", "UNDER_REVIEW"):
        due_iso = case.get("next_accounting_due_iso")
        if due_iso:
            try:
                due_dt = parse_iso(due_iso)
            except (ValueError, TypeError):
                due_dt = None
            if due_dt is not None and clock.now_dt() >= due_dt:
                if not _period_has_submitted_or_approved_accounting(case):
                    count = 1
    case["overdue_accounting_count"] = count
    return count


def recompute_posture(case):
    """Recompute overdue_accounting_count then protection_posture. RED>AMBER>GREEN."""
    overdue = recompute_overdue_accounting_count(case)

    appts = appointments_for_case(case["id"])
    has_active_appt = any(a["status"] == "ACTIVE" for a in appts)
    any_suspended = any(a["status"] == "SUSPENDED" for a in appts)

    accounts = accounts_for_case(case["id"])
    available_below_zero = any(
        acc["available_balance_cents"] < 0 for acc in accounts
    )

    if (case["status"] == "ACTIVE" and not has_active_appt) or overdue >= 2:
        case["protection_posture"] = "RED"
    elif overdue == 1 or available_below_zero or any_suspended:
        case["protection_posture"] = "AMBER"
    else:
        case["protection_posture"] = "GREEN"
    return case["protection_posture"]


def touch_case(case):
    """Recompute posture and bump the case's updated_at/version."""
    recompute_posture(case)
    stamp_update(case)


def recompute_case_posture_only(case):
    """Recompute posture without bumping version (used on read)."""
    recompute_posture(case)


# ---------------------------------------------------------------------------
# Accounting due date math.
# ---------------------------------------------------------------------------
def advance_due_iso(base_iso):
    from clock import _format_iso
    base = parse_iso(base_iso)
    return _format_iso(base + timedelta(days=ACCOUNTING_PERIOD_DAYS))


# ---------------------------------------------------------------------------
# Shared revoke/close cascade for terminate and restore (PRD §3.9).
# ---------------------------------------------------------------------------
def run_revoke_close_cascade(case):
    case_id = case["id"]
    for appt in appointments_for_case(case_id):
        if appt["status"] in ("ACTIVE", "SUSPENDED"):
            was_active = appt["status"] == "ACTIVE"
            appt["status"] = "REVOKED"
            stamp_update(appt)
            # Both ACTIVE and SUSPENDED count as open; decrement either way.
            fid = db.fiduciaries.get(appt["fiduciary_id"])
            if fid is not None:
                fid["open_appointment_count"] = max(0, fid["open_appointment_count"] - 1)
                stamp_update(fid)
            # Exonerate this appointment's APPROVED bond.
            for bond in db.bonds.values():
                if bond["appointment_id"] == appt["id"] and bond["status"] == "APPROVED":
                    bond["status"] = "EXONERATED"
                    stamp_update(bond)
    for acc in accounts_for_case(case_id):
        if acc["status"] in ("OPEN", "FROZEN"):
            acc["status"] = "CLOSED"
            touch_account(acc)


def find_granted_petition_for_case(case_id):
    for pet in db.petitions.values():
        if pet["case_id"] == case_id and pet["status"] == "GRANTED":
            return pet
    return None
