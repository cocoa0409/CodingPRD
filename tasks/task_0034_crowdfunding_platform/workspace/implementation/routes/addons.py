"""Add-on item CRUD."""

from flask import Blueprint, g

from db import DB, LOCK, new_id
from errors import (
    forbidden,
    invalid_state,
    not_found,
    validation_error,
)
from middleware import require_roles
from response import success_array, success_object
from services.common import (
    get_json_body,
    paginate,
    parse_pagination,
    require_positive_int,
    require_str,
    stamp_create,
)
from services.serializers import addon_view


bp = Blueprint("addons", __name__)


@bp.route("/projects/<project_id>/add-on-items", methods=["POST"])
@require_roles("Initiator")
def create_addon(project_id):
    body = get_json_body()
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        if project["initiator_id"] != g.user_id:
            raise forbidden()
        if project["status"] != "DRAFT":
            raise invalid_state("Add-on items can only be created while project is in DRAFT")

        name = require_str(body, "name")
        price_cents = require_positive_int(body, "price_cents")
        requires_shipping = body.get("requires_shipping", False)
        if requires_shipping is None:
            requires_shipping = False
        if not isinstance(requires_shipping, bool):
            raise validation_error("requires_shipping must be a boolean")
        inventory_limit = body.get("inventory_limit")
        if inventory_limit is not None:
            if isinstance(inventory_limit, bool) or not isinstance(inventory_limit, int) or inventory_limit < 0:
                raise validation_error("inventory_limit must be a non-negative integer or null")

        rec = stamp_create({
            "id": new_id(),
            "project_id": project_id,
            "name": name,
            "price_cents": price_cents,
            "requires_shipping": requires_shipping,
            "inventory_limit": inventory_limit,
            "inventory_claimed": 0,
        })
        DB.add_on_items[rec["id"]] = rec
    return success_object(addon_view(rec), status=201)


@bp.route("/projects/<project_id>/add-on-items", methods=["GET"])
@require_roles("Initiator", "Backer", "PlatformAdmin")
def list_addons(project_id):
    limit, offset = parse_pagination()
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        items = [a for a in DB.add_on_items.values() if a["project_id"] == project_id]
        items.sort(key=lambda a: a["created_at"])
        page, total, has_more = paginate(items, limit, offset)
        return success_array([addon_view(a) for a in page], limit=limit, offset=offset,
                             total_count=total, has_more=has_more)
