"""Renewal quotes: reads and the club's accept / decline decision."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import domain, quoting, validate

bp = Blueprint("quotes", __name__)


@bp.get("/fleetcare/renewal-quotes")
def list_quotes():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.quotes, {
        "contract_id": response.arg("contract_id"),
        "status": response.arg("status"),
    })


@bp.get("/fleetcare/renewal-quotes/<quote_id>")
def read_quote(quote_id):
    ctx = middleware.auth(*middleware.ALL_ROLES)
    quote = domain.need_quote(quote_id)
    middleware.require_club_scope(ctx, domain.club_id_of_contract(quote["contract_id"]))
    return response.object_response(quote)


def _decidable(quote, contract):
    if quote["status"] != "ISSUED" or contract is None or contract["status"] != "RENEWAL_QUOTED":
        raise ApiError("ERR_QUOTE_NOT_ISSUED")
    expires_at = db.parse_iso(quote["expires_at"])
    if not db.now() < expires_at:
        raise ApiError("ERR_QUOTE_EXPIRED")


@bp.post("/fleetcare/renewal-quotes/<quote_id>/accept")
def accept_quote(quote_id):
    ctx = middleware.auth(middleware.CLUB_MANAGER)
    quote = domain.need_quote(quote_id)
    contract = db.contracts.get(quote["contract_id"])
    middleware.require_club_scope(ctx, contract["club_id"] if contract else None)
    _decidable(quote, contract)

    db.apply_changes(quote, {"status": "ACCEPTED"})
    db.apply_changes(contract, {"status": "RENEWED"})
    return response.object_response(quote)


@bp.post("/fleetcare/renewal-quotes/<quote_id>/decline")
def decline_quote(quote_id):
    ctx = middleware.auth(middleware.CLUB_MANAGER)
    quote = domain.need_quote(quote_id)
    contract = db.contracts.get(quote["contract_id"])
    middleware.require_club_scope(ctx, contract["club_id"] if contract else None)
    body = middleware.body()
    reason = validate.string(body, "reason", min_len=1)
    _decidable(quote, contract)

    db.apply_changes(quote, {"status": "DECLINED", "decline_reason": reason})
    db.apply_changes(contract, {"status": "EXPIRED"})
    quoting.tear_down_forward_schedule(contract, "CONTRACT_EXPIRED")
    return response.object_response(quote)
