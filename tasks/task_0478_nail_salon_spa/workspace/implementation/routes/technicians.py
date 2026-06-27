"""Technician roster and lifecycle (PRD §3.1)."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_enum,
                    get_number, get_int, parse_pagination, paginate)
from db import db
from clock import clock
from datetime_util import parse_iso8601
from errors import (err, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE,
                    ERR_LICENSE_EXPIRED, ERR_FORBIDDEN, ERR_INVALID_REQUEST)
from middleware import authorize
from lookup import get_technician, get_station
from response import success_object, success_list
from serialize import technician_out, appointment_out, commission_statement_out

bp = Blueprint("technicians", __name__)

READ_ROLES = {"SalonManager", "FrontDesk", "Technician"}


@bp.route("/technicians", methods=["POST"])
def create_technician():
    authorize({"SalonManager"})
    body = json_body(optional=False)
    full_name = get_str(body, "full_name", required=True)
    license_number = get_str(body, "license_number", required=True)
    license_expiry_raw = get_str(body, "license_expiry", required=True)
    parse_iso8601(license_expiry_raw)  # validate parseable
    pay_model = get_enum(body, "pay_model", ["COMMISSION", "BOOTH_RENT"], required=True)
    commission_pct = get_number(body, "commission_pct", required=False, default=0.40,
                                minimum=0)
    if commission_pct > 1:
        raise err(ERR_INVALID_REQUEST, "commission_pct must be between 0 and 1")
    booth_rent_cents = get_int(body, "booth_rent_cents", required=False, default=0, minimum=0)
    home_station_id = get_str(body, "home_station_id", required=True)

    # FK existence (PRD §2.6) — body order: home_station_id
    get_station(home_station_id)

    # uniqueness on license_number (PRD §3.1)
    for t in db.technicians.values():
        if t["license_number"] == license_number:
            raise err(ERR_DUPLICATE_RESOURCE, "license_number already exists")

    rec = make_record({
        "full_name": full_name,
        "license_number": license_number,
        "license_expiry": license_expiry_raw,
        "pay_model": pay_model,
        "commission_pct": commission_pct,
        "booth_rent_cents": booth_rent_cents,
        "home_station_id": home_station_id,
        "status": "ACTIVE",
        "accrued_earnings_cents": 0,
        "lifetime_no_show_strikes_attributed": 0,
    })
    db.technicians[rec["id"]] = rec
    return success_object(technician_out(rec), status=201)


@bp.route("/technicians", methods=["GET"])
def list_technicians():
    authorize({"SalonManager", "FrontDesk"})
    items = list(db.technicians.values())
    hs = request.args.get("home_station_id")
    if hs is not None:
        items = [t for t in items if t["home_station_id"] == hs]
    st = request.args.get("status")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([technician_out(t) for t in page], limit, offset, total)


@bp.route("/technicians/<tid>", methods=["GET"])
def get_one_technician(tid):
    user_id, role = authorize(READ_ROLES)
    rec = get_technician(tid)
    if role == "Technician" and user_id != rec["id"]:
        raise err(ERR_FORBIDDEN, "Technician may only read their own record")
    return success_object(technician_out(rec), status=200)


@bp.route("/technicians/<tid>/suspend", methods=["POST"])
def suspend_technician(tid):
    authorize({"SalonManager"})
    rec = get_technician(tid)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Technician is not ACTIVE")
    # no appointment IN_SERVICE on this technician
    for ap in db.appointments.values():
        if ap["technician_id"] == tid and ap["booking_status"] == "IN_SERVICE":
            raise err(ERR_INVALID_STATE, "Technician has an in-service appointment")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success_object(technician_out(rec), status=200)


@bp.route("/technicians/<tid>/reinstate", methods=["POST"])
def reinstate_technician(tid):
    authorize({"SalonManager"})
    rec = get_technician(tid)
    if rec["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Technician is not SUSPENDED")
    if parse_iso8601(rec["license_expiry"]) <= clock.now():
        raise err(ERR_LICENSE_EXPIRED, "Cannot reinstate on an expired license")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(technician_out(rec), status=200)


@bp.route("/technicians/<tid>/terminate", methods=["POST"])
def terminate_technician(tid):
    authorize({"SalonManager"})
    rec = get_technician(tid)
    if rec["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Technician is not SUSPENDED")
    if rec["accrued_earnings_cents"] != 0:
        raise err(ERR_INVALID_STATE, "Technician has unsettled accrued earnings")
    rec["status"] = "TERMINATED"
    touch(rec)
    return success_object(technician_out(rec), status=200)


@bp.route("/technicians/<tid>/appointments", methods=["GET"])
def technician_appointments(tid):
    user_id, role = authorize(READ_ROLES)
    rec = get_technician(tid)
    if role == "Technician" and user_id != rec["id"]:
        raise err(ERR_FORBIDDEN, "Technician may only read their own appointments")
    items = [a for a in db.appointments.values() if a["technician_id"] == tid]
    bs = request.args.get("booking_status")
    if bs is not None:
        items = [a for a in items if a["booking_status"] == bs]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([appointment_out(a) for a in page], limit, offset, total)


@bp.route("/technicians/<tid>/commission-statements", methods=["GET"])
def technician_commission_statements(tid):
    user_id, role = authorize({"SalonManager", "Technician"})
    rec = get_technician(tid)
    if role == "Technician" and user_id != rec["id"]:
        raise err(ERR_FORBIDDEN, "Technician may only read their own statements")
    items = [s for s in db.commission_statements.values() if s["technician_id"] == tid]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([commission_statement_out(s) for s in page], limit, offset, total)
