"""Pursuit intake, conflict screening, qualification, scope narrative and baselining."""

from decimal import Decimal

from flask import Blueprint, g

from calc import (
    D,
    FOLLOW_ON_MIN_CSAT,
    PRACTICE_CODES,
    QUALIFICATION_THRESHOLD,
    has_dependency_cycle,
    line_cost_cents,
    longest_dependency_chain,
    qualification_score,
    r2,
    scope_discount_for_hours,
)
from db import clock_date, clock_stamp, db, new_row, rows, touch
from errors import fail
from middleware import (
    READ_ROLES,
    ROLE_CLIENT,
    ROLE_MANAGER,
    ROLE_PARTNER,
    client_scope,
    require_roles,
)
from response import ok
from routes.common import fetch, filtered, fk, paged
from serializers import opportunity_out
from validators import (
    filter_arg,
    get_bool,
    get_date,
    get_enum,
    get_id,
    get_int,
    get_str,
    get_str_list,
    json_body,
    present,
)

bp = Blueprint("opportunities", __name__)

TERMINAL = ("WON", "LOST", "DISQUALIFIED")
CLEARED = ("CLEAR", "CLEARED_WITH_WAIVER")


def owner_binding(opportunity):
    if g.user_id != opportunity["owner_partner_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the pursuit's owning partner may perform this operation.",
        )


def manager_binding(opportunity):
    if g.user_id != opportunity["scoping_manager_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the pursuit's scoping manager may perform this operation.",
        )


def opportunity_deliverables(opportunity_id):
    return [d for d in rows("deliverables") if d["opportunity_id"] == opportunity_id]


def score_for(opportunity, client, budget_basis):
    return qualification_score(opportunity, client, budget_basis)


def clear_baseline(opportunity):
    """Unfreeze a pursuit's scope (PRD 3.5 revision request)."""
    opportunity["total_estimated_hours"] = None
    opportunity["scope_discount_pct"] = None
    opportunity["baseline_effort_cost_cents"] = None
    opportunity["longest_dependency_chain"] = None
    opportunity["baselined_at"] = None
    for d in opportunity_deliverables(opportunity["id"]):
        if d["line_cost_cents"] is not None:
            d["line_cost_cents"] = None
            touch(d)


# ------------------------------------------------------------------ create / read / list


@bp.post("/opportunities")
def create_opportunity():
    require_roles(ROLE_PARTNER)
    body = json_body()
    client_id = get_id(body, "client_id")
    owner_id = get_id(body, "owner_partner_consultant_id")
    manager_id = get_id(body, "scoping_manager_consultant_id")
    practice_code = get_enum(body, "requested_practice_code", PRACTICE_CODES)
    estimated_value_cents = get_int(body, "estimated_value_cents", minimum=1)
    stated_budget_cents = get_int(body, "stated_budget_cents", minimum=0)
    decision_maker_identified = get_bool(body, "decision_maker_identified")
    target_start_date = get_date(body, "target_start_date")
    target_end_date = get_date(body, "target_end_date")
    objective_summary = get_str(body, "objective_summary", min_len=1, max_len=None)
    origin_engagement_id = get_id(body, "origin_engagement_id", required=False)

    if not target_end_date > target_start_date:
        fail("ERR_INVALID_DATE_RANGE", "target_end_date must be strictly after target_start_date.")

    client = fk("clients", client_id)
    fk("consultants", owner_id)
    fk("consultants", manager_id)
    origin = fk("engagements", origin_engagement_id) if origin_engagement_id else None

    if target_start_date < clock_date():
        fail("ERR_TARGET_DATE_IN_PAST", "target_start_date is earlier than the current clock date.")

    if origin is not None:
        assessment = None
        for a in rows("satisfaction_assessments"):
            if a["engagement_id"] == origin["id"]:
                assessment = a
                break
        if assessment is None or D(assessment["csat_score"]) < FOLLOW_ON_MIN_CSAT:
            fail(
                "ERR_FOLLOW_ON_NOT_ELIGIBLE",
                "The origin engagement has no satisfaction assessment at or above 7.50.",
            )

    draft = {
        "estimated_value_cents": estimated_value_cents,
        "decision_maker_identified": decision_maker_identified,
    }
    intake_score = score_for(draft, client, stated_budget_cents)

    row = new_row(
        {
            "client_id": client_id,
            "owner_partner_consultant_id": g.user_id,
            "scoping_manager_consultant_id": manager_id,
            "origin_engagement_id": origin_engagement_id,
            "requested_practice_code": practice_code,
            "estimated_value_cents": estimated_value_cents,
            "stated_budget_cents": stated_budget_cents,
            "verified_budget_cents": None,
            "decision_maker_identified": decision_maker_identified,
            "target_start_date": target_start_date.isoformat(),
            "target_end_date": target_end_date.isoformat(),
            "objective_summary": objective_summary,
            "assumptions": [],
            "exclusions": [],
            "client_responsibilities": [],
            "status": "SCREENING",
            "conflict_status": "NOT_CHECKED",
            "screened_adverse_party_codes": [],
            "qualification_score_intake": intake_score,
            "qualification_score_verified": None,
            "total_estimated_hours": None,
            "scope_discount_pct": None,
            "baseline_effort_cost_cents": None,
            "longest_dependency_chain": None,
            "baselined_at": None,
        }
    )
    db.opportunities[row["id"]] = row
    return ok(opportunity_out(row), 201)


