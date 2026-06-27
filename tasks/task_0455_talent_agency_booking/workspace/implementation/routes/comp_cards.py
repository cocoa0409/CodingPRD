"""CompCard endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db, lock
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    public,
    get_json_body,
    require_str,
    require_int,
    require_array,
    lookup,
    paginate,
)

bp = Blueprint("comp_cards", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}


@bp.route("/comp-cards", methods=["POST"])
def create_comp_card():
    _, role = get_identity()
    require_role(role, {"Agent", "Talent"})
    body = get_json_body()
    talent_id = require_str(body, "talent_id")
    headshot_url = require_str(body, "headshot_url")
    height_cm = require_int(body, "height_cm", minimum=1)
    skills = require_array(body, "skills")
    with lock:
        lookup("Talent", talent_id)
        is_first = not any(
            c["talent_id"] == talent_id for c in db.comp_cards.values()
        )
        record = mint_common({
            "talent_id": talent_id,
            "headshot_url": headshot_url,
            "height_cm": height_cm,
            "skills": skills,
            "is_primary": is_first,
        })
        db.comp_cards[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/comp-cards", methods=["GET"])
def list_comp_cards():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.comp_cards.values())
        talent_id = request.args.get("talent_id")
        if talent_id is not None:
            items = [c for c in items if c["talent_id"] == talent_id]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/comp-cards/<card_id>", methods=["GET"])
def get_comp_card(card_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("CompCard", card_id)
        return object_response(public(record), status=200)
