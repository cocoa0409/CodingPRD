"""Defendant + BailOrder endpoints."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (paginate, require_enum, require_fields, require_int,
                     require_str, require_bool)
from lookup import get_defendant, get_bail_order
from middleware import (authenticate, get_json_body, parse_pagination,
                        require_role)
from response import array_response, object_response
from views import view, view_list

bp = Blueprint("defendants", __name__)

RISK_TIERS = {"LOW", "MEDIUM", "HIGH"}
BOND_TYPE_ALLOWED = {"CASH", "SURETY", "PR", "ANY"}
CONDITION_CODES = {"GPS", "CURFEW", "DRUG_TEST", "NO_CONTACT"}


@bp.route("/defendants", methods=["POST"])
def create_defendant():
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court"})
    body = get_json_body()
    require_fields(body, ["full_name", "date_of_birth", "phone_e164"])
    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    phone = require_str(body, "phone_e164")
    risk_tier = require_enum(body, "risk_tier", RISK_TIERS, required=False, default="MEDIUM")

    rec = db.make_record({
        "full_name": full_name,
        "date_of_birth": dob,
        "phone_e164": phone,
        "risk_tier": risk_tier,
        "total_active_exposure_cents": 0,
        "status": "ACTIVE",
    })
    db.defendants[rec["id"]] = rec
    return object_response(view(rec), 201)


@bp.route("/defendants/<defendant_id>", methods=["GET"])
def fetch_defendant(defendant_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    d = get_defendant(defendant_id)
    return object_response(view(d), 200)


@bp.route("/defendants", methods=["GET"])
def list_defendants():
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    limit, offset = parse_pagination()
    records = list(db.defendants.values())
    risk_filter = request.args.get("risk_tier")
    if risk_filter is not None:
        records = [r for r in records if r["risk_tier"] == risk_filter]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/defendants/<defendant_id>/bail-orders", methods=["POST"])
def create_bail_order(defendant_id):
    _, role = authenticate()
    require_role(role, {"Court"})
    get_defendant(defendant_id)
    body = get_json_body()
    require_fields(body, ["case_number", "bail_amount_cents", "bond_type_allowed"])
    case_number = require_str(body, "case_number")
    bail_amount = require_int(body, "bail_amount_cents", gt=0)
    bond_type_allowed = require_enum(body, "bond_type_allowed", BOND_TYPE_ALLOWED)
    condition_codes = body.get("condition_codes", [])
    if condition_codes is None:
        condition_codes = []
    if not isinstance(condition_codes, list) or \
            any(not isinstance(c, str) or c not in CONDITION_CODES for c in condition_codes):
        raise err("ERR_INVALID_REQUEST", "condition_codes must be an array of valid codes.")
    gps_required = require_bool(body, "gps_required", required=False, default=False)

    # case_number unique within (defendant_id)
    for o in db.bail_orders.values():
        if o["defendant_id"] == defendant_id and o["case_number"] == case_number:
            raise err("ERR_DUPLICATE_CASE_NUMBER", "case_number already exists for defendant.")

    rec = db.make_record({
        "defendant_id": defendant_id,
        "case_number": case_number,
        "bail_amount_cents": bail_amount,
        "bond_type_allowed": bond_type_allowed,
        "condition_codes": condition_codes,
        "gps_required": gps_required,
        "status": "OPEN",
    })
    db.bail_orders[rec["id"]] = rec
    return object_response(view(rec), 201)


@bp.route("/defendants/<defendant_id>/bail-orders", methods=["GET"])
def list_bail_orders(defendant_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    get_defendant(defendant_id)
    limit, offset = parse_pagination()
    records = [o for o in db.bail_orders.values() if o["defendant_id"] == defendant_id]
    page, total = paginate(records, limit, offset)
    return array_response(view_list(page), limit, offset, total, 200)


@bp.route("/bail-orders/<order_id>", methods=["GET"])
def fetch_bail_order(order_id):
    _, role = authenticate()
    require_role(role, {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent"})
    o = get_bail_order(order_id)
    return object_response(view(o), 200)
