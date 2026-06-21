"""Add-on channel endpoints (PRD §3.5)."""

from flask import Blueprint, request

import db
import errors
from middleware import get_identity, require_role
from response import object_response
from services import common
from services import accounts as acc_svc
from services import calculations as calc

bp = Blueprint("addons", __name__)


@bp.route("/accounts/<account_id>/add-ons", methods=["POST"])
def attach_addon(account_id):
    user_id, role = get_identity()
    require_role(role, {"CustomerServiceAgent", "Subscriber"})
    acc = common.resolve_account(role, user_id, account_id)
    body = common.get_json_body()
    premium_channel_id = common.require_str(body, "premium_channel_id")
    channel = common.get_active_catalog(db.premium_channels, premium_channel_id)

    # Account activity gate (PRD §2.8).
    if acc["lifecycle_status"] != "ACTIVE":
        raise errors.account_not_active()

    # Business rule: min_package_rank <= current package rank.
    current_rank = calc.package_rank(acc["active_package_id"])
    if current_rank is None or channel["min_package_rank"] > current_rank:
        raise errors.addon_rank_too_high()

    created_at, updated_at, version = db.stamp_new()
    addon = {
        "id": db.new_id(),
        "account_id": account_id,
        "premium_channel_id": premium_channel_id,
        "status": "ACTIVE",
        "fee_cents": channel["monthly_fee_cents"],
        "drop_reason": None,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.add_on_subscriptions[addon["id"]] = addon
    acc_svc.recompute_recurring_only(acc)
    db.touch(acc)
    return object_response(addon, 201)


@bp.route("/accounts/<account_id>/add-ons", methods=["GET"])
def list_account_addons(account_id):
    user_id, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    common.resolve_account(role, user_id, account_id)
    items = [a for a in db.add_on_subscriptions.values() if a["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return common.paginate_and_respond(items)


@bp.route("/accounts/<account_id>/add-ons/<aid>/drop", methods=["POST"])
def drop_addon(account_id, aid):
    user_id, role = get_identity()
    require_role(role, {"CustomerServiceAgent", "Subscriber"})
    acc = common.resolve_account(role, user_id, account_id)
    addon = db.add_on_subscriptions.get(aid)
    if addon is None or addon["account_id"] != account_id:
        raise errors.subresource_not_found("Add-on not found under account")
    if addon["status"] != "ACTIVE":
        raise errors.invalid_state("Add-on must be ACTIVE to drop")
    addon["status"] = "DROPPED"
    addon["drop_reason"] = "USER"
    db.touch(addon)
    acc_svc.recompute_recurring_only(acc)
    db.touch(acc)
    return object_response(addon, 200)
