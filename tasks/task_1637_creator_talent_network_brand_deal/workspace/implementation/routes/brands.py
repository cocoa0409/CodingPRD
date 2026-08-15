"""Brand endpoints: onboard, list, get, update (status / credit_hold)."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import helpers as H

bp = Blueprint("brands", __name__)


@bp.route("/brands", methods=["POST"])
@require_roles("BrandManager")
def create_brand(actor):
    payload = H.body()
    H.req_fields(payload, ["name", "industry"])
    name = H.require_str(payload, "name")
    industry = H.require_enum(payload, "industry", H.INDUSTRY_ENUM)

    brand = H.new_entity()
    brand.update({
        "name": name,
        "industry": industry,
        "status": "ACTIVE",
        "credit_hold": False,
        "outstanding_balance_cents": 0,
    })
    db.brands[brand["id"]] = brand
    return resp.created(brand)


@bp.route("/brands", methods=["GET"])
@require_roles("BrandManager", "FinanceAdmin", "TalentManager")
def list_brands(actor):
    items = list(db.brands.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/brands/<bid>", methods=["GET"])
@require_roles("BrandManager", "FinanceAdmin", "TalentManager", "Brand")
def get_brand(actor, bid):
    brand = H.get_or_404(db.brands, bid, "brand")
    if actor.role == "Brand":
        require_owner(actor, brand["id"], "brand")
    return resp.ok(brand)


@bp.route("/brands/<bid>", methods=["PATCH"])
@require_roles("BrandManager")
def update_brand(actor, bid):
    brand = H.get_or_404(db.brands, bid, "brand")
    payload = H.body()

    new_status = H.opt_enum(payload, "status", H.BRAND_STATUS_ENUM, default=None)
    credit_hold = H.opt_bool(payload, "credit_hold", default=None)

    if new_status is not None and new_status != brand["status"]:
        # Brand lifecycle: ACTIVE <-> SUSPENDED only.
        if (brand["status"], new_status) not in (
                ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")):
            raise err.invalid_state(
                f"Brand cannot transition {brand['status']} -> {new_status}")
        brand["status"] = new_status

    if credit_hold is not None:
        brand["credit_hold"] = credit_hold

    H.touch(brand)
    return resp.ok(brand)
