"""Sample/demo units and checkouts."""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import now, touch
from errors import err, not_found, invalid_request
from middleware import api, body, ctx, ALL_ROLES
from response import success_object, success_list
from services import (
    CHECKOUT_DAYS, CHECKOUT_BUFFER_DAYS, DAMAGED_RETURN_BP,
    depreciated_value, post_entry, recompute_rep, rhu_div,
)

bp = Blueprint("samples", __name__)


# ---------------------------------------------------------------------------
# Sample units
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/sample-units", methods=["POST"])
@api(["PrincipalOps"])
def create_sample_unit():
    data = body()
    principal_id = data.get("principal_id")
    if not isinstance(principal_id, str):
        raise invalid_request("principal_id is required")
    principal = db.principals.get(principal_id)
    if principal is None:
        raise not_found("Principal")
    if ctx()["user_id"] != principal["id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "PrincipalOps may only consign units for its own principal")
    if principal["status"] == "TERMINATED":
        raise err("ERR_LINE_TERMINATED", "A TERMINATED principal consigns nothing new")
    serial = data.get("serial_number")
    family = data.get("family_code")
    value = data.get("value_cents")
    if not isinstance(serial, str) or not serial:
        raise invalid_request("serial_number is required")
    if not isinstance(family, str) or not family:
        raise invalid_request("family_code is required")
    if not db.is_int(value) or value <= 0:
        raise invalid_request("value_cents must be a positive integer")
    for other in db.sample_units.values():
        if other["principal_id"] == principal_id and other["serial_number"] == serial:
            raise err("ERR_DUPLICATE_SERIAL",
                      "serial_number already registered for this principal")
    unit = {
        "principal_id": principal_id,
        "serial_number": serial,
        "family_code": family,
        "value_cents": value,
        "status": "IN_STOCK",
    }
    db.stamp_new(unit)
    db.sample_units[unit["id"]] = unit
    return success_object(unit, 201)


@bp.route("/rep-agency/sample-units", methods=["GET"])
@api(ALL_ROLES)
def list_sample_units():
    items = list(db.sample_units.values())
    for param in ("principal_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [u for u in items if u[param] == value]
    return success_list(items)


@bp.route("/rep-agency/sample-units/<uid>", methods=["GET"])
@api(ALL_ROLES)
def get_sample_unit(uid):
    unit = db.sample_units.get(uid)
    if unit is None:
        raise not_found("SampleUnit")
    return success_object(unit)


# ---------------------------------------------------------------------------
# Sample checkouts
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/sample-checkouts", methods=["POST"])
@api(["Rep"])
def create_checkout():
    data = body()
    unit_id = data.get("sample_unit_id")
    if not isinstance(unit_id, str):
        raise invalid_request("sample_unit_id is required")
    unit = db.sample_units.get(unit_id)
    if unit is None:
        raise not_found("SampleUnit")
    if unit["status"] != "IN_STOCK":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Sample unit must be IN_STOCK to check out")
    rep = db.reps[ctx()["user_id"]]
    if rep["status"] == "COMMISSION_HOLD":
        raise err("ERR_REP_ON_HOLD", "Rep is on COMMISSION_HOLD")
    # blocked interval with inspection buffer
    unit_checkouts = sorted(
        (c for c in db.checkouts.values() if c["sample_unit_id"] == unit["id"]),
        key=lambda c: c["_seq"])
    if unit_checkouts:
        latest = unit_checkouts[-1]
        if latest["status"] == "OPEN":
            raise err("ERR_CHECKOUT_WINDOW_CONFLICT",
                      "Sample unit has an OPEN checkout")
        anchor = latest["returned_at"] if latest["returned_at"] is not None else latest["due_at"]
        if now() < anchor + timedelta(days=CHECKOUT_BUFFER_DAYS):
            raise err("ERR_CHECKOUT_WINDOW_CONFLICT",
                      "Sample unit is inside its inspection buffer")
    co = {
        "sample_unit_id": unit["id"],
        "rep_id": rep["id"],
        "checked_out_at": now(),
        "due_at": now() + timedelta(days=CHECKOUT_DAYS),
        "returned_at": None,
        "condition_on_return": None,
        "charge_cents": None,
        "status": "OPEN",
    }
    db.stamp_new(co)
    db.checkouts[co["id"]] = co
    unit["status"] = "CHECKED_OUT"
    touch(unit)
    return success_object(co, 201)


@bp.route("/rep-agency/sample-checkouts", methods=["GET"])
@api(ALL_ROLES)
def list_checkouts():
    items = list(db.checkouts.values())
    for param in ("sample_unit_id", "rep_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    return success_list(items)


def _checkout_owned(cid):
    co = db.checkouts.get(cid)
    if co is None:
        raise not_found("SampleCheckout")
    if ctx()["user_id"] != co["rep_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "Rep may only act on its own checkouts")
    return co


@bp.route("/rep-agency/sample-checkouts/<cid>", methods=["GET"])
@api(ALL_ROLES)
def get_checkout(cid):
    co = db.checkouts.get(cid)
    if co is None:
        raise not_found("SampleCheckout")
    return success_object(co)


@bp.route("/rep-agency/sample-checkouts/<cid>/return", methods=["POST"])
@api(["Rep"])
def return_checkout(cid):
    co = _checkout_owned(cid)
    if co["status"] != "OPEN":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only an OPEN checkout can be returned")
    data = body()
    condition = data.get("condition_on_return")
    if condition not in ("SELLABLE", "DAMAGED"):
        raise invalid_request("condition_on_return must be SELLABLE or DAMAGED")
    unit = db.sample_units[co["sample_unit_id"]]
    co["returned_at"] = now()
    co["condition_on_return"] = condition
    if condition == "SELLABLE":
        unit["status"] = "IN_STOCK"
        co["charge_cents"] = 0
    else:
        dep = depreciated_value(unit["value_cents"], co["checked_out_at"], now())
        charge = rhu_div(dep * DAMAGED_RETURN_BP, 10000)
        co["charge_cents"] = charge
        unit["status"] = "WRITTEN_OFF"
        post_entry(rep_id=co["rep_id"], principal_id=unit["principal_id"],
                   order_id=None, statement_id=None, etype="SAMPLE_CHARGE",
                   amount_cents=-charge, business_date=now())
        recompute_rep(co["rep_id"])
    co["status"] = "RETURNED"
    touch(co)
    touch(unit)
    return success_object(co)


@bp.route("/rep-agency/sample-checkouts/<cid>/convert", methods=["POST"])
@api(["Rep"])
def convert_checkout(cid):
    co = _checkout_owned(cid)
    if co["status"] != "OPEN":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only an OPEN checkout can be converted")
    unit = db.sample_units[co["sample_unit_id"]]
    charge = depreciated_value(unit["value_cents"], co["checked_out_at"], now())
    co["charge_cents"] = charge
    co["status"] = "CONVERTED"
    touch(co)
    unit["status"] = "CONVERTED"
    touch(unit)
    post_entry(rep_id=co["rep_id"], principal_id=unit["principal_id"],
               order_id=None, statement_id=None, etype="SAMPLE_CHARGE",
               amount_cents=-charge, business_date=now())
    recompute_rep(co["rep_id"])
    return success_object(co)
