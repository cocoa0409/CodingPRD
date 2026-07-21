"""UnusedTicketCredit read endpoints (all credit fields are server-managed)."""

from flask import Blueprint, request

import store
from common import get_or_404, single, list_result, filter_by, as_str
from auth import authenticate

bp = Blueprint("credits", __name__)

READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}


@bp.get("/tmc/unused-ticket-credits/<cid>")
def get_credit(cid):
    authenticate(READERS)
    return single(get_or_404(store.credits, cid))


@bp.get("/tmc/unused-ticket-credits")
def list_credits():
    authenticate(READERS)
    recs = filter_by(store.credits.values(), request.args,
                     {"traveler_id": as_str, "origin_booking_id": as_str,
                      "redeemed_by_booking_id": as_str, "vendor_id": as_str,
                      "status": as_str})
    return list_result(recs)
