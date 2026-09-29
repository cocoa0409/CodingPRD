"""Allocation cycles, volunteer panel seats and the community impact fund
(PRD 3.7, 3.8)."""

from decimal import Decimal

from flask import Blueprint

from auth import (ALL_ROLES, authenticate, get_cycle, get_panelist, get_request)
from envelope import created, filter_bool, filter_str, ok, paginate
from errors import ApiError
from store import (D, ZERO, base_entity, db, now_iso, plus_days, q2,
                   sort_created_asc, date_of, touch)
from validators import (bad, body, get_bool, get_date, get_enum, get_id, get_int,
                        get_money, iso_date_str)

from services import aggregates, calc

bp = Blueprint("cycles", __name__)

PRIORITY_AREAS = ("BASIC_NEEDS", "EDUCATION", "HEALTH", "FINANCIAL_STABILITY")
ASSIGNMENT_ROLES = ("SCORER", "CHAIR")


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #


@bp.get("/allocation-cycles/<cycle_id>")
def read_cycle(cycle_id):
    authenticate(ALL_ROLES)
    return ok(get_cycle(cycle_id))


@bp.get("/allocation-cycles/<cycle_id>/panel-assignments")
def list_cycle_assignments(cycle_id):
    authenticate(ALL_ROLES)
    get_cycle(cycle_id)
    rows = aggregates.cycle_assignments(cycle_id)
    conflict = filter_bool("conflict_declared")
    assignment_role = filter_str("assignment_role")
    if conflict is not None:
        rows = [r for r in rows if r["conflict_declared"] == conflict]
    if assignment_role is not None:
        rows = [r for r in rows if r["assignment_role"] == assignment_role]
    return paginate(sort_created_asc(rows))


@bp.get("/allocation-cycles/<cycle_id>/impact-fund-summary")
def impact_fund_summary(cycle_id):
    authenticate(ALL_ROLES)
    cycle = get_cycle(cycle_id)
    base_total = ZERO
    offset_total = ZERO
    supplement_total = ZERO
    awarded_count = 0
    for req in aggregates.cycle_requests(cycle_id):
        if req["status"] not in aggregates.AWARD_HOLDING:
            continue
        awarded_count += 1
        if req.get("base_award") is not None:
            base_total = base_total + D(req["base_award"])
        if req.get("designation_offset") is not None:
            offset_total = offset_total + D(req["designation_offset"])
        if req.get("strategic_supplement") is not None:
            supplement_total = supplement_total + D(req["strategic_supplement"])
    return ok({
        "cycle_id": cycle["id"],
        "posture": cycle["posture"],
        "opening_undesignated_pool": cycle["opening_undesignated_pool"],
        "available_undesignated_pool": cycle["available_undesignated_pool"],
        "awarded_total": cycle["awarded_total"],
        "base_award_total": q2(base_total),
        "designation_offset_total": q2(offset_total),
        "strategic_supplement_total": q2(supplement_total),
        "awarded_request_count": awarded_count,
        "suspended_request_count": cycle["suspended_request_count"],
        "suspended_request_ratio": cycle["suspended_request_ratio"],
        "awards_blocked": cycle["awards_blocked"],
    })


# --------------------------------------------------------------------------- #
# cycle lifecycle
# --------------------------------------------------------------------------- #


@bp.post("/allocation-cycles")
def create_cycle():
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    data = body()
    cycle_year = get_int(data, "cycle_year", minimum=2020, maximum=2100)
    focus = get_enum(data, "focus_priority_area", PRIORITY_AREAS)
    opening_pool = get_money(data, "opening_undesignated_pool", exclusive_min=0)
    max_award = get_money(data, "max_award_per_agency", exclusive_min=0)
    start = get_date(data, "request_window_start")
    end = get_date(data, "request_window_end")
    if not (end > start):
        bad("Field 'request_window_end' must be strictly later than 'request_window_start'.")
    for existing in db.cycles.values():
        if existing["cycle_year"] == cycle_year:
            bad("Field 'cycle_year' must be unique across all allocation cycles.")

    row = base_entity()
    row.update({
        "cycle_year": cycle_year,
        "focus_priority_area": focus,
        "opening_undesignated_pool": q2(opening_pool),
        "max_award_per_agency": q2(max_award),
        "request_window_start": iso_date_str(start),
        "request_window_end": iso_date_str(end),
        "posture": "DRAFT",
        "available_undesignated_pool": q2(opening_pool),
        "awarded_total": ZERO,
        "submitted_request_count": 0,
        "suspended_request_count": 0,
        "suspended_request_ratio": Decimal("0.0000"),
        "awards_blocked": False,
    })
    db.cycles[row["id"]] = row
    return created(row)


