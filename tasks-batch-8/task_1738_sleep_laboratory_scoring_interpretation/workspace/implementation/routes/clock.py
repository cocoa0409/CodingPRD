"""Test-driving logical clock (PRD 2.4). Setting the clock runs the
authorization expiry sweep: an APPROVED authorization whose window_end has
passed (strictly — current logical date > window_end) while its parent order
is AUTHORIZED expires, taking the order to EXPIRED with it."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from services.core import touch
from util import CLOCK, parse_date
from validate import get_body, req_datetime_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorized(["LabDirector"])
    body = get_body()
    to_iso8601 = req_datetime_str(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    current_date = CLOCK.today()
    for auth in db["authorizations"].values():
        if auth["status"] != "APPROVED":
            continue
        if current_date <= parse_date(auth["window_end"]):
            continue
        order = db["referral_orders"].get(auth["order_id"])
        if order is None or order["status"] != "AUTHORIZED":
            continue
        auth["status"] = "EXPIRED"
        touch(auth)
        order["status"] = "EXPIRED"
        touch(order)
    return success_object({"current_utc": CLOCK.now_iso()})
