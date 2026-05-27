"""EBT card routes."""

import random
from datetime import timedelta
from flask import Blueprint, request

from db import db, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    get_json_body, parse_pagination, paginate, new_id,
)


bp = Blueprint("ebt_cards", __name__)


def _card_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "household_id": c["household_id"],
        "pan_last4": c.get("pan_last4"),
        "status": c["status"],
        "replaced_by_card_id": c.get("replaced_by_card_id"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _generate_pan_last4() -> str:
    return f"{random.randint(0, 9999):04d}"


@bp.route("/snap/ebt-cards/<card_id>", methods=["GET"])
@require_roles("Caseworker", "Cardholder", "FraudInvestigator")
def get_card(card_id, _user_id, _role, **_):
    c = db.ebt_cards.get(card_id)
    if c is None:
        raise_api("ERR_NOT_FOUND", "EBTCard not found")
    if _role == "Cardholder" and _user_id != c["household_id"]:
        raise_api("ERR_FORBIDDEN", "Cardholder may only access own card")
    return success(_card_view(c))


@bp.route("/snap/ebt-cards", methods=["GET"])
@require_roles("Caseworker", "Cardholder", "FraudInvestigator")
def list_cards(_user_id, _role, **_):
    limit, offset = parse_pagination()
    hh_filter = request.args.get("household_id")
    status_filter = request.args.get("status")

    rows = list(db.ebt_cards.values())
    if hh_filter is not None:
        rows = [r for r in rows if r["household_id"] == hh_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if _role == "Cardholder":
        rows = [r for r in rows if r["household_id"] == _user_id]

    page, total = paginate(rows, limit, offset)
    return list_success([_card_view(r) for r in page], limit, offset, total)


@bp.route("/snap/ebt-cards/<card_id>/activate", methods=["POST"])
@require_roles("Cardholder", "Caseworker")
def activate_card(card_id, _user_id, _role, **_):
    c = db.ebt_cards.get(card_id)
    if c is None:
        raise_api("ERR_NOT_FOUND", "EBTCard not found")
    if c["status"] != "PENDING_ISSUE":
        raise_api("ERR_INVALID_STATE", "EBTCard must be PENDING_ISSUE to activate")
    hh = db.households.get(c["household_id"])
    if hh is None or hh["status"] != "ACTIVE":
        raise_api("ERR_HOUSEHOLD_NOT_ACTIVE", "Host household must be ACTIVE")
    if _role == "Cardholder" and _user_id != hh["id"]:
        raise_api("ERR_FORBIDDEN", "Cardholder may only activate own card")

    c["status"] = "ACTIVE"
    c["pan_last4"] = _generate_pan_last4()
    c["updated_at"] = db.current_utc_iso()
    c["version"] = int(c.get("version", 1)) + 1
    return success(_card_view(c))


@bp.route("/snap/ebt-cards/<card_id>/suspend", methods=["POST"])
@require_roles("Caseworker", "FraudInvestigator")
def suspend_card(card_id, **_):
    c = db.ebt_cards.get(card_id)
    if c is None:
        raise_api("ERR_NOT_FOUND", "EBTCard not found")
    if c["status"] != "ACTIVE":
        raise_api("ERR_INVALID_STATE", "EBTCard must be ACTIVE to suspend")

    c["status"] = "SUSPENDED"
    c["updated_at"] = db.current_utc_iso()
    c["version"] = int(c.get("version", 1)) + 1

    # Cascade: AUTHORIZED purchase txs on this card -> REVERSED
    for tx in db.purchase_transactions.values():
        if tx["ebt_card_id"] == card_id and tx["status"] == "AUTHORIZED":
            tx["status"] = "REVERSED"
            tx["updated_at"] = db.current_utc_iso()
            tx["version"] = int(tx.get("version", 1)) + 1

    return success(_card_view(c))


@bp.route("/snap/ebt-cards/<card_id>/reinstate", methods=["POST"])
@require_roles("Caseworker")
def reinstate_card(card_id, **_):
    c = db.ebt_cards.get(card_id)
    if c is None:
        raise_api("ERR_NOT_FOUND", "EBTCard not found")
    if c["status"] != "SUSPENDED":
        raise_api("ERR_INVALID_STATE", "EBTCard must be SUSPENDED to reinstate")
    hh = db.households.get(c["household_id"])
    if hh is None or hh["status"] != "ACTIVE":
        raise_api("ERR_HOUSEHOLD_NOT_ACTIVE", "Host household must be ACTIVE")

    c["status"] = "ACTIVE"
    c["updated_at"] = db.current_utc_iso()
    c["version"] = int(c.get("version", 1)) + 1
    return success(_card_view(c))


@bp.route("/snap/ebt-cards/<card_id>/replace", methods=["POST"])
@require_roles("Cardholder", "Caseworker")
def replace_card(card_id, _user_id, _role, **_):
    c = db.ebt_cards.get(card_id)
    if c is None:
        raise_api("ERR_NOT_FOUND", "EBTCard not found")
    if c["status"] != "ACTIVE":
        raise_api("ERR_INVALID_STATE", "EBTCard must be ACTIVE to replace")
    hh = db.households.get(c["household_id"])
    if hh is None or hh["status"] != "ACTIVE":
        raise_api("ERR_HOUSEHOLD_NOT_ACTIVE", "Host household must be ACTIVE")
    if _role == "Cardholder" and _user_id != hh["id"]:
        raise_api("ERR_FORBIDDEN", "Cardholder may only replace own card")

    now = db.current_utc_iso()

    # Create successor card with status ACTIVE
    successor = {
        "id": new_id(),
        "household_id": c["household_id"],
        "pan_last4": _generate_pan_last4(),
        "status": "ACTIVE",
        "replaced_by_card_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.ebt_cards[successor["id"]] = successor

    # Predecessor transitions to REPLACED, links to successor
    c["status"] = "REPLACED"
    c["replaced_by_card_id"] = successor["id"]
    c["updated_at"] = now
    c["version"] = int(c.get("version", 1)) + 1

    # If this is the >=3rd replacement of any card for this household within
    # a rolling 90-day window (endpoint = current_utc inclusive, lookback 90d),
    # raise a CARD_REPLACE_ABUSE fraud flag.
    now_dt = db.current_utc_dt()
    window_start = now_dt - timedelta(days=90)
    # Count cards in this household that are now REPLACED with updated_at in [window_start, now_dt]
    # (the predecessor's updated_at is `now`, so it's included)
    replacements = 0
    for card in db.ebt_cards.values():
        if card["household_id"] != hh["id"]:
            continue
        if card["status"] != "REPLACED":
            continue
        ua = parse_iso(card["updated_at"])
        if window_start <= ua <= now_dt:
            replacements += 1

    if replacements >= 3:
        flag_now = db.current_utc_iso()
        flag = {
            "id": new_id(),
            "household_id": hh["id"],
            "trigger_rule": "CARD_REPLACE_ABUSE",
            "status": "OPEN",
            "investigator_id": None,
            "resolution_note": None,
            "created_at": flag_now,
            "updated_at": flag_now,
            "version": 1,
        }
        db.fraud_flags[flag["id"]] = flag

    return success(_card_view(c))
