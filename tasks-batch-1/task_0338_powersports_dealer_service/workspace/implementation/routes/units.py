"""Units (PRD 3.1) and floor-plan loans / curtailments (PRD 3.1, 3.2)."""

import re

from flask import Blueprint, request

import errors
import calculations as calc
from common import (
    get_body, stamp_new, serialize, touch, paginate,
    as_int, as_str, as_enum,
)
from db import db
from lookups import get_unit
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("units", __name__)

UNIT_CATEGORIES = {"MOTORCYCLE", "ATV", "UTV", "PWC", "SNOWMOBILE"}
ACQUISITION_KINDS = {"NEW_FLOORED", "TRADE_IN", "CASH_OWNED"}
VIN_RE = re.compile(r"^[A-Z0-9]{17}$")


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@bp.route("/units", methods=["POST"])
def create_unit():
    _, role = get_user_context()
    require_role(role, {"SalesManager", "DealerPrincipal"})
    body = get_body()
    vin = as_str(body, "vin")
    category = as_enum(body, "category", UNIT_CATEGORIES)
    model_year = as_int(body, "model_year")
    msrp = as_int(body, "msrp_cents", minimum=0)
    dealer_cost = as_int(body, "dealer_cost_cents", minimum=0)
    acquisition_kind = as_enum(body, "acquisition_kind", ACQUISITION_KINDS, required=False, default="NEW_FLOORED")

    # VIN must be exactly 17 chars uppercase alphanumeric (malformed -> 422)
    if not VIN_RE.match(vin):
        errors.err(errors.ERR_INVALID_REQUEST, "VIN must be 17 uppercase alphanumeric characters")
    if model_year < 2000:
        errors.err(errors.ERR_INVALID_REQUEST, "model_year must be >= 2000")

    # uniqueness: VIN unique across all units (409)
    for u in db.units.values():
        if u["vin"] == vin:
            errors.err(errors.ERR_DUPLICATE_RESOURCE, "VIN already exists")

    rec = stamp_new({
        "vin": vin,
        "category": category,
        "model_year": model_year,
        "msrp_cents": msrp,
        "dealer_cost_cents": dealer_cost,
        "acquisition_kind": acquisition_kind,
        "status": "IN_TRANSIT",
        "floor_plan_loan_id": None,
        "held_by_deal_id": None,
    })
    db.units[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/units", methods=["GET"])
def list_units():
    _, role = get_user_context()
    require_role(role, {"SalesManager", "ServiceAdvisor", "FinanceManager", "PartsClerk", "DealerPrincipal"})
    status = request.args.get("status")
    vin = request.args.get("vin")
    fpl = request.args.get("floor_plan_loan_id")
    held = request.args.get("held_by_deal_id")
    records = []
    for u in db.units.values():
        if status is not None and u["status"] != status:
            continue
        if vin is not None and u["vin"] != vin:
            continue
        if fpl is not None and u.get("floor_plan_loan_id") != fpl:
            continue
        if held is not None and u.get("held_by_deal_id") != held:
            continue
        records.append(u)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/units/<uid>", methods=["GET"])
def get_unit_route(uid):
    _, role = get_user_context()
    require_role(role, {"SalesManager", "ServiceAdvisor", "FinanceManager", "PartsClerk", "DealerPrincipal"})
    rec = get_unit(uid)
    return ok(serialize(rec), 200)


@bp.route("/units/<uid>/receive", methods=["POST"])
def receive_unit(uid):
    _, role = get_user_context()
    require_role(role, {"SalesManager", "DealerPrincipal"})
    unit = get_unit(uid)
    if unit["status"] != "IN_TRANSIT":
        errors.err(errors.ERR_INVALID_STATE, "Unit is not IN_TRANSIT")
    unit["status"] = "IN_STOCK"
    touch(unit)
    return ok(serialize(unit), 200)


# ---------------------------------------------------------------------------
# Floor-plan loans
# ---------------------------------------------------------------------------
def _loan_view(loan, basis="SIMPLE"):
    view = serialize(loan)
    view["accrued_interest_cents"] = calc.accrued_interest(loan, basis)
    return view


@bp.route("/floor-plan-loans", methods=["POST"])
def create_loan():
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal"})
    body = get_body()
    unit_id = as_str(body, "unit_id")
    opened_on = as_str(body, "opened_on")
    apr_bps = as_int(body, "apr_bps", minimum=0)

    from db import parse_iso
    if parse_iso(opened_on) is None:
        errors.err(errors.ERR_INVALID_REQUEST, "opened_on must be a valid ISO 8601 timestamp")

    unit = get_unit(unit_id)

    rec = stamp_new({
        "unit_id": unit_id,
        "original_advance_cents": unit["dealer_cost_cents"],
        "principal_outstanding_cents": unit["dealer_cost_cents"],
        "cumulative_curtailment_cents": 0,
        "accrued_interest_cents": 0,
        "opened_on": opened_on,
        "apr_bps": apr_bps,
        "status": "OPEN",
    })
    db.floor_plan_loans[rec["id"]] = rec
    # write loan id back onto the unit
    unit["floor_plan_loan_id"] = rec["id"]
    touch(unit)
    return ok(_loan_view(rec), 201)


@bp.route("/floor-plan-loans", methods=["GET"])
def list_loans():
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal", "FinanceManager", "SalesManager"})
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")
    records = []
    for l in db.floor_plan_loans.values():
        if unit_id is not None and l["unit_id"] != unit_id:
            continue
        if status is not None and l["status"] != status:
            continue
        records.append(l)
    from common import parse_pagination, serialize as _ser
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    items = [_loan_view(l) for l in page]
    return ok_list(items, limit, offset, total)


@bp.route("/floor-plan-loans/<lid>", methods=["GET"])
def get_loan_route(lid):
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal", "FinanceManager", "SalesManager"})
    from lookups import get_loan
    loan = get_loan(lid)
    basis = request.args.get("interest_basis", "SIMPLE")
    if basis not in ("SIMPLE", "DECLINING"):
        basis = "SIMPLE"
    return ok(_loan_view(loan, basis), 200)


@bp.route("/floor-plan-loans/<lid>/run-aging", methods=["POST"])
def run_aging(lid):
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal"})
    from lookups import get_loan
    loan = get_loan(lid)
    # recompute simple accrued interest presentation
    loan["accrued_interest_cents"] = calc.simple_interest(loan)
    if loan["status"] == "OPEN":
        days = calc.elapsed_days(loan["opened_on"])
        if days >= calc.CURTAILMENT_DUE_DAYS:
            loan["status"] = "CURTAILMENT_DUE"
    touch(loan)
    return ok(_loan_view(loan), 200)
