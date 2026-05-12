"""Backer registration."""

from flask import Blueprint

from db import DB, LOCK, new_id
from errors import validation_error
from middleware import require_roles
from response import success_object
from services.common import get_json_body, require_str, stamp_create
from services.serializers import backer_view


bp = Blueprint("backers", __name__)


@bp.route("/backers", methods=["POST"])
@require_roles("Backer", "PlatformAdmin")
def create_backer():
    body = get_json_body()
    display_name = require_str(body, "display_name")
    email = require_str(body, "email")
    default_shipping_address = body.get("default_shipping_address")
    if default_shipping_address is not None and not isinstance(default_shipping_address, dict):
        raise validation_error("default_shipping_address must be an object")

    with LOCK:
        # Email uniqueness across all backers
        for b in DB.backers.values():
            if b.get("email") == email:
                raise validation_error("email already registered")
        rec = stamp_create({
            "id": new_id(),
            "display_name": display_name,
            "email": email,
            "default_shipping_address": default_shipping_address,
        })
        DB.backers[rec["id"]] = rec

    return success_object(backer_view(rec), status=201)
