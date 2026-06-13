"""Catalog endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers

bp = Blueprint("catalogs", __name__)


@bp.route("/catalogs", methods=["POST"])
def create_catalog():
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    body = helpers.get_json_body()

    style_name = helpers.as_str(body, "style_name")
    category = helpers.as_enum(body, "category", helpers.CATEGORY_VALUES)
    daily_rate_cents = helpers.as_int_min(body, "daily_rate_cents", 0)
    deposit_cents = helpers.as_int_min(body, "deposit_cents", 0)
    replacement_value_cents = helpers.as_int_min(body, "replacement_value_cents", 0)
    waiver_daily_rate_cents = helpers.as_int_min(body, "waiver_daily_rate_cents", 0)
    # cleaning_buffer_days defaults to 1 when not provided (PRD §3.1).
    cleaning_buffer_days = helpers.as_int_min(
        body, "cleaning_buffer_days", 0, required=False, default=1
    )
    late_fee_daily_rate_cents = helpers.as_int_min(body, "late_fee_daily_rate_cents", 0)

    catalog = {
        "style_name": style_name,
        "category": category,
        "daily_rate_cents": daily_rate_cents,
        "deposit_cents": deposit_cents,
        "replacement_value_cents": replacement_value_cents,
        "waiver_daily_rate_cents": waiver_daily_rate_cents,
        "cleaning_buffer_days": cleaning_buffer_days,
        "late_fee_daily_rate_cents": late_fee_daily_rate_cents,
    }
    db.stamp_create(catalog)
    db.catalogs[catalog["id"]] = catalog
    return success(views.catalog_view(catalog), status=201)


@bp.route("/catalogs/<cid>", methods=["GET"])
def get_catalog(cid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    catalog = helpers.find("Catalog", cid)
    return success(views.catalog_view(catalog))


@bp.route("/catalogs", methods=["GET"])
def list_catalogs():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    limit, offset = helpers.parse_pagination()
    category = request.args.get("category")
    records = list(db.catalogs.values())
    if category is not None:
        records = [c for c in records if c["category"] == category]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.catalog_view(c) for c in page], limit, offset, total)
