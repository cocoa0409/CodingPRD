"""CategoryRule routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role
from services import category_rules as svc

bp = Blueprint("category_rules", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/category-rules", methods=["POST"])
def create():
    require_role("PlatformAdmin")
    with db.LOCK:
        rec = svc.create_category_rule(request.get_json(force=True, silent=True) or {})
    return resp.success(rec, 201)


@bp.route("/category-rules", methods=["GET"])
def list_():
    require_role("PlatformAdmin", "Dispatcher", "HotlineOperator")
    limit, offset = resp.parse_pagination()
    with db.LOCK:
        rows, total = svc.list_category_rules(
            limit, offset,
            category_code=request.args.get("category_code"),
        )
    return resp.success_list(rows, total, limit, offset)
