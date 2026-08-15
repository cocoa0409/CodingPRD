"""Business logic: derived fields, calculations, state transitions, cascades.

All temporal rules read the logical clock (db.CLOCK), never wall-clock time.
Derived fields (verification_posture, alert_tier, CE tallies, screening_posture,
work_authorization / restriction_reason, money counters) are recomputed from
source records at every mutation point and on read, so they never drift.
"""
from datetime import timedelta
from decimal import Decimal

from db import DB, current_date, now_iso
from util import add_months, parse_ymd, round_half_up_decimal, num_str

EMPLOYER_COMMITTED_CAP_CENTS = 1000000
EMPLOYER_PAID_CAP_CENTS = 1000000

LICENSE_TERMINAL = {"REVOKED"}

# Employee restriction-reason precedence, high -> low (PRD 3.2).
REASON_PRECEDENCE = [
    "SCREENING_FLAGGED",
    "LICENSE_SUSPENDED",
    "LICENSE_LAPSED",
    "VERIFICATION_OVERDUE",
    "MISSING_LICENSE",
]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def touch(entity):
    """Refresh updated_at and bump the optimistic-concurrency counter."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# License derived fields (PRD 3.3-3.5)
# ---------------------------------------------------------------------------

def compute_verification_posture(lic):
    if lic["last_verified_on"] is None:
        return "NEVER_VERIFIED"
    nvd = parse_ymd(lic["next_verification_due_on"])
    if current_date() > nvd:  # strict >; equal is still CURRENT
        return "OVERDUE"
    return "CURRENT"


def compute_alert_tier(lic):
    if lic["status"] not in ("PENDING_VERIFICATION", "ACTIVE"):
        return "AT_EXPIRY"
    days_until = (parse_ymd(lic["expires_on"]) - current_date()).days
    if days_until >= 91:
        return "NONE"
    if days_until >= 61:
        return "T90"
    if days_until >= 31:
        return "T60"
    if days_until >= 1:
        return "T30"
    return "AT_EXPIRY"


def compute_ce_tallies(lic):
    """Return (cycle_hours, rolling_hours) as Decimals over VALIDATED activities."""
    lt = DB["license_types"][lic["license_type_id"]]
    anchor = parse_ymd(lic["ce_cycle_anchor_on"])
    cycle_end = min(
        add_months(anchor, lt["cycle_length_months"]), parse_ymd(lic["expires_on"])
    )
    today = current_date()
    rolling_start = today - timedelta(days=364)
    cycle_total = Decimal("0")
    rolling_total = Decimal("0")
    for act in DB["ce_activities"].values():
        if act["license_id"] != lic["id"] or act["status"] != "VALIDATED":
            continue
        completed = parse_ymd(act["completed_on"])
        hours = Decimal(str(act["rounded_hours"]))
        if anchor <= completed <= cycle_end:
            cycle_total += hours
        if rolling_start <= completed <= today:
            rolling_total += hours
    return cycle_total, rolling_total


def refresh_license_derived(lic):
    """Recompute posture / tier / CE tallies / progress percentages in place."""
    lt = DB["license_types"][lic["license_type_id"]]
    lic["verification_posture"] = compute_verification_posture(lic)
    lic["alert_tier"] = compute_alert_tier(lic)
    cycle_total, rolling_total = compute_ce_tallies(lic)
    lic["cycle_ce_hours_validated"] = num_str(cycle_total)
    lic["rolling_ce_hours_validated"] = num_str(rolling_total)
    required = lt["ce_hours_required_per_cycle"]
    if required == 0:
        lic["ce_progress_reported_pct"] = None
        lic["ce_progress_required_pct"] = None
    else:
        req = Decimal(str(required))
        lic["ce_progress_reported_pct"] = num_str(
            round_half_up_decimal((cycle_total * 100) / req, "0.01")
        )
        lic["ce_progress_required_pct"] = num_str(
            round_half_up_decimal((rolling_total * 100) / req, "0.01")
        )


# ---------------------------------------------------------------------------
# Employee derived fields (PRD 3.2)
# ---------------------------------------------------------------------------

def compute_screening_posture(employee_id):
    statuses = [
        s["status"]
        for s in DB["exclusion_screenings"].values()
        if s["employee_id"] == employee_id
    ]
    if "CONFIRMED_MATCH" in statuses:
        return "FLAGGED"
    if "UNDER_REVIEW" in statuses:
        return "PENDING_REVIEW"
    return "CLEAR"


def compute_restriction(emp):
    """Return (work_authorization, restriction_reason) for the employee."""
    required_rows = [
        r
        for r in DB["role_requirements"].values()
        if r["role_code"] == emp["role_code"] and r["is_required"]
    ]
    active = set()

    if compute_screening_posture(emp["id"]) == "FLAGGED":
        active.add("SCREENING_FLAGGED")

    for row in required_rows:
        matches = [
            lic
            for lic in DB["licenses"].values()
            if lic["employee_id"] == emp["id"]
            and lic["license_type_id"] == row["license_type_id"]
            and lic["state_code"] == row["state_code"]
        ]
        if any(lic["status"] == "SUSPENDED" for lic in matches):
            active.add("LICENSE_SUSPENDED")
        if any(lic["status"] in ("LAPSED", "REVOKED") for lic in matches):
            active.add("LICENSE_LAPSED")
        if any(
            lic["status"] == "ACTIVE" and lic["verification_posture"] == "OVERDUE"
            for lic in matches
        ):
            active.add("VERIFICATION_OVERDUE")
        if not matches or all(
            lic["status"] == "PENDING_VERIFICATION" for lic in matches
        ):
            active.add("MISSING_LICENSE")

    for reason in REASON_PRECEDENCE:
        if reason in active:
            return "RESTRICTED", reason
    return "AUTHORIZED", None


def compute_money_counters(employee_id):
    committed = 0
    paid = 0
    for req in DB["renewal_requests"].values():
        lic = DB["licenses"].get(req["license_id"])
        if lic is None or lic["employee_id"] != employee_id:
            continue
        if req["status"] in ("SUBMITTED", "MORE_INFO"):
            committed += req["claimed_amount_cents"]
        elif req["status"] == "APPROVED":
            committed += req["approved_amount_cents"]
        elif req["status"] == "PAID":
            paid += req["approved_amount_cents"]
    return committed, paid


def refresh_employee_derived(emp, bump=False):
    """Recompute the employee's derived fields in place.

    With bump=True, increments version / refreshed updated_at only when a
    persisted derived field actually changed (a genuine cascade mutation).
    """
    changed = False
    posture = compute_screening_posture(emp["id"])
    if emp["screening_posture"] != posture:
        emp["screening_posture"] = posture
        changed = True
    auth, reason = compute_restriction(emp)
    if emp["work_authorization"] != auth:
        emp["work_authorization"] = auth
        changed = True
    if emp["restriction_reason"] != reason:
        emp["restriction_reason"] = reason
        changed = True
    committed, paid = compute_money_counters(emp["id"])
    if emp["reimbursement_committed_cents"] != committed:
        emp["reimbursement_committed_cents"] = committed
        changed = True
    if emp["reimbursement_paid_cents"] != paid:
        emp["reimbursement_paid_cents"] = paid
        changed = True
    if changed and bump:
        touch(emp)
    return changed


# ---------------------------------------------------------------------------
# Audit-package invalidation (PRD 3.9): a sealed package flips to INVALIDATED
# when a dependent fact lands inside [period_start, period_end).
# ---------------------------------------------------------------------------

def invalidate_sealed_packages(employee_id, occurred_on):
    if not occurred_on:
        return
    day = parse_ymd(occurred_on) if isinstance(occurred_on, str) else occurred_on
    for pkg in DB["audit_packages"].values():
        if pkg["employee_id"] != employee_id or pkg["status"] != "SEALED":
            continue
        start = parse_ymd(pkg["period_start"])
        end = parse_ymd(pkg["period_end"])
        if start <= day < end:
            pkg["status"] = "INVALIDATED"
            touch(pkg)


# ---------------------------------------------------------------------------
# Expiry sweep (PRD 3.5) — runs whenever the logical clock advances.
# ---------------------------------------------------------------------------

def run_expiry_sweep():
    today = current_date()
    licenses = sorted(
        DB["licenses"].values(),
        key=lambda l: (parse_ymd(l["expires_on"]), l["created_at"]),
    )
    affected_employees = set()
    for lic in licenses:
        lt = DB["license_types"][lic["license_type_id"]]
        expires = parse_ymd(lic["expires_on"])
        if lic["status"] == "ACTIVE" and today > expires:
            lic["status"] = "EXPIRED"
            lic["alert_tier"] = "AT_EXPIRY"
            touch(lic)
            affected_employees.add(lic["employee_id"])
        if lic["status"] == "EXPIRED":
            grace_end = expires + timedelta(days=lt["grace_period_days"])
            if today > grace_end:
                lic["status"] = "LAPSED"
                lic["alert_tier"] = "AT_EXPIRY"
                touch(lic)
                affected_employees.add(lic["employee_id"])
    # Refresh posture/tier for every still-pending or active license.
    for lic in licenses:
        if lic["status"] in ("PENDING_VERIFICATION", "ACTIVE"):
            before = (lic["verification_posture"], lic["alert_tier"])
            refresh_license_derived(lic)
            after = (lic["verification_posture"], lic["alert_tier"])
            if before != after:
                touch(lic)
                affected_employees.add(lic["employee_id"])
    # Re-derive work authorization for every affected holder.
    for employee_id in affected_employees:
        emp = DB["employees"].get(employee_id)
        if emp is not None:
            refresh_employee_derived(emp, bump=True)
