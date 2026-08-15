"""Ops checkpoint and the test-driving logical clock (PRD 2.5, 3.9)."""

from flask import Blueprint

from clock import CLOCK
from db import db
from errors import ApiError
from response import ok_object
from routes.common import authenticate, get_or_404, json_body
from services.sweeps import advance_month, expiry_sweep
from util import Body, iso3

bp = Blueprint("ops", __name__)


@bp.post("/acquirer/ops/advance-month")
def ops_advance_month():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    period_month = b.req_month("period_month")
    merchant_id = b.opt_str("merchant_id")

    # Priority 3: body-referenced merchant (when restricting the sweep).
    if merchant_id is not None:
        get_or_404(db.merchants, merchant_id, "Merchant")
    b.raise_pending()

    tally = advance_month(period_month, only_merchant_id=merchant_id)
    return ok_object(tally)


@bp.post("/acquirer/_clock/set_current_utc")
def set_clock():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    to = b.req_dt("to_iso8601")
    b.raise_pending()
    CLOCK.set(to)
    expiry_sweep()  # alert expiry + chargeback expiry (with cascades)
    return ok_object({"current_utc": iso3(CLOCK.now())})
