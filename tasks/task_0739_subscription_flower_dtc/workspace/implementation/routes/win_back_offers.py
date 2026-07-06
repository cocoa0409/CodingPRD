"""Win-back offer routes: POST /win-back-offers/{id}/redeem."""
from flask import Blueprint, request, g

from common import touch
from errors import (
    ApiError, invalid_state,
    ERR_OFFER_NOT_FOUND, ERR_OFFER_NOT_REDEEMABLE,
    ERR_OFFER_NOT_OWNED, ERR_OFFER_EXPIRED, ERR_SUBSCRIPTION_NOT_FOUND,
)
from middleware import auth_required
import db
from response import ok
from util import parse_iso
from services import validators as v
from services import calculations as calc
from services.views import winback_view

bp = Blueprint("win_back_offers", __name__)


@bp.route("/win-back-offers/<oid>/redeem", methods=["POST"])
@auth_required("Customer")
def redeem_offer(oid):
    offer = db.win_back_offers.get(oid)
    if offer is None:
        raise ApiError(ERR_OFFER_NOT_FOUND, "offer not found", 404)

    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    subscription_id = v.require_str(body, "subscription_id")

    sub = db.subscriptions.get(subscription_id)
    if sub is None:
        raise ApiError(ERR_SUBSCRIPTION_NOT_FOUND, "subscription not found", 404)

    # State (40): offer must be OFFERED and subscription CANCELLED.
    # Do NOT lazily flip status to EXPIRED here: PRD §2.9 orders the
    # temporal window check (step 8, ERR_OFFER_EXPIRED) after state (step 5),
    # ownership (step 7). Preempting via a lazy transition on the redeem
    # path would surface an expired offer as ERR_OFFER_NOT_REDEEMABLE
    # instead of ERR_OFFER_EXPIRED. The lazy transition applies only on
    # read endpoints per PRD §3.8.
    if offer["status"] != "OFFERED":
        raise ApiError(ERR_OFFER_NOT_REDEEMABLE,
                       "offer not redeemable", 409)
    if sub["lifecycle_status"] != "CANCELLED":
        raise invalid_state("subscription is not CANCELLED")

    # Ownership (50)
    if offer["customer_id"] != g.user_id or sub["customer_id"] != g.user_id:
        raise ApiError(ERR_OFFER_NOT_OWNED, "offer not owned", 403)

    # Temporal (55): boundary inclusive.
    exp = parse_iso(offer["expires_at"])
    if db.now() > exp:
        raise ApiError(ERR_OFFER_EXPIRED, "offer expired", 422)

    # Apply.
    offer["status"] = "REDEEMED"
    touch(offer)
    sub["lifecycle_status"] = "ACTIVE"
    sub["discount_pct"] = float(offer["discount_pct"])
    # Recompute renewal price so it reflects the discount on the next renewal.
    plan = db.plans[sub["plan_id"]]
    sub["renewal_price_cents"] = calc.renewal_price_cents(
        plan=plan, size=sub["size"], vase_addon=sub.get("vase_addon", False),
        discount_pct=sub["discount_pct"],
    )
    touch(sub)
    return ok(winback_view(offer))