@bp.get("/opportunities/<opportunity_id>")
def read_opportunity(opportunity_id):
    require_roles(*READ_ROLES)
    row = fetch("opportunities", opportunity_id)
    client_scope(row["client_id"])
    return ok(opportunity_out(row))


@bp.get("/opportunities")
def list_opportunities():
    require_roles(*READ_ROLES)
    client_id = filter_arg("client_id")
    owner = filter_arg("owner_partner_consultant_id")
    manager = filter_arg("scoping_manager_consultant_id")
    origin = filter_arg("origin_engagement_id")
    status = filter_arg("status")

    def keep(row):
        if client_id is not None and row["client_id"] != client_id:
            return False
        if owner is not None and row["owner_partner_consultant_id"] != owner:
            return False
        if manager is not None and row["scoping_manager_consultant_id"] != manager:
            return False
        if origin is not None and row["origin_engagement_id"] != origin:
            return False
        if status is not None and row["status"] != status:
            return False
        if g.role == ROLE_CLIENT and row["client_id"] != g.user_id:
            return False
        return True

    return paged(filtered("opportunities", keep), opportunity_out)


# ------------------------------------------------------------------ conflict screening


@bp.post("/opportunities/<opportunity_id>/conflict-check")
def conflict_check(opportunity_id):
    require_roles(ROLE_PARTNER)
    row = fetch("opportunities", opportunity_id)
    owner_binding(row)
    body = json_body()
    codes = get_str_list(body, "screened_adverse_party_codes")
    waiver = get_bool(body, "waiver_obtained", required=False, default=False)
    if row["status"] in TERMINAL:
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The pursuit has reached a terminal status.")

    client = db.clients.get(row["client_id"])
    adverse = set(client["adverse_party_codes"]) if client else set()
    overlap = adverse & set(codes)
    if len(overlap) >= 2:
        conflict_status = "BLOCKED"
    elif len(overlap) == 1:
        conflict_status = "CLEARED_WITH_WAIVER" if waiver else "WAIVER_REQUIRED"
    else:
        conflict_status = "CLEAR"

    row["screened_adverse_party_codes"] = list(codes)
    row["conflict_status"] = conflict_status
    touch(row)
    return ok(opportunity_out(row))


# ------------------------------------------------------------------ budget / qualification


@bp.post("/opportunities/<opportunity_id>/verify-budget")
def verify_budget(opportunity_id):
    require_roles(ROLE_PARTNER)
    row = fetch("opportunities", opportunity_id)
    owner_binding(row)
    body = json_body()
    verified = get_int(body, "verified_budget_cents", minimum=0)
    if row["status"] in TERMINAL:
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The pursuit has reached a terminal status.")

    client = db.clients.get(row["client_id"])
    row["verified_budget_cents"] = verified
    row["qualification_score_verified"] = score_for(row, client, verified)
    touch(row)
    return ok(opportunity_out(row))


