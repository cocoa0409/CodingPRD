"""Gift card endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response

bp = Blueprint("gift_cards", __name__)


@bp.post("/studio-ops/gift-cards")
def create_gift_card():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    code = helpers.as_str(body, "code")
    issued = helpers.as_int(body, "issued_value_cents", min_value=1)
    for gc in db.gift_cards.values():
        if gc["code"] == code:
            raise err(errors.ERR_DUPLICATE_RESOURCE, "Gift card code already exists")
    rec = models.make_gift_card(code, issued)
    db.gift_cards[rec["id"]] = rec
    return object_response(models.serialize_gift_card(rec), 201)


@bp.get("/studio-ops/gift-cards/<gid>")
def get_gift_card(gid):
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    rec = db.gift_cards.get(gid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Gift card not found")
    return object_response(models.serialize_gift_card(rec), 200)
