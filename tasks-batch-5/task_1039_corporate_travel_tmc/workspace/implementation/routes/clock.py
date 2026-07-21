"""Logical clock control and maintenance sweep."""

from flask import Blueprint

import store
import envelope
from store import touch
from auth import authenticate
from validate import get_body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate({"TravelManager", "FinanceOfficer", "System"})
    body = get_body()
    to_iso = req_dt(body, "to_iso8601")
    store.set_clock(store.parse_dt(to_iso))
    return envelope.success({}, "object", 200)


@bp.post("/tmc/maintenance/run-sweep")
def run_sweep():
    authenticate({"TravelManager", "System"})
    now = store.now()
    # NegotiatedRate ACTIVE/EXHAUSTED -> EXPIRED when now > valid_to
    for rate in store.rates.values():
        if rate["status"] in ("ACTIVE", "EXHAUSTED"):
            if now > store.parse_dt(rate["valid_to"]):
                rate["status"] = "EXPIRED"
                touch(rate)
    # UnusedTicketCredit AVAILABLE/PARTIALLY_USED -> EXPIRED when now > expiry_date
    for credit in store.credits.values():
        if credit["status"] in ("AVAILABLE", "PARTIALLY_USED"):
            if now > store.parse_dt(credit["expiry_date"]):
                credit["status"] = "EXPIRED"
                touch(credit)
    return envelope.success({}, "object", 200)
