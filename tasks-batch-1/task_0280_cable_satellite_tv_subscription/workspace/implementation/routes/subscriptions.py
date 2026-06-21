"""Subscription endpoints: first activation, downgrade, upgrade (PRD §3.2, §3.4)."""

from flask import Blueprint, request

import db
import errors
from middleware import get_identity, require_role
from response import object_response
from services import common
from services import accounts as acc_svc
from services import calculations as calc

bp = Blueprint("subscriptions", __name__)


# ---------------------------------------------------------------------------
# First subscription activation (PROSPECT -> ACTIVE)
# ---------------------------------------------------------------------------
@bp.route("/accounts/<account_id>/subscriptions", methods=["POST"])
def activate_subscription(account_id):
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent"})
    acc = common.get_account_or_404(account_id)
    body = common.get_json_body()
    package_id = common.require_str(body, "package_id")
    package = common.get_active_catalog(db.channel_packages, package_id)
    # State check: lifecycle must be PROSPECT for first activation.
    if acc["lifecycle_status"] != "PROSPECT":
        raise errors.invalid_state("Account must be PROSPECT for first subscription")

    created_at, updated_at, version = db.stamp_new()
    sub = {
        "id": db.new_id(),
        "account_id": account_id,
        "package_id": package_id,
        "status": "ACTIVE",
        "base_fee_cents": package["monthly_fee_cents"],
        "previous_subscription_id": None,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.subscriptions[sub["id"]] = sub

    acc["lifecycle_status"] = "ACTIVE"
    acc["active_package_id"] = package_id
    acc_svc.recompute_account(acc)
    db.touch(acc)
    return object_response(sub, 201)


@bp.route("/accounts/<account_id>/subscriptions", methods=["GET"])
def list_account_subscriptions(account_id):
    user_id, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    common.resolve_account(role, user_id, account_id)
    items = [s for s in db.subscriptions.values() if s["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return common.paginate_and_respond(items)


# ---------------------------------------------------------------------------
# Tier change: downgrade / upgrade (with OCC)
# ---------------------------------------------------------------------------
def _tier_change(account_id, sid, direction):
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent"})
    acc = common.get_account_or_404(account_id)
    body = common.get_json_body()
    package_id = common.require_str(body, "package_id")
    # Existence ordering: catalog ref (package) checked before sub-resource.
    target = common.get_active_catalog(db.channel_packages, package_id)

    sub = db.subscriptions.get(sid)
    if sub is None or sub["account_id"] != account_id:
        raise errors.subresource_not_found("Subscription not found under account")

    # State check (sub must be ACTIVE).
    if sub["status"] != "ACTIVE":
        raise errors.invalid_state("Subscription must be ACTIVE for a tier change")

    # Account activity gate (PRD §2.8).
    if acc["lifecycle_status"] != "ACTIVE":
        raise errors.account_not_active()

    # OCC (PRD §2.9): expected_account_version is non-optional.
    expected = body.get("expected_account_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_account_version is required")
    if expected != acc["version"]:
        raise errors.stale_version()

    # Business rule: target rank must differ from current; target active.
    current_pkg = db.channel_packages.get(sub["package_id"])
    current_rank = current_pkg["rank"] if current_pkg else None
    target_rank = target["rank"]
    if target_rank == current_rank:
        raise errors.same_or_invalid_tier()
    # Direction sanity: a downgrade must lower rank, an upgrade must raise it.
    if direction == "downgrade" and target_rank > current_rank:
        raise errors.same_or_invalid_tier("Downgrade target rank must be lower")
    if direction == "upgrade" and target_rank < current_rank:
        raise errors.same_or_invalid_tier("Upgrade target rank must be higher")

    # Supersede the current subscription.
    sub["status"] = "SUPERSEDED"
    db.touch(sub)

    new_status = "DOWNGRADED" if direction == "downgrade" else "ACTIVE"
    created_at, updated_at, version = db.stamp_new()
    new_sub = {
        "id": db.new_id(),
        "account_id": account_id,
        "package_id": package_id,
        "status": new_status,
        "base_fee_cents": target["monthly_fee_cents"],
        "previous_subscription_id": sub["id"],
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.subscriptions[new_sub["id"]] = new_sub
    acc["active_package_id"] = package_id

    if direction == "downgrade":
        # Drop incompatible add-ons (min_package_rank > new rank).
        for addon in db.add_on_subscriptions.values():
            if addon["account_id"] != account_id or addon["status"] != "ACTIVE":
                continue
            channel = db.premium_channels.get(addon["premium_channel_id"])
            if channel and channel["min_package_rank"] > target_rank:
                addon["status"] = "DROPPED"
                addon["drop_reason"] = "INCOMPATIBLE_DOWNGRADE"
                db.touch(addon)
        # Eligibility-based promo rollback if rank fell below offer minimum.
        pa = calc.active_promotion_application(account_id)
        if pa is not None:
            offer = db.promotion_offers.get(pa["promotion_offer_id"])
            if offer and target_rank < offer["requires_min_rank"]:
                pa["status"] = "ROLLED_BACK"
                pa["discount_cents_snapshot"] = 0
                db.touch(pa)
                acc["promo_status"] = "ROLLED_BACK"

    # Recompute rsf (rank may cross PREMIER) then recurring; bump account.
    acc_svc.recompute_account(acc)
    db.touch(acc)
    return object_response(new_sub, 201)


@bp.route("/accounts/<account_id>/subscriptions/<sid>/downgrade", methods=["POST"])
def downgrade(account_id, sid):
    return _tier_change(account_id, sid, "downgrade")


@bp.route("/accounts/<account_id>/subscriptions/<sid>/upgrade", methods=["POST"])
def upgrade(account_id, sid):
    return _tier_change(account_id, sid, "upgrade")
