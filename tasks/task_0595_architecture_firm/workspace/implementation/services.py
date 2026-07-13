"""Serialisation, calculations (PRD 3.3 / 3.4 / 3.7 / 3.9), cascades and RBAC scoping."""

from datetime import timedelta
from decimal import Decimal

from core import (
    ApiError,
    ROLE_CLIENT,
    ROLE_CONSULTANT,
    ROLE_PM,
    ROLE_PRINCIPAL,
    ROLE_STAFF,
    bump,
    clock_now,
    d,
    db,
    fmt_dt,
    parse_dt,
    round_half_up_2,
    round_half_up_int,
)

PHASE_ORDER = {"SD": 1, "DD": 2, "CD": 3, "CA": 4}
MAX_CLARIFICATION_ROUNDS = 2
BILLING_THRESHOLD_PCT = 50
RETAINAGE_TIER_1_BP = 1000
RETAINAGE_TIER_2_BP = 500
RETAINAGE_TIER_3_BP = 0
WEEKEND = (5, 6)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
_COMMON = ("id", "created_at", "updated_at", "version")

_FIELDS = {
    "staff": ("full_name", "title", "billing_rate_cents_per_hour",
              "cost_rate_cents_per_hour", "active"),
    "consultant": ("name", "discipline", "concurrent_review_capacity", "status"),
    "project": ("project_number", "name", "client_rep_user_id", "project_manager_staff_id",
                "status", "labor_budget_cents", "labor_cost_cents", "approved_hours",
                "budget_posture", "open_rfi_count", "ca_posture"),
    "contract": ("project_id", "fee_basis", "construction_cost_estimate_cents", "fee_rate_bp",
                 "not_to_exceed_cents", "review_clock_basis", "submittal_review_period_days",
                 "status", "base_fee_cents", "total_fee_cents", "earned_to_date_cents",
                 "billed_fee_to_date_cents", "wip_balance_cents"),
    "phase": ("project_id", "phase_code", "phase_order", "weight_bp", "status",
              "percent_complete", "fee_allocation_cents", "earned_cents", "milestone_name",
              "milestone_due_at", "milestone_status", "is_billing_milestone"),
    "drawing": ("phase_id", "sheet_number", "title", "revision", "status"),
    "time_entry": ("phase_id", "staff_member_id", "start_utc", "end_utc", "hours", "billable",
                   "cost_cents", "billable_cents", "status", "approved_by_user_id"),
    "expense": ("project_id", "staff_member_id", "category", "amount_cents", "reimbursable",
                "markup_bp", "billable_cents", "status", "invoice_id"),
    "rfi": ("project_id", "drawing_id", "field_report_id", "rfi_number", "subject", "origin",
            "impacts_fee", "status", "clarification_rounds", "answer_text", "answered_at"),
    "submittal": ("project_id", "consultant_firm_id", "spec_section", "revision_number",
                  "status", "review_started_at", "review_due_at", "review_notes"),
    "change_order": ("contract_id", "title", "co_type", "fee_delta_cents", "source_rfi_number",
                     "status", "submitted_by_user_id", "executed_by_user_id", "executed_at"),
    "invoice": ("contract_id", "period_end", "status", "payment_status", "fee_billed_cents",
                "reimbursable_cents", "gross_cents", "retainage_bp", "retainage_cents",
                "net_due_cents", "amount_paid_cents", "issued_at"),
    "permit_review": ("phase_id", "jurisdiction_name", "permit_type", "status",
                      "submission_round", "comment_count", "decided_at"),
    # FieldReport is append-only: id + created_at only, no updated_at / version.
    "field_report": ("project_id", "staff_member_id", "visit_date", "weather", "observations",
                     "deficiency_count"),
}


