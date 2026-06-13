"""Charge endpoints (PRD §3.7)."""
from flask import Blueprint

import serialize
from db import db, stamp_create, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path

bp = Blueprint("charges", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "Provider"]
SOURCE_TYPES = {"VISIT", "OCC_HEALTH"}


@bp.route("/visits/<vid>/charges", methods=["POST"])
def create_charge(vid):
    authorize(["Provider"])
    visit = get_path("visit", vid)
    body = get_json_body()
    require_str(body, "cpt_code")
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be a positive integer")
    source_type = body.get("source_type", "VISIT")
    if source_type not in SOURCE_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid source_type")

    # Charges may only be added while billing is OPEN.
    if visit["billing_status"] != "OPEN":
        raise err("ERR_BILLING_FROZEN", "billing not OPEN")

    charge = stamp_create({
        "visit_id": visit["id"],
        "cpt_code": body["cpt_code"],
        "amount_cents": amount,
        "source_type": source_type,
        "voided": False,
    })
    db.charges[charge["id"]] = charge
    return ok_object(serialize.charge(charge), 201)


@bp.route("/visits/<vid>/charges", methods=["GET"])
def list_charges(vid):
    authorize(READ_ROLES)
    visit = get_path("visit", vid)
    limit, offset = parse_pagination()
    items = [c for c in db.charges.values() if c["visit_id"] == visit["id"]]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.charge(c) for c in page], limit, offset, len(items))


@bp.route("/charges/<charge_id>/void", methods=["POST"])
def void_charge(charge_id):
    authorize(["Provider"])
    charge = get_path("charge", charge_id)
    visit = db.visits.get(charge["visit_id"])
    # Void only while billing OPEN.
    if visit is not None and visit["billing_status"] != "OPEN":
        raise err("ERR_BILLING_FROZEN", "billing not OPEN")
    charge["voided"] = True
    touch(charge)
    return ok_object(serialize.charge(charge))
