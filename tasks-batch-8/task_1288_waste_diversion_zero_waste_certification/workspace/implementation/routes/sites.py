"""Site endpoints."""

from flask import Blueprint

from db import base_record, store
from errors import not_found
from middleware import ALL_ROLES, authenticate, check_unknown, f_int, f_str, get_body
from response import success_object
from services.lifecycle import pub_site

bp = Blueprint("sites", __name__)


@bp.route("/sites", methods=["POST"])
def create_site():
    authenticate(["SustainabilityManager"])
    b = get_body()
    check_unknown(b, ["name", "landfill_tip_fee_per_ton_cents",
                      "max_rebate_rate_per_ton_cents"])
    name = f_str(b, "name")
    tip_fee = f_int(b, "landfill_tip_fee_per_ton_cents")
    cap = f_int(b, "max_rebate_rate_per_ton_cents")

    rec = base_record({
        "name": name,
        "landfill_tip_fee_per_ton_cents": tip_fee,
        "max_rebate_rate_per_ton_cents": cap,
        "certification_tier": "NONE",
        "program_standing": "GOOD_STANDING",
    })
    store.sites[rec["id"]] = rec
    return success_object(pub_site(rec), 201)


@bp.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    authenticate(ALL_ROLES)
    rec = store.sites.get(site_id)
    if rec is None:
        raise not_found("Site not found")
    return success_object(pub_site(rec))