def view(kind, row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if kind != "field_report":
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    for key in _FIELDS[kind]:
        value = row.get(key)
        if isinstance(value, Decimal):
            value = float(value)
        out[key] = value
    return out


def view_all(kind, rows):
    return [view(kind, r) for r in rows]


# ---------------------------------------------------------------------------
# Relationship helpers
# ---------------------------------------------------------------------------
def project_phases(project_id):
    rows = [p for p in db.phases.values() if p["project_id"] == project_id]
    rows.sort(key=lambda p: p["phase_order"])
    return rows


def phase_by_code(project_id, code):
    for p in db.phases.values():
        if p["project_id"] == project_id and p["phase_code"] == code:
            return p
    return None


def contract_of_project(project_id):
    for c in db.contracts.values():
        if c["project_id"] == project_id:
            return c
    return None


def project_of_phase(phase):
    return db.projects[phase["project_id"]]


def project_of_contract(contract):
    return db.projects[contract["project_id"]]


# ---------------------------------------------------------------------------
# Ownership scoping (PRD 2.1 / 2.7 step 6)
# ---------------------------------------------------------------------------
def scope_project(project, user_id, role):
    """Every ProjectManager write against a project is scoped to its manager."""
    if role == ROLE_PM and project["project_manager_staff_id"] != user_id:
        raise ApiError("ERR_NOT_PROJECT_MANAGER", 403,
                       "Caller is not the project manager of this project.")


def scope_staff_owner(staff_member_id, user_id, role):
    """A StaffArchitect may only act for themselves on time / expense / field report."""
    if role == ROLE_STAFF and staff_member_id != user_id:
        raise ApiError("ERR_NOT_OWNER", 403, "StaffArchitect may only act for themselves.")


def scope_client_rep(project, user_id, role):
    if role == ROLE_CLIENT and project["client_rep_user_id"] != user_id:
        raise ApiError("ERR_NOT_OWNER", 403, "Caller is not the client rep for this project.")


def scope_consultant(submittal, user_id, role):
    if role == ROLE_CONSULTANT and submittal["consultant_firm_id"] != user_id:
        raise ApiError("ERR_NOT_OWNER", 403, "Caller does not own this submittal.")


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_base_fee(contract):
    if contract["fee_basis"] == "PERCENT_OF_CONSTRUCTION":
        return round_half_up_int(
            d(contract["construction_cost_estimate_cents"]) * d(contract["fee_rate_bp"]) / d(10000)
        )
    return contract["not_to_exceed_cents"]


def compute_total_fee(contract):
    delta = sum(
        co["fee_delta_cents"]
        for co in db.change_orders.values()
        if co["contract_id"] == contract["id"] and co["status"] == "EXECUTED"
    )
    return contract["base_fee_cents"] + delta


def phase_earned(phase):
    return round_half_up_int(
        d(phase["fee_allocation_cents"]) * d(phase["percent_complete"]) / d(100)
    )


def allocate_phase_fees(contract):
    """Waterfall allocation: round every phase except the last; the last (CA) absorbs
    the remainder so the four allocations sum to total_fee_cents exactly."""
    phases = project_phases(contract["project_id"])
    if not phases:
        return
    total = contract["total_fee_cents"]
    running = 0
    for phase in phases[:-1]:
        phase["fee_allocation_cents"] = round_half_up_int(
            d(total) * d(phase["weight_bp"]) / d(10000)
        )
        running += phase["fee_allocation_cents"]
    last = phases[-1]
    last["fee_allocation_cents"] = total - running
    for phase in phases:
        phase["earned_cents"] = phase_earned(phase)
        bump(phase)


def recompute_contract_earned(contract):
    """Dual-variant earned value; wip follows immediately."""
    if contract["fee_basis"] == "PERCENT_OF_CONSTRUCTION":
        earned = 0
        for phase in project_phases(contract["project_id"]):
            earned += round_half_up_int(
                d(phase["fee_allocation_cents"]) * d(phase["percent_complete"]) / d(100)
            )
    else:
        project_id = contract["project_id"]
        raw = 0
        for entry in db.time_entries.values():
            if entry["status"] != "APPROVED":
                continue
            phase = db.phases.get(entry["phase_id"])
            if phase is None or phase["project_id"] != project_id:
                continue
            raw += entry["billable_cents"]
        earned = min(raw, contract["not_to_exceed_cents"])
    contract["earned_to_date_cents"] = earned
    contract["wip_balance_cents"] = earned - contract["billed_fee_to_date_cents"]


def recompute_wip(contract):
    contract["wip_balance_cents"] = (
        contract["earned_to_date_cents"] - contract["billed_fee_to_date_cents"]
    )


def recompute_project_labor(project):
    hours = Decimal("0")
    cost = 0
    for entry in db.time_entries.values():
        if entry["status"] != "APPROVED":
            continue
        phase = db.phases.get(entry["phase_id"])
        if phase is None or phase["project_id"] != project["id"]:
            continue
        hours += Decimal(str(entry["hours"]))
        cost += entry["cost_cents"]
    project["approved_hours"] = float(round_half_up_2(hours))
    project["labor_cost_cents"] = cost
    project["budget_posture"] = (
        "OVER_BUDGET" if cost >= project["labor_budget_cents"] else "WITHIN_BUDGET"
    )
    bump(project)


def recompute_project_rfis(project):
    count = 0
    for rfi in db.rfis.values():
        if rfi["project_id"] == project["id"] and rfi["status"] in (
            "OPEN", "RETURNED_FOR_CLARIFICATION"
        ):
            count += 1
    project["open_rfi_count"] = count
    project["ca_posture"] = "DEFICIENT" if count > 0 else "CLEAR"
    bump(project)


def submittal_review_due(start, contract):
    days = contract["submittal_review_period_days"]
    if contract["review_clock_basis"] == "CALENDAR_DAYS":
        return start + timedelta(days=days)
    cursor = start
    advanced = 0
    while advanced < days:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() not in WEEKEND:
            advanced += 1
    return cursor


def next_rfi_number(project_id):
    return sum(1 for r in db.rfis.values() if r["project_id"] == project_id) + 1


def unbilled_reimbursables(project_id):
    return [
        e for e in db.expenses.values()
        if e["project_id"] == project_id
        and e["status"] == "APPROVED"
        and e["reimbursable"] is True
        and e["invoice_id"] is None
    ]


def compute_invoice_totals(contract):
    """PRD 3.9 — the seven numbers, strictly in order."""
    project_id = contract["project_id"]

    # 1) fee portion (variant-aware)
    if contract["fee_basis"] == "PERCENT_OF_CONSTRUCTION":
        eligible = [
            p for p in project_phases(project_id)
            if p["is_billing_milestone"] and p["percent_complete"] >= BILLING_THRESHOLD_PCT
        ]
        if not eligible:
            raise ApiError("ERR_BILLING_THRESHOLD_NOT_MET", 409,
                           "No billing-milestone phase has reached 50 percent complete.")
        billable_fee_earned = sum(p["earned_cents"] for p in eligible)
    else:
        billable_fee_earned = contract["earned_to_date_cents"]

    fee_billed = billable_fee_earned - contract["billed_fee_to_date_cents"]
    if fee_billed < 0:
        fee_billed = 0

    # 2) reimbursables
    reimbursable = sum(e["billable_cents"] for e in unbilled_reimbursables(project_id))

    # 3) gross
    gross = fee_billed + reimbursable
    if gross == 0:
        raise ApiError("ERR_ZERO_INVOICE_AMOUNT", 409, "Invoice gross amount is zero.")

    # 4) cumulative fee after this invoice
    cumulative_after = contract["billed_fee_to_date_cents"] + fee_billed

    # 5) tier selection, integer floor division
    total_fee = contract["total_fee_cents"]
    if total_fee > 0:
        ratio_bp = (cumulative_after * 10000) // total_fee
    else:
        ratio_bp = 0 if cumulative_after == 0 else 10001
    if ratio_bp <= 5000:
        retainage_bp = RETAINAGE_TIER_1_BP
    elif ratio_bp <= 9000:
        retainage_bp = RETAINAGE_TIER_2_BP
    else:
        retainage_bp = RETAINAGE_TIER_3_BP

    # 6) retainage on the gross
    retainage = round_half_up_int(d(gross) * d(retainage_bp) / d(10000))

    # 7) net
    return {
        "fee_billed_cents": fee_billed,
        "reimbursable_cents": reimbursable,
        "gross_cents": gross,
        "retainage_bp": retainage_bp,
        "retainage_cents": retainage,
        "net_due_cents": gross - retainage,
    }


# ---------------------------------------------------------------------------
# State machines: declared transitions and their permitted actors
# ---------------------------------------------------------------------------
_PM_PA = (ROLE_PM, ROLE_PRINCIPAL)
_PM_SA = (ROLE_PM, ROLE_STAFF)

TRANSITIONS = {
    "project": {
        ("ACTIVE", "SUSPENDED"): (ROLE_PRINCIPAL,),
        ("SUSPENDED", "ACTIVE"): (ROLE_PRINCIPAL,),
        ("ACTIVE", "CLOSED"): (ROLE_PRINCIPAL,),
        ("SUSPENDED", "CLOSED"): (ROLE_PRINCIPAL,),
    },
    "contract": {
        ("DRAFT", "EXECUTED"): (ROLE_PRINCIPAL,),
        ("EXECUTED", "TERMINATED"): (ROLE_PRINCIPAL,),
    },
    "phase": {
        ("NOT_STARTED", "ACTIVE"): _PM_PA,
        ("ACTIVE", "ON_HOLD"): _PM_PA,
        ("ON_HOLD", "ACTIVE"): _PM_PA,
        ("ACTIVE", "COMPLETED"): _PM_PA,
    },
    "drawing": {
        ("IN_PROGRESS", "ISSUED"): _PM_SA,
        ("ISSUED", "SUPERSEDED"): _PM_SA,
        ("SUPERSEDED", "ISSUED"): _PM_SA,
    },
    "time_entry": {
        ("DRAFT", "SUBMITTED"): (ROLE_STAFF, ROLE_PM, ROLE_PRINCIPAL),
        ("SUBMITTED", "APPROVED"): _PM_PA,
        ("SUBMITTED", "REJECTED"): _PM_PA,
        ("APPROVED", "SUBMITTED"): _PM_PA,
    },
    "expense": {
        ("SUBMITTED", "APPROVED"): _PM_PA,
        ("SUBMITTED", "REJECTED"): _PM_PA,
    },
    "rfi": {
        ("OPEN", "RETURNED_FOR_CLARIFICATION"): _PM_SA,
        ("RETURNED_FOR_CLARIFICATION", "OPEN"): _PM_SA,
        ("OPEN", "ANSWERED"): _PM_SA,
        ("ANSWERED", "CLOSED"): _PM_SA,
        ("OPEN", "VOID"): _PM_SA,
    },
    "submittal": {
        ("RECEIVED", "UNDER_REVIEW"): (ROLE_PM,),
        ("UNDER_REVIEW", "APPROVED"): (ROLE_PM,),
        ("UNDER_REVIEW", "APPROVED_AS_NOTED"): (ROLE_PM,),
        ("UNDER_REVIEW", "REJECTED"): (ROLE_PM,),
        ("UNDER_REVIEW", "REVISE_AND_RESUBMIT"): (ROLE_PM,),
        ("REVISE_AND_RESUBMIT", "RECEIVED"): (ROLE_CONSULTANT,),
    },
    "change_order": {
        ("DRAFT", "SUBMITTED"): _PM_PA,
        ("SUBMITTED", "CLIENT_APPROVED"): (ROLE_CLIENT,),
        ("SUBMITTED", "CLIENT_REJECTED"): (ROLE_CLIENT,),
        ("EXECUTED", "VOID"): (ROLE_PRINCIPAL,),
    },
    "invoice": {
        ("DRAFT", "ISSUED"): _PM_PA,
        ("DRAFT", "VOID"): (ROLE_PRINCIPAL,),
        ("ISSUED", "VOID"): (ROLE_PRINCIPAL,),
    },
    "permit_review": {
        ("PREPARING", "SUBMITTED"): (ROLE_PM,),
        ("SUBMITTED", "COMMENTS_ISSUED"): (ROLE_PM,),
        ("COMMENTS_ISSUED", "RESUBMITTED"): (ROLE_PM,),
        ("RESUBMITTED", "COMMENTS_ISSUED"): (ROLE_PM,),
        ("SUBMITTED", "APPROVED"): (ROLE_PM,),
        ("RESUBMITTED", "APPROVED"): (ROLE_PM,),
        ("RESUBMITTED", "REJECTED"): (ROLE_PM,),
    },
}


def check_transition_role(kind, current, to_status, role):
    """Authorisation step for the requested transition (only when the pair is declared;
    undeclared pairs fall through to the ERR_INVALID_STATE check later on)."""
    allowed = TRANSITIONS[kind].get((current, to_status))
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role %s may not perform this transition." % role)


def require_transition(kind, current, to_status):
    if (current, to_status) not in TRANSITIONS[kind]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Transition %s -> %s is not declared." % (current, to_status))


def invalid_state(message):
    return ApiError("ERR_INVALID_STATE", 409, message)


def stamp():
    return fmt_dt(clock_now())
