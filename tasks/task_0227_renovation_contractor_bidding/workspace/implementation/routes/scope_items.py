"""Standalone scope-line-item read endpoints (reverse-reachability)."""
from flask import Blueprint

import db
import response
from middleware import require_roles
from services import common, lookups

bp = Blueprint("scope_items", __name__)


@bp.route("/scope-line-items/<rid>", methods=["GET"])
def get_scope_item(rid):
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    rec = lookups.get_scope_line_item(rid)
    return response.success(common.public(rec), 200)


@bp.route("/scope-line-items/<rid>/bid-line-items", methods=["GET"])
def list_bid_lines_for_scope(rid):
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    lookups.get_scope_line_item(rid)
    items = [li for li in db.bid_line_items.values() if li["scope_line_item_id"] == rid]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)
