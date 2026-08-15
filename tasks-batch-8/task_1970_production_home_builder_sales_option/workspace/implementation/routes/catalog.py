"""OptionCatalogItem endpoints: create / community-scoped list (PRD 3.1)."""

import db
from constants import READ_ROLES, OPTION_CATEGORIES, BUILD_STAGES
from errors import ERR_COMMUNITY_NOT_FOUND
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import ser_option_item
from util import (
    body_json,
    check_shape,
    require_fk,
    pagination_params,
    paginate,
    apply_filters,
)

bp = make_blueprint("option_catalog")

CREATE_SPEC = {
    "community_id": {"type": "string", "required": True},
    "option_name": {"type": "string", "required": True},
    "category": {"type": "enum", "required": True, "values": OPTION_CATEGORIES},
    "price_cents": {"type": "integer", "required": True, "min": 1},
    "cutoff_stage": {"type": "enum", "required": True, "values": set(BUILD_STAGES)},
    "install_stage": {"type": "enum", "required": True, "values": set(BUILD_STAGES)},
}


@bp.post("/option-catalog-items")
def create_option_item():
    authenticate(["SalesDirector"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    require_fk("communities", body["community_id"], ERR_COMMUNITY_NOT_FOUND, "community")
    item = db.new_entity("option_items", {
        "community_id": body["community_id"],
        "option_name": body["option_name"],
        "category": body["category"],
        "price_cents": body["price_cents"],
        "cutoff_stage": body["cutoff_stage"],
        "install_stage": body["install_stage"],
    })
    return success_obj(ser_option_item(item), 201)


@bp.get("/communities/<cid>/option-catalog-items")
def list_option_items(cid):
    authenticate(READ_ROLES)
    require_fk("communities", cid, ERR_COMMUNITY_NOT_FOUND, "community")
    limit, offset = pagination_params()
    items = [i for i in db.all_of("option_items") if i["community_id"] == cid]
    items = apply_filters(items, ["category"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_option_item(i) for i in page], limit, offset, total, has_more)
