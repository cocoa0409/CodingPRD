"""VirtualCard routes: issue (OCC), get, list, freeze, unfreeze, close."""
from flask import Blueprint, request

from common import (get_json_body, require_fields, require_nonneg_int,
                    paginate, list_response)
from db import store, base_fields, touch
from errors import err
from middleware import require_roles
from response import success
from services import get_or_404, recompute_card

bp = Blueprint("cards", __name__)


def _card_view(c):
    return dict(c)


@bp.route("/trip-requests/<trip_id>/virtual-cards", methods=["POST"])
@require_roles("FinanceAdmin")
def issue_card(trip_id):
    trip = get_or_404(store.trip_requests, trip_id)
    body = get_json_body()
    # body well-formedness: load_limit_cents and expected_trip_request_version required
    require_fields(body, ["load_limit_cents", "expected_trip_request_version"])
    load_limit = require_nonneg_int(body, "load_limit_cents")
    expected_version = require_nonneg_int(body, "expected_trip_request_version")
    # state: trip must be APPROVED
    if trip["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Trip is not APPROVED")
    # OCC (priority 7)
    if expected_version != trip["version"]:
        raise err("ERR_STALE_VERSION", "Stale trip request version")
    # fiscal: load_limit <= remaining budget at issuance
    if load_limit > trip["remaining_budget_cents"]:
        raise err("ERR_CARD_LIMIT_EXCEEDED", "Load limit exceeds remaining budget")

    c = base_fields()
    c.update({
        "trip_request_id": trip_id,
        "load_limit_cents": load_limit,
        "authorized_holds_cents": 0,
        "captured_total_cents": 0,
        "available_balance_cents": load_limit,
        "status": "ACTIVE",
    })
    store.virtual_cards[c["id"]] = c
    # advance the funding trip's version by one
    touch(trip)
    return success(_card_view(c), status=201)


@bp.route("/virtual-cards/<card_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler")
def get_card(card_id):
    c = get_or_404(store.virtual_cards, card_id)
    return success(_card_view(c))


@bp.route("/virtual-cards", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler")
def list_cards():
    limit, offset = paginate()
    items = list(store.virtual_cards.values())
    trip_request_id = request.args.get("trip_request_id")
    if trip_request_id is not None:
        items = [c for c in items if c["trip_request_id"] == trip_request_id]
    page, pagination = list_response(items, limit, offset)
    return success([_card_view(c) for c in page], pagination=pagination)


@bp.route("/virtual-cards/<card_id>/freeze", methods=["POST"])
@require_roles("FinanceAdmin")
def freeze_card(card_id):
    c = get_or_404(store.virtual_cards, card_id)
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Card is not ACTIVE")
    c["status"] = "FROZEN"
    touch(c)
    return success(_card_view(c))


@bp.route("/virtual-cards/<card_id>/unfreeze", methods=["POST"])
@require_roles("FinanceAdmin")
def unfreeze_card(card_id):
    c = get_or_404(store.virtual_cards, card_id)
    if c["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Card is not FROZEN")
    c["status"] = "ACTIVE"
    touch(c)
    return success(_card_view(c))


@bp.route("/virtual-cards/<card_id>/close", methods=["POST"])
@require_roles("FinanceAdmin")
def close_card(card_id):
    c = get_or_404(store.virtual_cards, card_id)
    if c["status"] not in ("ACTIVE", "FROZEN"):
        raise err("ERR_INVALID_STATE", "Card cannot be closed from its current state")
    # ensure ledger is current before checking holds
    recompute_card(c)
    if c["authorized_holds_cents"] != 0:
        raise err("ERR_CARD_HAS_OPEN_HOLDS", "Card has outstanding authorization holds")
    c["status"] = "CLOSED"
    touch(c)
    return success(_card_view(c))