@bp.post("/allocation-cycles/<cycle_id>/panel-assignments")
def seat_panelist(cycle_id):
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    data = body()
    panelist_id = get_id(data, "panelist_id")
    conflict = get_bool(data, "conflict_declared", required=False, default=False)
    assignment_role = get_enum(
        data, "assignment_role", ASSIGNMENT_ROLES, required=False, default="SCORER"
    )

    cycle = get_cycle(cycle_id)
    get_panelist(panelist_id)
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN")
    if aggregates.assignment_for(cycle_id, panelist_id) is not None:
        raise ApiError("ERR_DUPLICATE_PANEL_SCORE")

    row = base_entity()
    row.update({
        "cycle_id": cycle_id,
        "panelist_id": panelist_id,
        "conflict_declared": conflict,
        "assignment_role": assignment_role,
        "submitted_score_count": 0,
    })
    db.assignments[row["id"]] = row
    return created(row)


@bp.post("/allocation-cycles/<cycle_id>/open")
def open_cycle(cycle_id):
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    body()
    cycle = get_cycle(cycle_id)
    if cycle["posture"] != "DRAFT":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    conflict_free = [
        a for a in aggregates.cycle_assignments(cycle_id) if not a["conflict_declared"]
    ]
    if not conflict_free:
        raise ApiError("ERR_PANEL_NOT_SEATED")
    cycle["posture"] = "OPEN"
    cycle["available_undesignated_pool"] = q2(cycle["opening_undesignated_pool"])
    touch("cycle", cycle)
    return ok(cycle)


@bp.post("/allocation-cycles/<cycle_id>/freeze")
def freeze_cycle(cycle_id):
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    body()
    cycle = get_cycle(cycle_id)
    # PRD 3.7 declares FROZEN only from OPEN or RESTRICTED. No error is catalogued
    # for the other two postures, so the terminal posture reports itself frozen and
    # DRAFT reports that the cycle is not open.
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN")
    if cycle["posture"] not in ("OPEN", "RESTRICTED"):
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    cycle["posture"] = "FROZEN"
    cycle["awards_blocked"] = True
    touch("cycle", cycle)
    return ok(cycle)


# --------------------------------------------------------------------------- #
# awarding the community impact fund
# --------------------------------------------------------------------------- #


@bp.post("/allocation-cycles/<cycle_id>/awards")
def issue_award(cycle_id):
    authenticate(("AllocationsDirector",))
    data = body()
    request_id = get_id(data, "request_id")
    expected_version = get_int(data, "expected_allocation_cycle_version", minimum=0)

    cycle = get_cycle(cycle_id)
    req = get_request(request_id)

    # Gate 8 precedes the posture and status gates (PRD 2.10).
    if expected_version != cycle["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN")
    if cycle["posture"] == "RESTRICTED":
        raise ApiError("ERR_CYCLE_RESTRICTED")
    if req["status"] != "PANEL_APPROVED":
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    agency = db.agencies[req["agency_id"]]
    available = D(cycle["available_undesignated_pool"])
    if available <= 0:
        raise ApiError("ERR_POOL_INSUFFICIENT")
    result = calc.award_waterfall(
        req["requested_amount"],
        cycle["max_award_per_agency"],
        req["composite_score"],
        available,
        agency["designated_passthrough_ytd"],
    )
    if result["total_award_unclamped"] > available:
        raise ApiError("ERR_POOL_INSUFFICIENT")

    req["base_award"] = result["base_award"]
    req["designation_offset"] = result["designation_offset"]
    req["strategic_supplement"] = result["strategic_supplement"]
    req["total_award"] = result["total_award"]
    req["status"] = "AWARDED"
    req["awarded_at"] = now_iso()
    req["outcome_report_due_date"] = plus_days(
        date_of(req["awarded_at"]), calc.OUTCOME_REPORT_DUE_DAYS
    ).isoformat()
    touch("request", req)

    aggregates.recompute_cycle_pool(cycle)
    aggregates.recompute_agency_delinquency(agency)
    return ok(req)
