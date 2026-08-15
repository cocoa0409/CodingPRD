"""Reps (and ledger adjustments) + Customers."""
from flask import Blueprint, request

import db
from errors import err, not_found, invalid_request
from middleware import api, body, ALL_ROLES
from response import success_object, success_list
from services import post_entry, recompute_rep

bp = Blueprint("reps", __name__)


# ---------------------------------------------------------------------------
# Reps
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/reps", methods=["POST"])
@api(["AgencyAdmin"])
def create_rep():
    data = body()
    name = data.get("display_name")
    if not isinstance(name, str) or not name:
        raise invalid_request("display_name is required")
    codes = data.get("territory_codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise invalid_request("territory_codes must be an array of strings")
    draw = data.get("outstanding_draw_cents", 0)
    if not db.is_int(draw) or draw < 0:
        raise invalid_request("outstanding_draw_cents must be a non-negative integer")
    new_codes = set(codes)
    for other in db.reps.values():
        if other["status"] == "ACTIVE" and new_codes & set(other["territory_codes"] or []):
            raise err("ERR_TERRITORY_COVERAGE_CONFLICT",
                      "territory_codes overlap another ACTIVE rep")
    rep = {
        "display_name": name,
        "territory_codes": list(codes),
        "status": "ACTIVE",
        "commission_balance_cents": 0,
        "outstanding_draw_cents": draw,
    }
    db.stamp_new(rep)
    db.reps[rep["id"]] = rep
    return success_object(rep, 201)


@bp.route("/rep-agency/reps", methods=["GET"])
@api(ALL_ROLES)
def list_reps():
    items = list(db.reps.values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return success_list(items)


@bp.route("/rep-agency/reps/<rid>", methods=["GET"])
@api(ALL_ROLES)
def get_rep(rid):
    rep = db.reps.get(rid)
    if rep is None:
        raise not_found("Rep")
    return success_object(rep)


@bp.route("/rep-agency/reps/<rid>/adjustments", methods=["POST"])
@api(["AgencyAdmin"])
def post_adjustment(rid):
    rep = db.reps.get(rid)
    if rep is None:
        raise not_found("Rep")
    data = body()
    amount = data.get("amount_cents")
    if not db.is_int(amount) or amount == 0:
        raise invalid_request("amount_cents must be a non-zero integer")
    note = data.get("note")
    if not isinstance(note, str):
        raise invalid_request("note is required")
    principal_id = data.get("principal_id")
    if principal_id is not None:
        if not isinstance(principal_id, str) or principal_id not in db.principals:
            raise not_found("Principal")
    entry = post_entry(rep_id=rep["id"], principal_id=principal_id,
                       order_id=None, statement_id=None, etype="ADJUSTMENT",
                       amount_cents=amount, note=note)
    recompute_rep(rep["id"])
    return success_object(entry, 201)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/customers", methods=["POST"])
@api(["AgencyAdmin"])
def create_customer():
    data = body()
    name = data.get("name")
    spec = data.get("spec_territory_code")
    ship = data.get("ship_to_territory_code")
    if not isinstance(name, str) or not name:
        raise invalid_request("name is required")
    if not isinstance(spec, str) or not spec:
        raise invalid_request("spec_territory_code is required")
    if not isinstance(ship, str) or not ship:
        raise invalid_request("ship_to_territory_code is required")
    cust = {"name": name, "spec_territory_code": spec, "ship_to_territory_code": ship}
    db.stamp_new(cust)
    db.customers[cust["id"]] = cust
    return success_object(cust, 201)


@bp.route("/rep-agency/customers", methods=["GET"])
@api(ALL_ROLES)
def list_customers():
    return success_list(list(db.customers.values()))


@bp.route("/rep-agency/customers/<cid>", methods=["GET"])
@api(ALL_ROLES)
def get_customer(cid):
    cust = db.customers.get(cid)
    if cust is None:
        raise not_found("Customer")
    return success_object(cust)
