"""Associations, their reverse-lookup lists and the repose sweep."""
from flask import Blueprint

import auth
import calc
import clock
import constants
import response
import util
import validation as v
from db import db, new_record, serialize, serialize_list, touch
from routes import common

bp = Blueprint("associations", __name__)


# ------------------------------------------------------------------ create ---
@bp.post("/hoa/associations")
def create_association():
    auth.require_roles(constants.ROLE_PLATFORM_ADMIN)
    body = v.body()

    name = v.get_str(body, "name", min_len=1, max_len=120)
    total_planned_lots = v.get_int(body, "total_planned_lots", minimum=1)
    threshold = v.get_number(
        body, "turnover_threshold_pct", minimum="0.01", maximum="100.00"
    )
    fixed_turnover_date, _ = v.get_datetime(body, "fixed_turnover_date")
    statute_years = v.get_int(body, "statute_of_repose_years", minimum=1, maximum=15)
    reserve_pool = v.get_int(body, "reserve_pool_cents", minimum=0)
    reserve_claim_pool = v.get_int(body, "reserve_claim_pool_cents", minimum=0)
    monthly_subsidy = v.get_int(body, "declarant_monthly_subsidy_cents", minimum=0)

    association = new_record({
        "name": name,
        "total_planned_lots": total_planned_lots,
        "turnover_threshold_pct": float(util.round_half_up(threshold, 2)),
        "fixed_turnover_date": fixed_turnover_date,
        "statute_of_repose_years": statute_years,
        "reserve_pool_cents": reserve_pool,
        "reserve_claim_pool_cents": reserve_claim_pool,
        "declarant_monthly_subsidy_cents": monthly_subsidy,
        "sold_lot_count": 0,
        "sold_lot_pct": 0.00,
        "subsidy_receivable_cents": 0,
        "reserve_claim_committed_cents": 0,
        "reserve_claim_available_cents": reserve_claim_pool,
        "subsidy_end_date": None,
        "budget_forecast_status": "CURRENT",
    })
    db.associations[association["id"]] = association
    return response.object_response(serialize(association), 201)


# -------------------------------------------------------------------- read ---
@bp.get("/hoa/associations/<association_id>")
def read_association(association_id):
    auth.require_roles(*constants.ALL_ROLES)
    association = common.association_or_404(association_id, scoped=True)
    return response.object_response(serialize(association))


# ------------------------------------------------------- reverse lookups ---
@bp.get("/hoa/associations/<association_id>/lots")
def list_lots(association_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.association_or_404(association_id, scoped=True)
    records = calc.lots_of(association_id)
    sale_status = v.query_filter("sale_status")
    if sale_status is not None:
        records = [r for r in records if r["sale_status"] == sale_status]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.get("/hoa/associations/<association_id>/components")
def list_components(association_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.association_or_404(association_id, scoped=True)
    records = calc.components_of(association_id)
    for field in ("build_status", "conveyance_status", "category"):
        value = v.query_filter(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.get("/hoa/associations/<association_id>/turnover-cases")
def list_turnover_cases(association_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.association_or_404(association_id, scoped=True)
    case = calc.case_for_association(association_id)
    records = [case] if case is not None else []
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.get("/hoa/associations/<association_id>/reserve-studies")
def list_reserve_studies(association_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.association_or_404(association_id, scoped=True)
    records = calc.studies_of(association_id)
    status = v.query_filter("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.get("/hoa/associations/<association_id>/audit-engagements")
def list_audit_engagements(association_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.association_or_404(association_id, scoped=True)
    records = calc.engagements_of(association_id)
    status = v.query_filter("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.get("/hoa/associations/<association_id>/assessment-schedules")
def list_assessment_schedules(association_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.association_or_404(association_id, scoped=True)
    records = calc.schedules_of(association_id)
    status = v.query_filter("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    fiscal_year = v.query_int("fiscal_year")
    if fiscal_year is not None:
        records = [r for r in records if r["fiscal_year"] == fiscal_year]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


# ------------------------------------------------------------ repose sweep ---
@bp.post("/hoa/associations/<association_id>/repose-sweep")
def repose_sweep(association_id):
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    common.association_or_404(association_id, scoped=True)

    now = clock.now()
    swept = []
    for claim in calc.claims_of(association_id):
        if claim["status"] != "INVESTIGATING":
            continue
        deadline = util.parse_dt(claim["repose_deadline"]) if claim["repose_deadline"] else None
        if deadline is None or not now > deadline:
            continue
        claim["status"] = "TIME_BARRED"
        touch(claim)
        swept.append(claim["id"])

    return response.object_response({
        "swept_claim_count": len(swept),
        "time_barred_claim_ids": swept,
    })
