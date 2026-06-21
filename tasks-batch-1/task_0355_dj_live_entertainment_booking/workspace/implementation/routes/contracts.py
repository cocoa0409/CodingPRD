"""Contract document endpoints."""
from flask import Blueprint

import db
from errors import invalid_state, not_resource_owner
from middleware import authenticate, require_roles
from response import array_response, object_response
from services import get_or_404
from validate import parse_pagination, paginate

bp = Blueprint("contracts", __name__)


@bp.get("/contracts/<cid>")
def get_contract(cid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Client"})
    rec = get_or_404(db.contracts, cid)
    if caller.role == "Client":
        booking = db.bookings.get(rec["booking_id"])
        if booking is None or caller.user_id != booking["client_id"]:
            raise not_resource_owner()
    return object_response(rec)


@bp.get("/bookings/<bid>/contracts")
def list_contracts(bid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Client"})
    limit, offset = parse_pagination()
    booking = get_or_404(db.bookings, bid)
    if caller.role == "Client" and caller.user_id != booking["client_id"]:
        raise not_resource_owner()
    rows = [c for c in db.contracts.values() if c["booking_id"] == bid]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


@bp.post("/contracts/<cid>/sign")
def sign_contract(cid):
    caller = authenticate()
    require_roles(caller, {"Client"})
    contract = get_or_404(db.contracts, cid)
    booking = db.bookings.get(contract["booking_id"])
    # Ownership (priority 3): acting client owns the booking.
    if booking is None or caller.user_id != booking["client_id"]:
        raise not_resource_owner()
    if contract["status"] != "ISSUED" or booking["status"] != "CONTRACT_SENT":
        raise invalid_state("contract is not signable from current state")
    contract["status"] = "SIGNED"
    db.touch(contract)
    return object_response(contract)


@bp.post("/contracts/<cid>/decline")
def decline_contract(cid):
    caller = authenticate()
    require_roles(caller, {"Client"})
    contract = get_or_404(db.contracts, cid)
    booking = db.bookings.get(contract["booking_id"])
    if booking is None or caller.user_id != booking["client_id"]:
        raise not_resource_owner()
    if contract["status"] != "ISSUED":
        raise invalid_state("only an ISSUED contract may be declined")
    contract["status"] = "DECLINED"
    db.touch(contract)
    return object_response(contract)
