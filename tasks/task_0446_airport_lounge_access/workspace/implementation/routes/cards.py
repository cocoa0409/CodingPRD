"""EligibilityCard endpoints (PRD §3.2)."""
from flask import Blueprint

import errors
import clock
import domain
from db import db, new_id, make_common_fields, touch
from middleware import get_principal, require_role
from validation import get_json_body, require_str, require_enum
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("cards", __name__)

CARD_STATUS = {"BASIC", "SILVER", "GOLD"}
FARE_CLASS = {"ECONOMY", "BUSINESS", "FIRST"}


def _deactivate_others(member_id, keep_id):
    for c in db.eligibility_cards.items.values():
        if c["member_id"] == member_id and c["id"] != keep_id and c.get("active"):
            c["active"] = False
            touch(c)


@bp.route("/eligibility-cards", methods=["POST"])
def issue_card():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()

    member_id = require_str(body, "member_id")
    card_status = require_enum(body, "card_status", CARD_STATUS)
    fare_class = require_enum(body, "fare_class", FARE_CLASS)
    valid_until = require_str(body, "valid_until")
    try:
        clock.parse_iso(valid_until)
    except (ValueError, TypeError):
        raise errors.invalid_request("valid_until must be ISO 8601")

    if not domain.get_member(member_id):
        raise errors.not_found("Member not found")

    card = {
        "id": new_id(),
        "member_id": member_id,
        "card_status": card_status,
        "fare_class": fare_class,
        "active": True,
        "valid_until": clock.to_iso_millis(clock.parse_iso(valid_until)),
    }
    card.update(make_common_fields())
    card["_seq"] = db.eligibility_cards.next_seq()
    db.eligibility_cards.items[card["id"]] = card
    # issuing a new card flips any prior active card inactive
    _deactivate_others(member_id, card["id"])
    return success(serialize(card), status=201)


@bp.route("/eligibility-cards", methods=["GET"])
def list_cards():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    return list_filtered(
        db.eligibility_cards,
        [("member_id", "member_id", "str"), ("active", "active", "bool")],
    )


@bp.route("/eligibility-cards/<card_id>", methods=["GET"])
def get_card(card_id):
    user_id, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    card = domain.get_card(card_id)
    if not card:
        raise errors.not_found("Card not found")
    if role == "Member" and user_id != card["member_id"]:
        raise errors.not_owner("Member may only read their own cards")
    return success(serialize(card))


@bp.route("/eligibility-cards/<card_id>/activate", methods=["POST"])
def activate_card(card_id):
    user_id, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    card = domain.get_card(card_id)
    if not card:
        raise errors.not_found("Card not found")
    if role == "Member" and user_id != card["member_id"]:
        raise errors.not_owner("Member may only activate their own cards")
    card["active"] = True
    touch(card)
    _deactivate_others(card["member_id"], card["id"])
    return success(serialize(card))
