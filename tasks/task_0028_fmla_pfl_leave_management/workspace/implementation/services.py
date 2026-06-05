"""Shared mutation helpers: timestamps, version bumps, common-field initialization, notice issuance."""
from datetime import timedelta

import db
import clock
import calculations
from errors import APIError
import errors as E


PFL_ENABLED_STATES = {"CA", "NY", "NJ", "MA", "WA", "CT", "RI", "CO", "OR"}
ALL_STATE_CODES = PFL_ENABLED_STATES | {"FED"}


def init_common(entity):
    now = clock.now_utc()
    entity["id"] = db.new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity):
    """Bump version and refresh updated_at on a mutation that modifies a non-system field."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = clock.now_utc()


# ---------------------------------------------------------------------------
# Notice helpers
# ---------------------------------------------------------------------------

def create_notice(leave_case, notice_type, response_window_days=None):
    now = clock.now_utc()
    n = {
        "leave_case_id": leave_case["id"],
        "notice_type": notice_type,
        "sent_at": now,
        "response_due_at": (now + timedelta(days=response_window_days))
            if response_window_days is not None else None,
        "response_received": False,
    }
    init_common(n)
    db.notices[n["id"]] = n
    return n


def _refresh_response_received(case_id):
    """Recompute response_received on CERTIFICATION_DEMAND / RECERTIFICATION_REQUEST notices."""
    notices_for_case = [n for n in db.notices.values() if n["leave_case_id"] == case_id]
    certs = sorted((c for c in db.certifications.values() if c["leave_case_id"] == case_id),
                   key=lambda c: c["created_at"])
    for n in notices_for_case:
        if n["notice_type"] not in ("CERTIFICATION_DEMAND", "RECERTIFICATION_REQUEST"):
            continue
        # A notice is satisfied when SOME CertificationRecord on the case reaches
        # RECEIVED with received_at <= response_due_at, and the cert was created
        # after the notice was issued (i.e., it is a response to this demand).
        if n["response_due_at"] is None:
            continue
        for c in certs:
            if c.get("received_at") is None:
                continue
            if c["created_at"] < n["sent_at"]:
                continue
            if c["received_at"] <= n["response_due_at"]:
                if not n["response_received"]:
                    n["response_received"] = True
                    touch(n)
                break


# ---------------------------------------------------------------------------
# Employee derived state helpers
# ---------------------------------------------------------------------------

def set_employment_status(employee, status):
    if employee["employment_status"] != status:
        employee["employment_status"] = status
        touch(employee)


def set_job_restoration_deadline(employee, deadline_or_none):
    if employee.get("job_restoration_deadline") != deadline_or_none:
        employee["job_restoration_deadline"] = deadline_or_none
        touch(employee)


# ---------------------------------------------------------------------------
# Cascade: ledger DELINQUENT → case.job_restoration_protected = false
# ---------------------------------------------------------------------------

def cascade_delinquent_ledger(ledger):
    case = db.leave_cases.get(ledger["leave_case_id"])
    if case is None:
        return
    changed = False
    if case.get("job_restoration_protected", False):
        case["job_restoration_protected"] = False
        changed = True
    if changed:
        touch(case)
    # If the associated employee currently has a restoration deadline tied to this case,
    # that deadline should be reconsidered. Per PRD §3.7, the cascade "may further unset
    # Employee.job_restoration_deadline if the affected case's restoration window is now invalid."
    employee = db.employees.get(case["employee_id"])
    if employee is not None and employee.get("job_restoration_deadline") is not None:
        # If this case was the active source of protection and protection is now false,
        # clear deadline if employee is currently ON_LEAVE on this case (no protection left).
        if employee["employment_status"] == "ON_LEAVE" and not case["job_restoration_protected"]:
            set_job_restoration_deadline(employee, None)


def auto_delinquency_sweep():
    """Run after clock advance: transition any past-due PENDING/PARTIAL ledger to DELINQUENT."""
    now = clock.now_utc()
    flipped_ids = []
    for ledger in db.ledgers.values():
        if ledger["payment_status"] not in ("PENDING", "PARTIAL"):
            continue
        if ledger["employee_owes_cents"] <= 0:
            continue
        cutoff = ledger["period_end"] + timedelta(days=30)
        if now > cutoff:
            ledger["payment_status"] = "DELINQUENT"
            touch(ledger)
            cascade_delinquent_ledger(ledger)
            flipped_ids.append(ledger["id"])
    return flipped_ids


# ---------------------------------------------------------------------------
# Helpers used by route layer
# ---------------------------------------------------------------------------

def latest_certification_for_case(case_id):
    cs = [c for c in db.certifications.values() if c["leave_case_id"] == case_id]
    if not cs:
        return None
    cs.sort(key=lambda c: c["created_at"])
    return cs[-1]


def all_certifications_for_case(case_id):
    return sorted((c for c in db.certifications.values() if c["leave_case_id"] == case_id),
                  key=lambda c: c["created_at"])


def intervals_for_case(case_id):
    return sorted((i for i in db.intervals.values() if i["leave_case_id"] == case_id),
                  key=lambda i: i["start_datetime"])


def compute_pfl_concurrent(employer, employee, leave_case):
    if not employer["pfl_enabled"]:
        return False
    if employee["home_state_code"] != employer["state_code"]:
        return False
    return leave_case["qualifying_reason"] in (
        "OWN_SERIOUS_HEALTH_CONDITION",
        "FAMILY_SERIOUS_HEALTH_CONDITION",
        "NEW_CHILD_BONDING",
    )


def update_response_received_for_case(case_id):
    _refresh_response_received(case_id)


# ---------------------------------------------------------------------------
# Benefit-continuation ledger recomputation
# ---------------------------------------------------------------------------
# PRD §3.7: "The ledger row is recomputed monthly while the case is `ACTIVE`,
# and once more when the case completes to prorate the final partial month."
# Triggered after recording or reversing a `LeaveInterval` so the leave-fraction
# reflects the live set of `RECORDED` intervals on the case (PRD §3.7 formula).
def recompute_ledger_rows_for_case(case_id):
    case = db.leave_cases.get(case_id)
    if case is None:
        return
    employee = db.employees.get(case["employee_id"])
    if employee is None:
        return
    employer = db.employers.get(employee["employer_id"])
    if employer is None:
        return
    monthly_total = employer["monthly_premium_total_cents"]
    employer_pct = employer["employer_premium_share_pct"]
    intervals = [i for i in db.intervals.values()
                 if i["leave_case_id"] == case_id and i["status"] == "RECORDED"]
    for ledger in list(db.ledgers.values()):
        if ledger["leave_case_id"] != case_id:
            continue
        # Don't recompute terminal rows.
        if ledger["payment_status"] in ("PAID", "DELINQUENT"):
            continue
        employer_share, employee_share = calculations.benefit_continuation_premium(
            ledger["period_start"], ledger["period_end"],
            monthly_total, employer_pct, intervals,
        )
        changed = False
        if ledger["employer_premium_share_cents"] != employer_share:
            ledger["employer_premium_share_cents"] = employer_share
            changed = True
        if ledger["employee_premium_share_cents"] != employee_share:
            ledger["employee_premium_share_cents"] = employee_share
            changed = True
        new_owes = employee_share - ledger["payments_received_cents"]
        if new_owes < 0:
            new_owes = 0
        if ledger["employee_owes_cents"] != new_owes:
            ledger["employee_owes_cents"] = new_owes
            changed = True
        # Recompute payment_status (PENDING/PARTIAL/PAID) while non-terminal.
        # PRD §3.7: PAID when applied amount equals outstanding balance; PARTIAL
        # while a positive balance remains with some payments; PENDING with no
        # payments received.
        recv = ledger["payments_received_cents"]
        if employee_share > 0 and recv >= employee_share:
            new_status = "PAID"
        elif recv > 0:
            new_status = "PARTIAL"
        else:
            new_status = "PENDING"
        if ledger["payment_status"] != new_status:
            ledger["payment_status"] = new_status
            changed = True
        if changed:
            touch(ledger)
