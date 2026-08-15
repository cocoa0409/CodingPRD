"""AssetStatement and AssetValuation endpoints."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination, list_page
from errors import (
    plan_terminated, validation, not_found, ApiError,
    ERR_PLAN_YEAR_MISMATCH, ERR_UNIQUENESS_VIOLATION,
)
from validate import body_of, req_int, req_num
from services.core import (
    base_record, public, get_plan, get_asset_valuation, r2,
    compute_asset_valuation_fields,
)

bp = Blueprint("assets", __name__)

READ_ROLES = ["PlanAdmin", "Actuary", "SeniorActuary", "Auditor"]
ACTUARY_ROLES = ["Actuary", "SeniorActuary"]


def _plan_active_gate(plan):
    if plan["status"] != "ACTIVE":
        raise plan_terminated()


def _check_plan_year(body, plan):
    py = body.get("plan_year")
    if isinstance(py, int) and not isinstance(py, bool) and py != plan["plan_year"]:
        raise ApiError(ERR_PLAN_YEAR_MISMATCH, 422, "plan_year differs from the plan's plan_year")


# ---------------------------------------------------------------------------
# AssetStatement
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/asset-statements", methods=["POST"])
def create_asset_statement(plan_id):
    require_roles(["PlanAdmin"])
    plan = get_plan(plan_id)
    _plan_active_gate(plan)
    body = body_of(request)
    _check_plan_year(body, plan)
    plan_year = req_int(body, "plan_year")

    # priority 17: unique per (plan, plan_year)
    for s in store.asset_statements.values():
        if s["plan_id"] == plan["id"] and s["plan_year"] == plan_year:
            raise ApiError(ERR_UNIQUENESS_VIOLATION, 409, "An asset statement already exists for this plan_year")

    market_value_begin = req_num(body, "market_value_begin")
    contributions_received = req_num(body, "contributions_received")
    benefits_paid = req_num(body, "benefits_paid")
    investment_return = req_num(body, "investment_return")
    if market_value_begin < 0:
        raise validation("market_value_begin must be >= 0")
    if contributions_received < 0:
        raise validation("contributions_received must be >= 0")
    if benefits_paid < 0:
        raise validation("benefits_paid must be >= 0")

    # roll-forward invariant
    market_value_end = r2(
        Decimal(str(market_value_begin))
        + Decimal(str(contributions_received))
        - Decimal(str(benefits_paid))
        + Decimal(str(investment_return))
    )

    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "plan_year": plan_year,
        "market_value_begin": r2(market_value_begin),
        "contributions_received": r2(contributions_received),
        "benefits_paid": r2(benefits_paid),
        "investment_return": r2(investment_return),
        "market_value_end": market_value_end,
        "status": "FINAL",
    })
    store.asset_statements[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/asset-statements", methods=["GET"])
def list_asset_statements(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.asset_statements.values() if s["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# AssetValuation
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/asset-valuations", methods=["POST"])
def create_asset_valuation(plan_id):
    require_roles(ACTUARY_ROLES)
    plan = get_plan(plan_id)
    _plan_active_gate(plan)
    body = body_of(request)
    _check_plan_year(body, plan)
    plan_year = req_int(body, "plan_year")

    # input set: the plan's AssetStatement for the same plan_year (exactly one permitted)
    stmt = None
    for s in store.asset_statements.values():
        if s["plan_id"] == plan["id"] and s["plan_year"] == plan_year:
            stmt = s
            break
    if stmt is None:
        raise not_found("No AssetStatement exists for this plan and plan_year")

    fields = compute_asset_valuation_fields(stmt)
    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "plan_year": plan_year,
        "asset_statement_id": stmt["id"],
        "status": "FINAL",
    })
    rec.update(fields)
    store.asset_valuations[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/asset-valuations", methods=["GET"])
def list_asset_valuations(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [a for a in store.asset_valuations.values() if a["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/v1/asset-valuations/<valuation_id>", methods=["GET"])
def fetch_asset_valuation(valuation_id):
    require_roles(READ_ROLES)
    rec = get_asset_valuation(valuation_id)
    return success_object(public(rec))
