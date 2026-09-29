"""Carriers, bonds and ports: registering the participants (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db, new_record, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import ok, ok_list, read_pagination, window
from services import calc, domain
import validate as v

bp = Blueprint("registry", __name__)

REGION_CODES = ("NE", "MW", "SE", "PSW", "NW")
CUSTODIAL_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED")
BOND_TYPES = ("SINGLE_TRANSACTION", "CONTINUOUS")
BOND_STATUSES = ("ACTIVE", "SATURATED", "SUSPENDED", "EXPIRED")


# --------------------------------------------------------------------------
# BondedCarrier
# --------------------------------------------------------------------------
@bp.route("/in-bond/carriers", methods=["POST"])
def create_carrier():
    require("CBPOfficer")
    body = v.get_body()
    name = v.req_str(body, "name", max_len=120)
    irs_number = v.req_str(body, "irs_number")

    for existing in db.carriers.values():
        if existing["irs_number"] == irs_number:
            raise ApiError("ERR_DUPLICATE_IRS_NUMBER")

    rec = new_record()
    rec.update({
        "name": name,
        "irs_number": irs_number,
        "custodial_status": "ACTIVE",
        "sanction_points": Decimal("0.0"),
        "suspension_reason": None,
    })
    db.carriers[rec["id"]] = rec
    return ok(domain.carrier_json(rec), 201)


@bp.route("/in-bond/carriers/<carrier_id>", methods=["GET"])
def read_carrier(carrier_id):
    require(*ALL_ROLES)
    rec = db.carriers.get(carrier_id)
    if rec is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    return ok(domain.carrier_json(rec))


@bp.route("/in-bond/carriers/<carrier_id>", methods=["PATCH"])
def patch_carrier(carrier_id):
    require("CBPOfficer")
    body = v.get_body()
    target = v.req_enum(body, "custodial_status", CUSTODIAL_STATUSES)
    v.opt_str(body, "reason_code")

    rec = db.carriers.get(carrier_id)
    if rec is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")

    current = rec["custodial_status"]
    allowed = {("ACTIVE", "REVOKED"), ("SUSPENDED", "REVOKED"), ("SUSPENDED", "ACTIVE")}
    if (current, target) not in allowed:
        raise ApiError("ERR_CARRIER_INVALID_STATE")
    if current == "SUSPENDED" and target == "ACTIVE":
        if rec["sanction_points"] >= calc.SANCTION_SUSPENSION_THRESHOLD:
            raise ApiError("ERR_CARRIER_INVALID_STATE")

    rec["custodial_status"] = target
    if target == "REVOKED":
        rec["suspension_reason"] = "PRIVILEGE_REVOKED"
    else:
        rec["suspension_reason"] = None
    touch(rec)

    if target == "REVOKED":
        domain.cascade_cancel_filed(rec, "CARRIER_SUSPENSION_CASCADE")
    return ok(domain.carrier_json(rec))


# --------------------------------------------------------------------------
# CustomsBond
# --------------------------------------------------------------------------
@bp.route("/in-bond/bonds", methods=["POST"])
def create_bond():
    require("CBPOfficer")
    body = v.get_body()
    carrier_id = v.req_str(body, "carrier_id")
    bond_type = v.req_enum(body, "bond_type", BOND_TYPES)
    limit_amount = v.req_money(body, "limit_amount", positive=True)
    effective_date = v.req_dt(body, "effective_date")
    expiry_date = v.req_dt(body, "expiry_date")
    surety_code = v.req_str(body, "surety_code")
    if expiry_date <= effective_date:
        raise ApiError("ERR_INVALID_REQUEST")

    if db.carriers.get(carrier_id) is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")

    rec = new_record()
    rec.update({
        "carrier_id": carrier_id,
        "bond_type": bond_type,
        "limit_amount": calc.round2(limit_amount),
        "obligated_amount": Decimal("0.00"),
        "available_amount": calc.round2(limit_amount),
        "status": "ACTIVE",
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "surety_code": surety_code,
        "open_movement_count": 0,
    })
    db.bonds[rec["id"]] = rec
    return ok(domain.bond_json(rec), 201)


@bp.route("/in-bond/bonds/<bond_id>", methods=["GET"])
def read_bond(bond_id):
    require(*ALL_ROLES)
    rec = db.bonds.get(bond_id)
    if rec is None:
        raise ApiError("ERR_BOND_NOT_FOUND")
    return ok(domain.bond_json(rec))


@bp.route("/in-bond/bonds", methods=["GET"])
def list_bonds():
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    items = domain.rows(db.bonds)
    for key in ("carrier_id", "bond_type", "status"):
        value = request.args.get(key)
        if value is not None and value != "":
            items = [b for b in items if b[key] == value]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.bond_json(b) for b in page], limit, offset, total)


@bp.route("/in-bond/bonds/<bond_id>", methods=["PATCH"])
def patch_bond(bond_id):
    user_id, _role = require("SuretyAgent")
    # Band 3: the SuretyAgent's user id IS the bond id it administers.
    if user_id != bond_id:
        raise ApiError("ERR_NOT_BOND_SURETY")

    body = v.get_body()
    target = v.opt_enum(body, "status", BOND_STATUSES)
    limit_amount = v.opt_money(body, "limit_amount", positive=True)

    rec = db.bonds.get(bond_id)
    if rec is None:
        raise ApiError("ERR_BOND_NOT_FOUND")

    if rec["status"] == "EXPIRED":
        raise ApiError("ERR_BOND_INVALID_STATE")
    if target is not None:
        allowed = {("ACTIVE", "SUSPENDED"), ("SATURATED", "SUSPENDED"),
                   ("SUSPENDED", "ACTIVE")}
        if (rec["status"], target) not in allowed:
            raise ApiError("ERR_BOND_INVALID_STATE")
        if target == "ACTIVE" and db.now > rec["expiry_date"]:
            raise ApiError("ERR_BOND_INVALID_STATE")

    before = (rec["limit_amount"], rec["status"], rec["obligated_amount"],
              rec["available_amount"], rec["open_movement_count"])
    if limit_amount is not None:
        rec["limit_amount"] = calc.round2(limit_amount)
    if target is not None:
        rec["status"] = target
    domain.recompute_bond(rec, mark=False)
    after = (rec["limit_amount"], rec["status"], rec["obligated_amount"],
             rec["available_amount"], rec["open_movement_count"])
    if before != after:
        touch(rec)
    return ok(domain.bond_json(rec))


# --------------------------------------------------------------------------
# Port
# --------------------------------------------------------------------------
@bp.route("/in-bond/ports", methods=["POST"])
def create_port():
    require("CBPOfficer")
    body = v.get_body()
    port_code = v.req_str(body, "port_code")
    if len(port_code) != 4 or not port_code.isdigit():
        raise ApiError("ERR_INVALID_REQUEST")
    name = v.req_str(body, "name")
    region_code = v.req_enum(body, "region_code", REGION_CODES)
    exam_capacity_slots = v.req_int(body, "exam_capacity_slots", minimum=0)
    go_warehouse_available = v.opt_bool(body, "go_warehouse_available", True)

    if domain.port_by_code(port_code) is not None:
        raise ApiError("ERR_DUPLICATE_PORT_CODE")

    rec = new_record()
    rec.update({
        "port_code": port_code,
        "name": name,
        "region_code": region_code,
        "exam_capacity_slots": exam_capacity_slots,
        "go_warehouse_available": go_warehouse_available,
        "open_hold_count": 0,
    })
    db.ports[rec["id"]] = rec
    return ok(domain.port_json(rec), 201)


@bp.route("/in-bond/ports/<port_id>", methods=["GET"])
def read_port(port_id):
    require(*ALL_ROLES)
    rec = db.ports.get(port_id)
    if rec is None:
        raise ApiError("ERR_PORT_NOT_FOUND")
    return ok(domain.port_json(rec))
