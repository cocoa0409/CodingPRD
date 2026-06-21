"""Promotion endpoints: apply / win-back (PRD §3.6)."""

from flask import Blueprint, request

import db
import errors
from middleware import get_identity, require_role
from response import object_response
from services import common
from services import accounts as acc_svc
from services import calculations as calc

bp = Blueprint("promotions", __name__)


@bp.route("/accounts/<account_id>/promotions", methods=["POST"])
def apply_promotion(account_id):
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent"})
    acc = common.get_account_or_404(account_id)
    body = common.get_json_body()
    promotion_offer_id = common.require_str(body, "promotion_offer_id")
    offer = common.get_active_catalog(db.promotion_offers, promotion_offer_id)

    # Account activity gate (PRD §2.8).
    if acc["lifecycle_status"] != "ACTIVE":
        raise errors.account_not_active()

    # OCC (PRD §2.9): expected_account_version non-optional.
    expected = body.get("expected_account_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_account_version is required")
    if expected != acc["version"]:
        raise errors.stale_version()

    promo_status = acc["promo_status"]
    is_winback = False
    if promo_status == "PROMO_ACTIVE":
        raise errors.promo_already_active()

    current_rank = calc.package_rank(acc["active_package_id"])

    if promo_status == "ROLLED_BACK":
        # Win-back requires a rollback_protected offer.
        if not offer["rollback_protected"]:
            raise errors.promo_not_winback_eligible()
        if current_rank is None or current_rank < offer["requires_min_rank"]:
            raise errors.promo_rank_not_met()
        is_winback = True
    else:  # NONE -> first application
        if current_rank is None or current_rank < offer["requires_min_rank"]:
            raise errors.promo_rank_not_met()

    created_at, updated_at, version = db.stamp_new()
    applied_at_tenure = acc["tenure_months"]
    pa = {
        "id": db.new_id(),
        "account_id": account_id,
        "promotion_offer_id": promotion_offer_id,
        "status": "ACTIVE",
        "applied_at_tenure": applied_at_tenure,
        "rollback_at_tenure": applied_at_tenure + offer["promo_months"],
        "discount_cents_snapshot": 0,
        "is_winback": is_winback,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.promotion_applications[pa["id"]] = pa
    acc["promo_status"] = "PROMO_ACTIVE"

    # Recompute recurring including the discount, then snapshot the discount.
    acc_svc.recompute_recurring_only(acc)
    pa["discount_cents_snapshot"] = _current_discount(acc)
    db.touch(acc)
    return object_response(pa, 201)


def _current_discount(account):
    """The discount the single ACTIVE promo currently contributes."""
    sub = calc.current_subscription(account["id"])
    package_base = sub["base_fee_cents"] if sub else 0
    addon_sum = calc.active_addon_sum(account["id"])
    equip_sum = calc.assigned_equipment_sum(account["id"])
    rsf = account["regional_sports_fee_cents"]
    gross = package_base + addon_sum + equip_sum + rsf
    return calc.promo_discount(account["id"], gross, package_base)


@bp.route("/accounts/<account_id>/promotions", methods=["GET"])
def list_account_promotions(account_id):
    user_id, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    common.resolve_account(role, user_id, account_id)
    items = [p for p in db.promotion_applications.values() if p["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return common.paginate_and_respond(items)
