"""SavedSearch & Alert read endpoints (PRD §3.8)."""
from flask import Blueprint, request

import constants as C
from db import store
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import saved_search_out, alert_out
import validate as V

bp = Blueprint("saved_searches", __name__)


def _find_saved_search(ss_id):
    ss = store.saved_searches.get(ss_id)
    if ss is None:
        raise err("ERR_NOT_FOUND", "Saved search not found.")
    return ss


@bp.route("/saved-searches", methods=["POST"])
def create_saved_search():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER})
    body = get_json_body()

    owner_id = V.require_str(body, "owner_id")
    category_slug = V.require_str(body, "category_slug")
    keyword = V.optional_str(body, "keyword", default=None, allow_empty=False)
    max_price = V.optional_int(body, "max_price_cents", minimum=0, default=0)

    # Existence (§2.5): owner then category.
    owner = store.members.get(owner_id)
    if owner is None:
        raise err("ERR_NOT_FOUND", "Owner not found.")
    if category_slug not in store.categories:
        raise err("ERR_NOT_FOUND", "Category not found.")

    now = store.now()
    sid = store.new_id()
    rec = {
        "id": sid,
        "owner_id": owner_id,
        "category_slug": category_slug,
        "keyword": keyword,
        "max_price_cents": max_price,
        "alert_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.saved_searches[sid] = rec
    return object_response(saved_search_out(rec), 201)


@bp.route("/saved-searches", methods=["GET"])
def list_saved_searches():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_PLATFORM_ADMIN})
    limit, offset = parse_pagination(request.args)
    recs = list(store.saved_searches.values())
    if "owner_id" in request.args:
        recs = [s for s in recs if s["owner_id"] == request.args.get("owner_id")]
    if "category_slug" in request.args:
        recs = [s for s in recs if s["category_slug"] == request.args.get("category_slug")]
    return paginate_and_respond(recs, limit, offset, saved_search_out)


@bp.route("/saved-searches/<ss_id>", methods=["GET"])
def get_saved_search(ss_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_PLATFORM_ADMIN})
    ss = _find_saved_search(ss_id)
    return object_response(saved_search_out(ss))


@bp.route("/saved-searches/<ss_id>/alerts", methods=["GET"])
def list_saved_search_alerts(ss_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_PLATFORM_ADMIN})
    _find_saved_search(ss_id)
    limit, offset = parse_pagination(request.args)
    recs = [a for a in store.alerts.values() if a["saved_search_id"] == ss_id]
    return paginate_and_respond(recs, limit, offset, alert_out)
