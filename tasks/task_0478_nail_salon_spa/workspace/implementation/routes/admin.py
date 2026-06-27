"""Test-driving capabilities: logical clock and state injection (PRD §3.17)."""
from flask import Blueprint

from clock import clock
from common import json_body, touch, get_str, get_int
from datetime_util import parse_iso8601, format_iso8601
from errors import err, ERR_INVALID_REQUEST
from middleware import authorize
from lookup import get_client, get_appointment
from response import success_object
from serialize import client_out, appointment_out

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Available to SalonManager and FrontDesk (PRD §3.17 / §4).
    authorize({"SalonManager", "FrontDesk"})
    body = json_body(optional=False)
    value = body.get("to_iso8601")
    if value is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    dt = parse_iso8601(value)
    clock.set(dt)
    return success_object({}, status=200)


@bp.route("/_inject/client_state", methods=["POST"])
def inject_client_state():
    authorize({"SalonManager"})
    body = json_body(optional=False)
    client_id = get_str(body, "client_id", required=True)
    client = get_client(client_id)

    # Set the stored RAW strike count (decay applies on subsequent reads).
    if "active_no_show_strikes" in body and body["active_no_show_strikes"] is not None:
        raw = get_int(body, "active_no_show_strikes", required=True, minimum=0)
        client["_raw_strikes"] = raw
    if "last_no_show_at" in body and body["last_no_show_at"] is not None:
        # validate parseable; store canonical ISO form
        client["last_no_show_at"] = format_iso8601(parse_iso8601(body["last_no_show_at"]))
    if "loyalty_points_balance" in body and body["loyalty_points_balance"] is not None:
        client["loyalty_points_balance"] = get_int(
            body, "loyalty_points_balance", required=True, minimum=0)

    # deposit_required is recomputed from the resulting strike count on read.
    touch(client)
    return success_object(client_out(client), status=200)


@bp.route("/_inject/appointment_deposit", methods=["POST"])
def inject_appointment_deposit():
    authorize({"SalonManager"})
    body = json_body(optional=False)
    appointment_id = get_str(body, "appointment_id", required=True)
    deposit_due_cents = get_int(body, "deposit_due_cents", required=True, minimum=0)
    appt = get_appointment(appointment_id)
    if appt["booking_status"] != "REQUESTED":
        raise err(ERR_INVALID_REQUEST, "Deposit can only be forced on a REQUESTED appointment")
    appt["deposit_due_cents"] = deposit_due_cents
    touch(appt)
    return success_object(appointment_out(appt), status=200)
