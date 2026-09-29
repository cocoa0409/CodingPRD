"""Production files, the twin state axes and the two reports (PRD 3.1, 3.5)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from db import ZERO4
from errors import fail
from middleware import (ALL_ROLES, COMPTROLLER, GENERAL_MANAGER, INVESTOR,
                        LEAD_PRODUCER, MANAGEMENT_ROLES, SYNDICATION_COUNSEL,
                        ctx, endpoint, find_production, find_theatre)
from services import ledger
from services import queries as q

bp = Blueprint("productions", __name__)

OFFERING_STATUSES = ("DRAFT", "OFFERING", "FULLY_SUBSCRIBED", "CAPITALIZED")
OPERATING_STATUSES = ("PRE_PRODUCTION", "REHEARSAL", "PREVIEWS", "RUNNING",
                      "CLOSING_NOTICE", "CLOSED")
RECOUPMENT_STATUSES = ("UNRECOUPED", "RECOUPED")

# PRD 3.5: one step at a time, and only these three advances exist.
OPERATING_ADVANCES = {
    "PRE_PRODUCTION": "REHEARSAL",
    "REHEARSAL": "PREVIEWS",
    "PREVIEWS": "RUNNING",
}


@bp.post("/productions")
@endpoint((GENERAL_MANAGER,))
def create_production():
    data = v.body()
    title = v.req_str(data, "title", 1, 200)
    entity_type = v.req_enum(data, "offering_entity_type", ("LP", "LLC"))
    target = v.req_int(data, "capitalization_target_cents", 1)
    reserve_target = v.req_int(data, "reserve_target_cents", 0)
    theatre_id = v.req_id(data, "theatre_id")
    pre_pct = v.opt_pct(data, "pre_recoupment_pool_pct", "0.3500")
    post_pct = v.opt_pct(data, "post_recoupment_pool_pct", "0.4000")
    sub_pct = v.opt_pct(data, "subsidiary_rights_investor_share_pct", "0.4000",
                        max_inclusive=True)
    notice_days = v.opt_int(data, "closing_notice_min_days", 14, 0)

    find_theatre(theatre_id)

    row = db.insert("productions", {
        "title": title,
        "offering_entity_type": entity_type,
        "capitalization_target_cents": target,
        "reserve_target_cents": reserve_target,
        "theatre_id": theatre_id,
        "pre_recoupment_pool_pct": pre_pct,
        "post_recoupment_pool_pct": post_pct,
        "subsidiary_rights_investor_share_pct": sub_pct,
        "closing_notice_min_days": notice_days,
        "royalty_basis": "FIXED_GROSS",
        "offering_status": "DRAFT",
        "operating_status": "PRE_PRODUCTION",
        "recoupment_status": "UNRECOUPED",
        "budget_status": "DRAFT",
        "budget_total_cents": 0,
        "budget_committed_cents": 0,
        "capital_raised_cents": 0,
        "released_capital_cents": 0,
        "escrow_balance_cents": 0,
        "recouped_amount_cents": 0,
        "recoupment_pct": ZERO4,
        "deferred_royalty_cents": 0,
        "distributed_total_cents": 0,
        "distributable_cash_cents": 0,
        "total_pool_points": 0,
        "active_investor_count": 0,
    })
    return response.obj(row, 201)


@bp.get("/productions/<production_id>")
@endpoint(ALL_ROLES)
def read_production(production_id):
    return response.obj(find_production(production_id))


@bp.get("/productions")
@endpoint(ALL_ROLES)
def list_productions():
    theatre_id = v.q_str("theatre_id")
    offering_status = v.q_enum("offering_status", OFFERING_STATUSES)
    operating_status = v.q_enum("operating_status", OPERATING_STATUSES)
    recoupment_status = v.q_enum("recoupment_status", RECOUPMENT_STATUSES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("productions")
            if (theatre_id is None or r["theatre_id"] == theatre_id)
            and (offering_status is None or r["offering_status"] == offering_status)
            and (operating_status is None or r["operating_status"] == operating_status)
            and (recoupment_status is None
                 or r["recoupment_status"] == recoupment_status)]
    return response.listing(rows, limit, offset)


@bp.post("/productions/<production_id>/open-offering")
@endpoint((SYNDICATION_COUNSEL,))
def open_offering(production_id):
    production = find_production(production_id)
    if production["offering_status"] != "DRAFT":
        fail(errors.ERR_INVALID_OFFERING_STATE,
             "The offering axis must read DRAFT to open the offering.")
    ctx().force(production)
    production["offering_status"] = "OFFERING"
    return response.obj(production)


@bp.post("/productions/<production_id>/capitalize")
@endpoint((COMPTROLLER,))
def capitalize(production_id):
    production = find_production(production_id)
    if production["offering_status"] != "FULLY_SUBSCRIBED":
        fail(errors.ERR_INVALID_OFFERING_STATE,
             "Escrow may only be released from FULLY_SUBSCRIBED.")
    ctx().force(production)
    production["released_capital_cents"] = production["capital_raised_cents"]
    production["escrow_balance_cents"] = 0
    production["offering_status"] = "CAPITALIZED"
    return response.obj(production)


@bp.post("/productions/<production_id>/operating-status")
@endpoint((LEAD_PRODUCER,))
def advance_operating_status(production_id):
    production = find_production(production_id)
    data = v.body()
    to_status = v.req_enum(data, "to_status", OPERATING_STATUSES)

    current = production["operating_status"]
    if OPERATING_ADVANCES.get(current) != to_status:
        fail(errors.ERR_INVALID_OPERATING_STATE,
             "The operating axis cannot move from %s to %s." % (current, to_status))
    if current == "PRE_PRODUCTION" and production["offering_status"] != "CAPITALIZED":
        fail(errors.ERR_PRODUCTION_NOT_CAPITALIZED,
             "The offering axis must read CAPITALIZED first.")
    if to_status == "PREVIEWS" and len(
            q.active_operating_budgets(production_id)) != 1:
        fail(errors.ERR_ACTIVE_OPERATING_BUDGET_MISSING,
             "Exactly one ACTIVE operating budget is required.")

    ctx().force(production)
    production["operating_status"] = to_status
    return response.obj(production)


@bp.post("/productions/<production_id>/convert-royalties-to-pool")
@endpoint((LEAD_PRODUCER,))
def convert_royalties_to_pool(production_id):
    production = find_production(production_id)
    if production["royalty_basis"] == "POOL":
        fail(errors.ERR_ROYALTY_BASIS_ALREADY_POOL,
             "The royalty basis has already been converted to POOL.")
    ctx().force(production)
    production["royalty_basis"] = "POOL"
    ledger.royalty_pool_share_pct(ctx(), production)
    return response.obj(production)


@bp.post("/productions/<production_id>/approve-budget")
@endpoint((LEAD_PRODUCER,))
def approve_budget(production_id):
    production = find_production(production_id)
    ctx().force(production)
    production["budget_status"] = "APPROVED"
    ledger.capitalization_budget_rollup(ctx(), production)
    return response.obj(production)


@bp.get("/productions/<production_id>/break-even-analysis")
@endpoint(MANAGEMENT_ROLES)
def break_even_analysis(production_id):
    production = find_production(production_id)
    active = q.active_operating_budgets(production_id)
    if len(active) != 1:
        fail(errors.ERR_ACTIVE_OPERATING_BUDGET_MISSING,
             "Exactly one ACTIVE operating budget is required.")
    theatre = db.get("theatres", production["theatre_id"])
    return response.raw_obj(
        ledger.break_even_analysis(production, active[0], theatre))


@bp.get("/productions/<production_id>/recoupment-report")
@endpoint((GENERAL_MANAGER, COMPTROLLER, LEAD_PRODUCER, INVESTOR))
def recoupment_report(production_id):
    production = find_production(production_id)
    return response.raw_obj(ledger.recoupment_report(production))
