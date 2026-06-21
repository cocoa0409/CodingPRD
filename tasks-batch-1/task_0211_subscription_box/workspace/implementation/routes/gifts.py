"""Gift grant endpoints (PRD §3.11)."""
import secrets

from flask import Blueprint, request, g

from db import db
from common import (new_record, touch, serialize, get_body, require_str,
                    require_int, require_field, must_exist, paginate)
from middleware import authenticate, require_roles, require_owner_subscriber
from response import success, list_success
from errors import err, ERR_INVALID_STATE, ERR_GIFT_NOT_REDEEMABLE
from services.ledger import (cadence_delta, create_invoice, create_wallet_entry)

bp = Blueprint("gifts", __name__)


@bp.post("/gift-grants")
def create_gift_grant():
    authenticate()
    require_roles("Subscriber")
    body = get_body()
    plan_id = require_str(body, "plan_id")
    gifter_subscriber_id = require_str(body, "gifter_subscriber_id")
    term_periods = require_int(body, "term_periods", minimum=1)
    recipient_email = require_str(body, "recipient_email")

    # ownership: gifter acts on own gifter_subscriber_id
    require_owner_subscriber(gifter_subscriber_id)
    # existence of FKs
    must_exist(db.subscribers, gifter_subscriber_id, "Subscriber")
    plan = must_exist(db.plans, plan_id, "Plan")

    amount = plan["period_price_cents"] * term_periods  # no prepaid discount on gifts
    grant = new_record({
        "plan_id": plan_id,
        "gifter_subscriber_id": gifter_subscriber_id,
        "term_periods": term_periods,
        "recipient_email": recipient_email,
        "redemption_code": "gift_" + secrets.token_urlsafe(16),
        "amount_paid_cents": amount,
        "status": "ISSUED",
        "redeemed_subscription_id": None,
    })
    db.gift_grants[grant["id"]] = grant
    create_invoice(gifter_subscriber_id, None, amount, "GIFT_CHARGE")
    return success(serialize(grant), status=201)


@bp.get("/gift-grants/<gid>")
def get_gift_grant(gid):
    authenticate()
    require_roles("Subscriber", "CurationAdmin")
    grant = must_exist(db.gift_grants, gid, "GiftGrant")
    if g.role == "Subscriber":
        require_owner_subscriber(grant["gifter_subscriber_id"])
    return success(serialize(grant))


@bp.get("/gift-grants")
def list_gift_grants():
    authenticate()
    require_roles("Subscriber", "CurationAdmin")
    records = list(db.gift_grants.values())
    if g.role == "Subscriber":
        records = [r for r in records if r["gifter_subscriber_id"] == g.user_id]
    gifter_filter = request.args.get("gifter_subscriber_id")
    if gifter_filter is not None:
        records = [r for r in records if r["gifter_subscriber_id"] == gifter_filter]
    plan_filter = request.args.get("plan_id")
    if plan_filter is not None:
        records = [r for r in records if r["plan_id"] == plan_filter]
    redeemed_filter = request.args.get("redeemed_subscription_id")
    if redeemed_filter is not None:
        records = [r for r in records if r.get("redeemed_subscription_id") == redeemed_filter]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.post("/gift-grants/redeem")
def redeem_gift_grant():
    authenticate()
    require_roles("Subscriber")
    body = get_body()
    redemption_code = require_str(body, "redemption_code")
    subscriber_id = require_str(body, "subscriber_id")

    # ownership: recipient redeems against own subscriber_id
    require_owner_subscriber(subscriber_id)
    must_exist(db.subscribers, subscriber_id, "Subscriber")

    grant = None
    for gr in db.gift_grants.values():
        if gr["redemption_code"] == redemption_code:
            grant = gr
            break
    if grant is None:
        from errors import ERR_NOT_FOUND
        raise err(ERR_NOT_FOUND, "Gift grant not found.")

    # business: code must be ISSUED
    if grant["status"] != "ISSUED":
        raise err(ERR_GIFT_NOT_REDEEMABLE, "Gift code is not redeemable.")

    plan = db.plans[grant["plan_id"]]
    now = db.now()
    sub = new_record({
        "subscriber_id": subscriber_id,
        "plan_id": grant["plan_id"],
        "lifecycle_status": "ACTIVE",
        "billing_status": "PREPAID",
        "is_gift": True,
        "prepaid_periods_remaining": grant["term_periods"],
        "prepaid_unit_value_cents": 0,
        "current_period_index": 1,
        "next_renewal_at": now + cadence_delta(plan["cadence"]),
        "paused_until": None,
        "pause_count_in_term": 0,
        "cancelled_at": None,
        "_pause_start": None,
    })
    db.subscriptions[sub["id"]] = sub

    grant["status"] = "REDEEMED"
    grant["redeemed_subscription_id"] = sub["id"]
    touch(grant)
    return success(serialize(sub), status=201)


@bp.post("/gift-grants/<gid>/revoke")
def revoke_gift_grant(gid):
    authenticate()
    require_roles("BillingOperator")
    grant = must_exist(db.gift_grants, gid, "GiftGrant")
    if grant["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Only an ISSUED gift grant can be revoked.")
    grant["status"] = "REVOKED"
    touch(grant)
    create_invoice(grant["gifter_subscriber_id"], None,
                   -grant["amount_paid_cents"], "CANCEL_REFUND")
    create_wallet_entry(grant["gifter_subscriber_id"], grant["amount_paid_cents"],
                        "REFUND_CREDIT")
    return success(serialize(grant))
