"""FeeCharge routes and the test-driving clock."""
from flask import Blueprint, request

import db
import models
import clock
import validate as V
from middleware import get_identity, require_role
from errors import err, ERR_INVALID_STATE
import lookup
from util import parse_dt
from response import object_response, array_response
from services import reconcile

bp = Blueprint("fees", __name__)


@bp.route("/fee-charges/<rid>", methods=["GET"])
def get_fee(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    rec = lookup.get_fee_charge(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == rec["customer_id"])
    return object_response(models.ser_fee_charge(rec), 200)


@bp.route("/fee-charges", methods=["GET"])
def list_fees():
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    limit, offset = V.parse_pagination(request.args)
    items = list(db.fee_charges.values())
    customer_id = request.args.get("customer_id")
    appointment_id = request.args.get("appointment_id")
    if customer_id:
        items = [f for f in items if f["customer_id"] == customer_id]
    if appointment_id:
        items = [f for f in items if f["appointment_id"] == appointment_id]
    if role == "Customer":
        items = [f for f in items if f["customer_id"] == uid]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_fee_charge(f) for f in page], limit, offset, total, 200)


@bp.route("/fee-charges/<rid>/settle", methods=["POST"])
def settle_fee(rid):
    uid, role = get_identity()
    require_role(role, {"Customer"})
    rec = lookup.get_fee_charge(rid)
    lookup.forbid_unless(uid == rec["customer_id"])
    if rec["settlement_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Fee is not PENDING")
    rec["settlement_status"] = "SETTLED"
    models.touch(rec)
    customer = db.customers[rec["customer_id"]]
    reconcile.recompute_outstanding_fees(customer)
    models.touch(customer)
    return object_response(models.ser_fee_charge(rec), 200)


@bp.route("/fee-charges/<rid>/waive", methods=["POST"])
def waive_fee(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin"})
    rec = lookup.get_fee_charge(rid)
    if rec["settlement_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Fee is not PENDING")
    rec["settlement_status"] = "WAIVED"
    models.touch(rec)
    customer = db.customers[rec["customer_id"]]
    # waiving removes the strike: recompute outstanding + strikes (waived no
    # longer counts in the rolling window) + account status
    reconcile.recompute_outstanding_fees(customer)
    reconcile.recompute_customer_strikes(customer)
    models.touch(customer)
    return object_response(models.ser_fee_charge(rec), 200)


# ---- Logical clock ----
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin"})
    body = V.require_body(request.get_json(silent=True))
    to_iso8601 = V.require_field(body, "to_iso8601")
    dt = parse_dt(to_iso8601, "to_iso8601")
    clock.set_clock(dt)
    return object_response({}, 200)
