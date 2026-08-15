"""Negotiation round endpoints (PRD 3.6)."""
from flask import Blueprint

from db import store, touch
from errors import (
    ApiError, not_found,
    ERR_ROUND_NOT_PROPOSED, ERR_NOT_ROUND_PROPOSER,
)
from middleware import auth
from response import ok, paginated, sorted_items
from serializers import round_json

bp = Blueprint("negotiations", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]


def get_round_or_404(round_id):
    rnd = store.rounds.get(round_id)
    if rnd is None:
        raise not_found("Negotiation round does not exist")
    return rnd


@bp.get("/quotes/<quoteId>/negotiation-rounds")
def list_rounds(quoteId):
    auth(READ_ROLES)
    if quoteId not in store.quotes:
        raise not_found("Quote does not exist")
    items = [r for r in store.rounds.values() if r["quote_id"] == quoteId]
    return paginated([round_json(r) for r in sorted_items(items)])


@bp.get("/negotiation-rounds/<roundId>")
def get_round(roundId):
    auth(READ_ROLES)
    return ok(round_json(get_round_or_404(roundId)))


@bp.post("/negotiation-rounds/<roundId>/withdraw-round")
def withdraw_round(roundId):
    uid, role = auth(["Underwriter", "Broker"])
    rnd = get_round_or_404(roundId)
    if rnd["status"] != "PROPOSED":
        raise ApiError(ERR_ROUND_NOT_PROPOSED,
                       "Negotiation round must be in PROPOSED status", 409)
    # Only the party who proposed the round may withdraw it
    if (role == "Underwriter" and rnd["proposed_by"] != "UNDERWRITER") or (
            role == "Broker" and rnd["proposed_by"] != "BROKER"):
        raise ApiError(ERR_NOT_ROUND_PROPOSER,
                       "Only the party who proposed this round can withdraw it", 403)
    rnd["status"] = "WITHDRAWN"
    touch(rnd)
    return ok(round_json(rnd))
