"""Category endpoints (PRD §3.2). Categories carry only id + created_at (§2.4)."""
from flask import Blueprint, request

import constants as C
from db import store
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import category_out
import validate as V

bp = Blueprint("categories", __name__)


@bp.route("/categories", methods=["POST"])
def create_category():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_PLATFORM_ADMIN})
    body = get_json_body()

    slug = V.require_str(body, "slug")
    name = V.require_str(body, "name")
    requires_pv = V.require_bool(body, "requires_phone_verified_seller", default=False)
    max_price = V.optional_int(body, "max_price_cents", minimum=0, default=0)

    # slug unique (§3.2).
    if slug in store.categories:
        raise err("ERR_INVALID_REQUEST", "Category slug already exists.")

    now = store.now()
    rec = {
        "id": store.new_id(),
        "slug": slug,
        "name": name,
        "requires_phone_verified_seller": requires_pv,
        "max_price_cents": max_price,
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.categories[slug] = rec
    return object_response(category_out(rec), 201)


@bp.route("/categories", methods=["GET"])
def list_categories():
    auth_context(require_auth=False)
    limit, offset = parse_pagination(request.args)
    return paginate_and_respond(list(store.categories.values()), limit, offset, category_out)
