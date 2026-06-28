"""LinkedCard and RoundUpAccrual routes (PRD §3.4)."""

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_json, require_auth, require_owner
from models import new_entity, recompute_pending_roundup, serialize, touch
from response import success
from routes.helpers import (
    fetch_or_404,
    list_response,
    require_int,
    require_str,
)
from services.calc import roundup_amounts

bp = Blueprint("cards", __name__)

MULTIPLIERS = {1, 2, 3, 10}


# ---------------------------------------------------------------------------
# LinkedCard (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.route("/linked-cards", methods=["POST"])
def create_linked_card():
    role, user_id = require_auth({"Investor"})
    body = get_json()
    account_id = require_str(body, "account_id")
    last_four = require_str(body, "last_four")

    account = fetch_or_404(store.accounts, account_id)
    require_owner(role, user_id, account["id"])

    multiplier = body.get("roundup_multiplier")
    if multiplier is None:
        multiplier = 1
    else:
        if isinstance(multiplier, bool) or not isinstance(multiplier, int):
            raise err("ERR_INVALID_MULTIPLIER", "roundup_multiplier must be an integer in {1,2,3,10}.")
        if multiplier not in MULTIPLIERS:
            raise err("ERR_INVALID_MULTIPLIER", "roundup_multiplier must be one of {1,2,3,10}.")

    card = new_entity(
        {
            "account_id": account_id,
            "last_four": last_four,
            "roundup_multiplier": multiplier,
            "status": "LINKED",
        }
    )
    store.linked_cards[card["id"]] = card
    return success(serialize(card), status=201)


@bp.route("/linked-cards/<entity_id>", methods=["GET"])
def get_linked_card(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    card = fetch_or_404(store.linked_cards, entity_id)
    require_owner(role, user_id, card["account_id"])
    return success(serialize(card))


@bp.route("/linked-cards", methods=["GET"])
def list_linked_cards():
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    items = list(store.linked_cards.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    # Investor sees only own cards.
    if role == "Investor":
        items = [c for c in items if c["account_id"] == user_id]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


@bp.route("/linked-cards/<entity_id>", methods=["PATCH"])
def update_linked_card(entity_id):
    role, user_id = require_auth({"Investor"})
    card = fetch_or_404(store.linked_cards, entity_id)
    require_owner(role, user_id, card["account_id"])
    body = get_json()

    if "roundup_multiplier" in body and body["roundup_multiplier"] is not None:
        m = body["roundup_multiplier"]
        if isinstance(m, bool) or not isinstance(m, int) or m not in MULTIPLIERS:
            raise err("ERR_INVALID_MULTIPLIER", "roundup_multiplier must be one of {1,2,3,10}.")
        card["roundup_multiplier"] = m

    if "status" in body and body["status"] is not None:
        s = body["status"]
        if s not in ("LINKED", "PAUSED", "UNLINKED"):
            raise err("ERR_INVALID_REQUEST", "status must be one of LINKED, PAUSED, UNLINKED.")
        card["status"] = s

    touch(card)
    return success(serialize(card))


# ---------------------------------------------------------------------------
# RoundUpAccrual (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.route("/roundup-accruals", methods=["POST"])
def create_roundup_accrual():
    role, user_id = require_auth({"Investor"})
    body = get_json()
    account_id = require_str(body, "account_id")
    linked_card_id = require_str(body, "linked_card_id")
    purchase_amount_cents = require_int(body, "purchase_amount_cents", minimum=1)

    account = fetch_or_404(store.accounts, account_id)
    card = fetch_or_404(store.linked_cards, linked_card_id)
    require_owner(role, user_id, account["id"])

    base, effective = roundup_amounts(purchase_amount_cents, card["roundup_multiplier"])

    accrual = new_entity(
        {
            "account_id": account_id,
            "linked_card_id": linked_card_id,
            "purchase_amount_cents": purchase_amount_cents,
            "base_roundup_cents": base,
            "effective_amount_cents": effective,
            "status": "PENDING",
        }
    )
    store.roundup_accruals[accrual["id"]] = accrual
    # Increase the account's pending_roundup_cents (PRD §3.4) — no version bump
    # (see models.recompute_pending_roundup).
    recompute_pending_roundup(account)
    return success(serialize(accrual), status=201)


@bp.route("/roundup-accruals/<entity_id>", methods=["GET"])
def get_roundup_accrual(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    accrual = fetch_or_404(store.roundup_accruals, entity_id)
    require_owner(role, user_id, accrual["account_id"])
    return success(serialize(accrual))


@bp.route("/roundup-accruals", methods=["GET"])
def list_roundup_accruals():
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    items = list(store.roundup_accruals.values())
    account_id = request.args.get("account_id")
    linked_card_id = request.args.get("linked_card_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [a for a in items if a["account_id"] == account_id]
    if linked_card_id is not None:
        items = [a for a in items if a["linked_card_id"] == linked_card_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if role == "Investor":
        items = [a for a in items if a["account_id"] == user_id]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


@bp.route("/roundup-accruals/<entity_id>/cancel", methods=["POST"])
def cancel_roundup_accrual(entity_id):
    role, user_id = require_auth({"Investor"})
    accrual = fetch_or_404(store.roundup_accruals, entity_id)
    require_owner(role, user_id, accrual["account_id"])
    if accrual["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING accrual can be cancelled.")
    accrual["status"] = "CANCELLED"
    touch(accrual)
    account = store.accounts[accrual["account_id"]]
    recompute_pending_roundup(account)
    return success(serialize(accrual))
