"""Shop create/get routes."""
import re
from flask import Blueprint, request
from middleware import require_role
from errors import err_invalid_input
from db import store, new_id, format_ts
from response import success_object
from serializers import shop_view
from routes.common import get_json_body, parse_str_field, parse_int_field, parse_number_field, get_shop_or_404

bp = Blueprint("shops", __name__)

EASA_RE = re.compile(r"^EASA-[0-9]{4,6}$")


@bp.route("/shops", methods=["POST"])
def create_shop():
    require_role("ShopAdmin")
    body = get_json_body()
    shop_name = parse_str_field(body, "shop_name", required=True)
    easa_id = parse_str_field(body, "easa_accreditation_id", required=True)
    if not EASA_RE.match(easa_id):
        raise err_invalid_input("easa_accreditation_id must match ^EASA-[0-9]{4,6}$")
    lrs = parse_int_field(body, "labor_rate_small_cents", required=True)
    lrm = parse_int_field(body, "labor_rate_medium_cents", required=True)
    lrl = parse_int_field(body, "labor_rate_large_cents", required=True)
    lrx = parse_int_field(body, "labor_rate_xlarge_cents", required=True)
    rush = parse_number_field(body, "rush_premium_pct", required=True)
    thr = parse_number_field(body, "replace_threshold_pct", required=True)
    slow = parse_number_field(body, "supplies_low_pct", required=True)
    shigh = parse_number_field(body, "supplies_high_pct", required=True)
    wm = parse_int_field(body, "warranty_months", required=True)
    psm = parse_int_field(body, "pool_slot_monthly_cents", required=True)
    pld = parse_int_field(body, "pool_loan_daily_cents", required=True)
    plg = parse_int_field(body, "pool_loan_grace_days", required=True)
    currency = body.get("currency", "USD")
    if currency != "USD":
        raise err_invalid_input("currency must be USD")

    now = store.now()
    shop = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "shop_name": shop_name,
        "easa_accreditation_id": easa_id,
        "labor_rate_small_cents": lrs,
        "labor_rate_medium_cents": lrm,
        "labor_rate_large_cents": lrl,
        "labor_rate_xlarge_cents": lrx,
        "rush_premium_pct": rush,
        "replace_threshold_pct": thr,
        "supplies_low_pct": slow,
        "supplies_high_pct": shigh,
        "warranty_months": wm,
        "pool_slot_monthly_cents": psm,
        "pool_loan_daily_cents": pld,
        "pool_loan_grace_days": plg,
        "currency": currency,
    }
    store.shops[shop["id"]] = shop
    return success_object(shop_view(shop), status=201)


@bp.route("/shops/<shopId>", methods=["GET"])
def get_shop(shopId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    shop = get_shop_or_404(shopId)
    return success_object(shop_view(shop))
