"""Parts catalog (PRD §3.6)."""
import errors
from db import db, make_common
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import serialize_part
from validation import (
    get_json,
    require_string,
    require_enum,
    require_int,
    optional_int,
)

PART_READ_ROLES = ("PartsClerk", "DealerAdmin", "ServiceAdvisor")


def register(app):

    @app.route("/parts", methods=["POST"])
    @require_roles("PartsClerk", "DealerAdmin")
    def create_part():
        body = get_json()
        sku = require_string(body, "sku")
        description = require_string(body, "description")
        category = require_enum(body, "category",
                                {"MECHANICAL", "FILTER", "PRECISION_AG", "TELEMATICS"})
        unit_price_cents = require_int(body, "unit_price_cents", gt=0)
        on_hand_qty = optional_int(body, "on_hand_qty", default=0, minimum=0)

        for p in db.parts.values():
            if p["sku"] == sku:
                raise err(errors.ERR_DUPLICATE_KEY, "sku already exists.")

        part = {
            "sku": sku,
            "description": description,
            "category": category,
            "unit_price_cents": unit_price_cents,
            "on_hand_qty": on_hand_qty,
            "reserved_qty": 0,
        }
        make_common(part)
        db.parts[part["id"]] = part
        return respond(serialize_part(part, recompute=True), status=201)

    @app.route("/parts", methods=["GET"])
    @require_roles(*PART_READ_ROLES)
    def list_parts():
        from flask import request
        items = list(db.parts.values())
        category = request.args.get("category")
        sku = request.args.get("sku")
        if category is not None:
            items = [p for p in items if p["category"] == category]
        if sku is not None:
            items = [p for p in items if p["sku"] == sku]
        return list_and_respond(items, lambda p: serialize_part(p, recompute=True))

    @app.route("/parts/<part_id>", methods=["GET"])
    @require_roles(*PART_READ_ROLES)
    def get_part(part_id):
        part = lookup(db.parts, part_id)
        return respond(serialize_part(part, recompute=True))