@bp.post("/opportunities/<opportunity_id>/qualify")
def qualify(opportunity_id):
    require_roles(ROLE_PARTNER)
    row = fetch("opportunities", opportunity_id)
    owner_binding(row)
    if row["status"] != "SCREENING":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a SCREENING pursuit may be qualified.")
    if row["conflict_status"] == "BLOCKED":
        fail("ERR_CONFLICT_BLOCKED", "The pursuit's conflict position is BLOCKED.")
    if row["conflict_status"] not in CLEARED:
        fail("ERR_CONFLICT_NOT_CLEARED", "The pursuit's conflict position is not cleared.")
    if row["verified_budget_cents"] is None:
        fail("ERR_BUDGET_NOT_VERIFIED", "verified_budget_cents has not been recorded.")

    client = db.clients.get(row["client_id"])
    score = score_for(row, client, row["verified_budget_cents"])
    row["qualification_score_verified"] = score
    row["status"] = "QUALIFIED" if score >= QUALIFICATION_THRESHOLD else "DISQUALIFIED"
    touch(row)
    return ok(opportunity_out(row))


# ------------------------------------------------------------------ scope narrative


@bp.patch("/opportunities/<opportunity_id>/scope")
def patch_scope(opportunity_id):
    require_roles(ROLE_MANAGER)
    row = fetch("opportunities", opportunity_id)
    manager_binding(row)
    body = json_body()
    objective_summary = get_str(body, "objective_summary", required=False, min_len=1, max_len=None)
    assumptions = get_str_list(body, "assumptions", required=False)
    exclusions = get_str_list(body, "exclusions", required=False)
    responsibilities = get_str_list(body, "client_responsibilities", required=False)

    status = row["status"]
    if status in ("SCREENING", "DISQUALIFIED"):
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The pursuit is not open for scoping.")
    if status not in ("QUALIFIED", "SCOPING"):
        fail("ERR_SCOPE_FROZEN", "The scope has been baselined and is frozen.")

    if objective_summary is not None:
        row["objective_summary"] = objective_summary
    if assumptions is not None:
        row["assumptions"] = list(assumptions)
    if exclusions is not None:
        row["exclusions"] = list(exclusions)
    if responsibilities is not None:
        row["client_responsibilities"] = list(responsibilities)
    if status == "QUALIFIED":
        row["status"] = "SCOPING"
    touch(row)
    return ok(opportunity_out(row))


# ------------------------------------------------------------------ baselining


@bp.post("/opportunities/<opportunity_id>/baseline-scope")
def baseline_scope(opportunity_id):
    require_roles(ROLE_MANAGER)
    row = fetch("opportunities", opportunity_id)
    manager_binding(row)
    if row["status"] != "SCOPING":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a SCOPING pursuit may be baselined.")
    if row["conflict_status"] == "BLOCKED":
        fail("ERR_CONFLICT_BLOCKED", "The pursuit's conflict position is BLOCKED.")

    deliverables = opportunity_deliverables(row["id"])
    if has_dependency_cycle(deliverables):
        fail("ERR_DEPENDENCY_CYCLE", "The dependency graph contains a cycle.")
    if len(deliverables) == 0:
        fail("ERR_SCOPE_HAS_NO_DELIVERABLES", "The pursuit holds no deliverables.")
    if not row["assumptions"] or not row["exclusions"] or not row["client_responsibilities"]:
        fail(
            "ERR_ASSUMPTIONS_REQUIRED",
            "assumptions, exclusions and client_responsibilities must each hold an entry.",
        )
    for d in deliverables:
        criteria = d.get("acceptance_criteria")
        if criteria is None or not str(criteria).strip():
            fail("ERR_ACCEPTANCE_CRITERIA_MISSING", "Every deliverable needs acceptance criteria.")
    weight_sum = Decimal("0")
    for d in deliverables:
        weight_sum += D(d["completion_weight_pct"])
    if weight_sum != Decimal("100.00"):
        fail(
            "ERR_COMPLETION_WEIGHT_SUM_INVALID",
            "completion_weight_pct must sum to exactly 100.00.",
        )

    total_hours = Decimal("0")
    for d in deliverables:
        total_hours += D(d["effort_hours_estimate"])
    total_hours = r2(total_hours)
    discount = scope_discount_for_hours(total_hours)

    baseline_total = 0
    for d in deliverables:
        amount = line_cost_cents(d["effort_hours_estimate"], d["primary_grade"], discount)
        d["line_cost_cents"] = amount
        touch(d)
        baseline_total += amount

    row["total_estimated_hours"] = total_hours
    row["scope_discount_pct"] = discount
    row["baseline_effort_cost_cents"] = baseline_total
    row["longest_dependency_chain"] = longest_dependency_chain(deliverables)
    row["baselined_at"] = clock_stamp()
    row["status"] = "SCOPE_BASELINED"
    touch(row)
    return ok(opportunity_out(row))
