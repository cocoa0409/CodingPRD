"""Bond endpoints: post, fetch, list, activate, exonerate, revoke."""
from flask import Blueprint, request

import db
from errors import err
from helpers import paginate, require_enum, require_int
from lookup import (get_bail_order, get_bond, get_bond_for_defendant,
                    get_defendant)
from middleware import (authenticate, get_json_body, parse_pagination,
                        require_role)
from response import array_response, object_response
from services import calculations as calc
from services import domain
from views import view, view_list

bp = Blueprint("bonds", __name__)

BOND_TYPES = {"CASH", "SURETY", "PR"}


@bp.route("/defendants/<defendant_id>/bail-orders/<order_id>/bonds", methods=["POST"])
def post_bond(defendant_id, order_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    get_defendant(defendant_id)
    order = db.bail_orders.get(order_id)
    if order is None or order["defendant_id"] != defendant_id:
        raise err("ERR_NOT_FOUND", "Bail order not found for this defendant.")

    body = get_json_body()
    bond_type = require_enum(body, "bond_type", BOND_TYPES)
    premium_rate_bps = require_int(body, "premium_rate_bps", required=False, default=1000,
                                   min_value=0, max_value=1500)

    # Bond type must be permitted by the order (priority 10).
    allowed = order["bond_type_allowed"]
    if allowed != "ANY" and allowed != bond_type:
        raise err("ERR_BOND_TYPE_NOT_ALLOWED", "Bond type not permitted by order.")

    defendant = db.defendants[defendant_id]
    bail_amount = order["bail_amount_cents"]
    required_collateral = calc.required_collateral(bond_type, bail_amount,
                                                   defendant["risk_tier"])

    rec = db.make_record({
        "bail_order_id": order_id,
        "defendant_id": defendant_id,
        "bond_type": bond_type,
        "bail_amount_cents": bail_amount,
        "premium_rate_bps": premium_rate_bps,
        "premium_cents": 0,
        "premium_earned_cents": 0,
        "required_collateral_cents": required_collateral,
        "collateral_held_cents": 0,
        "coverage_status": "DRAFT",
        "settlement_status": "UNSETTLED",
        "posted_at": None,
        "activated_by_user_id": None,
    })
    db.bonds[rec["id"]] = rec
    return object_response(view(rec), 201)


@bp.route("/bonds/<bond_id>", methods=["GET"])
def fetch_bond(bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    b = get_bond(bond_id)
    return object_response(view(b), 200)


@bp.route("/bail-orders/<order_id>/bonds", methods=["GET"])
def list_order_bonds(order_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    get_bail_order(order_id)
    limit, offset = parse_pagination()
    records = [b for b in db.bonds.values() if b["bail_order_id"] == order_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/bonds", methods=["GET"])
def list_bonds():
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    limit, offset = parse_pagination()
    records = list(db.bonds.values())
    defendant_id = request.args.get("defendant_id")
    if defendant_id is not None:
        records = [b for b in records if b["defendant_id"] == defendant_id]
    coverage_status = request.args.get("coverage_status")
    if coverage_status is not None:
        records = [b for b in records if b["coverage_status"] == coverage_status]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/defendants/<defendant_id>/bonds/<bond_id>/activate", methods=["POST"])
def activate(defendant_id, bond_id):
    user_id, role = authenticate()
    require_role(role, {"BondsAgent"})
    bond = get_bond_for_defendant(defendant_id, bond_id)
    defendant = db.defendants[defendant_id]
    domain.activate_bond(defendant, bond, user_id)
    return object_response(view(bond), 200)


@bp.route("/defendants/<defendant_id>/bonds/<bond_id>/exonerate", methods=["POST"])
def exonerate(defendant_id, bond_id):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    bond = get_bond_for_defendant(defendant_id, bond_id)
    defendant = db.defendants[defendant_id]
    domain.exonerate_bond(defendant, bond, user_id)
    return object_response(view(bond), 200)


@bp.route("/defendants/<defendant_id>/bonds/<bond_id>/revoke", methods=["POST"])
def revoke(defendant_id, bond_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent"})
    bond = get_bond_for_defendant(defendant_id, bond_id)
    defendant = db.defendants[defendant_id]
    domain.revoke_bond(defendant, bond)
    return object_response(view(bond), 200)
