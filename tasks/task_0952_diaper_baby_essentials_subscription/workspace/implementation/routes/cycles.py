"""The recurring cycle: allocation, cutoff, charge, dispatch, delivery, skip."""

from flask import Blueprint, g

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import api, get_cycle, lookup, require_account_owner
from envelope import ok, created, paginate
from errors import ApiError
from store import db, now, touch

bp = Blueprint("cycles", __name__)

READ_ROLES = ["AccountHolder", "SupportAgent", "OpsAdmin"]


def _owner_of(cycle):
    sub = services.subscription_of_cycle(cycle)
    return sub["account_id"] if sub else None


@api(bp, "GET", "/cycles/<id>", READ_ROLES)
def read_cycle(id):
    return ok(serialize.cycle(get_cycle(id)))


@api(bp, "GET", "/cycles", READ_ROLES)
def list_cycles():
    rows = [r for r in db.cycles.values()
            if shapes.match(r, "subscription_id", shapes.qs("subscription_id"))
            and shapes.match(r, "status", shapes.qs("status"))
            and shapes.match(r, "payment_status", shapes.qs("payment_status"))]
    return paginate(rows, serialize.cycle)


@api(bp, "POST", "/cycles/<id>/allocate", ["OpsAdmin"])
def allocate(id):
    cycle = get_cycle(id)
    sub = services.subscription_of_cycle(cycle)
    child = services.child_of_subscription(sub) if sub else None
    plan_row = services.plan_of_subscription(sub) if sub else None
    if sub is None or sub["lifecycle_state"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")
    if child is None or child["archived"]:
        raise ApiError("ERR_CHILD_ARCHIVED")
    if cycle["status"] != "PLANNED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    services.allocate_cycle(cycle, sub, child, plan_row)
    cycle["status"] = "ALLOCATED"
    touch(cycle)
    services.recompute_account_estimate(sub["account_id"])
    return ok(serialize.cycle(cycle))


@api(bp, "POST", "/cycles/<id>/lock", ["OpsAdmin"])
def lock(id):
    cycle = get_cycle(id)
    if cycle["status"] != "ALLOCATED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    # Inclusive: the exact cutoff instant qualifies.
    if now() < cycle["cutoff_at"]:
        raise ApiError("ERR_CUTOFF_NOT_REACHED")
    cycle["status"] = "CUTOFF_LOCKED"
    touch(cycle)
    return ok(serialize.cycle(cycle))


@api(bp, "GET", "/cycles/<id>/pricing-preview", READ_ROLES)
def pricing_preview(id):
    cycle = get_cycle(id)
    breakdown = services.derive_pricing(cycle)
    return ok({
        "subtotal_cents": breakdown["subtotal_cents"],
        "shipping_cents": breakdown["shipping_cents"],
        "gift_credit_applied_cents": breakdown["gift_credit_applied_cents"],
        "referral_credit_applied_cents": breakdown["referral_credit_applied_cents"],
        "loyalty_redemption_applied_cents": breakdown["loyalty_redemption_applied_cents"],
        "loyalty_points_redeemed": breakdown["loyalty_points_redeemed"],
        "promo_discount_cents": breakdown["promo_discount_cents"],
        "total_due_cents": breakdown["total_due_cents"],
        "points_earn_base_cents": breakdown["points_earn_base_cents"],
    })


@api(bp, "POST", "/cycles/<id>/charge", ["OpsAdmin"])
def charge(id):
    cycle = get_cycle(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("credit_ids", kind="id_list", default=None),
    ])
    sub = services.subscription_of_cycle(cycle)
    account = db.accounts.get(sub["account_id"]) if sub else None

    # G7 — rung 20 (account), 24 (fulfilment axis), 25 (payment axis), 32 (credit)
    if account is None or account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if cycle["status"] not in ("ALLOCATED", "CUTOFF_LOCKED"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if cycle["payment_status"] != "UNCHARGED":
        raise ApiError("ERR_CYCLE_PAYMENT_STATE_INVALID")

    named = parsed["credit_ids"]
    if named is not None:
        rows = []
        for credit_id in named:
            credit = lookup(db.credits, credit_id, "Credit")
            rows.append(credit)
        for credit in rows:
            if credit["status"] not in ("AVAILABLE", "PARTIALLY_CONSUMED"):
                raise ApiError("ERR_CREDIT_NOT_AVAILABLE")
        # G8 — rung 43, only reachable when credits are NAMED explicitly.
        for credit in rows:
            if credit["expires_at"] <= now():
                raise ApiError("ERR_CREDIT_EXPIRED")

    breakdown = services.derive_pricing(cycle, named)

    # G9 — rung 70. The single declared MUTATE-THEN-REJECT case.
    if breakdown["total_due_cents"] > 0 and not account["payment_method_on_file"]:
        if sub["billing_state"] == "CURRENT":
            sub["billing_state"] = "PAST_DUE"
            touch(sub)
        raise ApiError("ERR_NO_PAYMENT_METHOD")

    contributions = []
    for entry in breakdown["gift_plan"] + breakdown["referral_plan"]:
        services.consume_credit(entry["credit"], entry["cents"])
        contributions.append({"credit_id": entry["credit"]["id"],
                              "cents": entry["cents"]})
    db.cycle_credit_contributions[cycle["id"]] = contributions

    wallet = services.wallet_of_account(account["id"])
    if breakdown["loyalty_points_redeemed"] > 0 and wallet is not None:
        services.write_ledger_entry(
            wallet, "REDEEM", -breakdown["loyalty_points_redeemed"],
            cycle_id=cycle["id"])
        touch(wallet)

    cycle["subtotal_cents"] = breakdown["subtotal_cents"]
    cycle["shipping_cents"] = breakdown["shipping_cents"]
    cycle["gift_credit_applied_cents"] = breakdown["gift_credit_applied_cents"]
    cycle["referral_credit_applied_cents"] = breakdown["referral_credit_applied_cents"]
    cycle["loyalty_redemption_applied_cents"] = breakdown["loyalty_redemption_applied_cents"]
    cycle["loyalty_points_redeemed"] = breakdown["loyalty_points_redeemed"]
    cycle["promo_discount_cents"] = breakdown["promo_discount_cents"]
    cycle["total_due_cents"] = breakdown["total_due_cents"]

    total = breakdown["total_due_cents"]
    cycle["charged_cash_cents"] = total
    cycle["retained_cash_cents"] = total
    cycle["payment_status"] = "FULLY_COVERED" if total == 0 else "CHARGED"
    touch(cycle)

    if sub["billing_state"] in ("PAST_DUE", "DELINQUENT"):
        sub["billing_state"] = "CURRENT"
        touch(sub)

    # A gift claimed as credit reaches FULFILLED when a charge fully consumes
    # the derived GIFT credit.
    for entry in breakdown["gift_plan"]:
        credit = entry["credit"]
        if credit["credit_type"] != "GIFT" or credit["status"] != "CONSUMED":
            continue
        gift = db.gift_orders.get(credit.get("source_gift_order_id"))
        if gift is not None and gift["status"] == "CLAIMED_CREDIT":
            gift["status"] = "FULFILLED"
            touch(gift)

    services.recompute_account_estimate(account["id"])
    return ok(serialize.cycle(cycle))


@api(bp, "POST", "/cycles/<id>/dispatch", ["OpsAdmin"])
def dispatch(id):
    cycle = get_cycle(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("service_level", kind="enum", members=C.SERVICE_LEVELS,
                     default="STANDARD"),
    ])
    if cycle["status"] != "CUTOFF_LOCKED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if cycle["payment_status"] not in ("FULLY_COVERED", "CHARGED"):
        raise ApiError("ERR_CYCLE_PAYMENT_STATE_INVALID")
    account_id = _owner_of(cycle)
    services.check_shipment_spacing(account_id)

    services.create_shipment(account_id, cycle["id"], None,
                             parsed["service_level"] or "STANDARD")
    cycle["status"] = "DISPATCHED"
    cycle["dispatched_at"] = now()
    touch(cycle)
    return ok(serialize.cycle(cycle))


def _pending_referral_for_first_delivery(account_id):
    """Returns the PENDING referral that this delivery would vest, or None."""
    for sub in services.subscriptions_of_account(account_id):
        for cycle in services.cycles_of_subscription(sub["id"]):
            if cycle["status"] == "DELIVERED":
                return None
    for referral in store.by_created(list(db.referrals.values())):
        if referral["referee_account_id"] == account_id and \
                referral["status"] == "PENDING":
            return referral
    return None


@api(bp, "POST", "/cycles/<id>/deliver", ["OpsAdmin"])
def deliver(id):
    cycle = get_cycle(id)
    if cycle["status"] != "DISPATCHED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    sub = services.subscription_of_cycle(cycle)
    account_id = sub["account_id"] if sub else None

    # G8 rung 44 — a referral may vest only at or before its expires_at.
    referral = _pending_referral_for_first_delivery(account_id)
    if referral is not None and now() > referral["expires_at"]:
        raise ApiError("ERR_REFERRAL_WINDOW_EXPIRED")

    # HOP 1
    cycle["status"] = "DELIVERED"
    cycle["delivered_at"] = now()

    wallet = services.wallet_of_account(account_id)
    if wallet is not None:
        # HOP 2 — the tier is read BEFORE the HOP-3 re-evaluation.
        tier_before = wallet["tier"]
        base = calc.points_earn_base_cents(cycle)
        earned = calc.points_earned(base, tier_before)
        cycle["points_earned"] = earned
        services.write_ledger_entry(
            wallet, "EARN", earned, cycle_id=cycle["id"], earn_base_cents=base,
            tier_multiplier_applied=float(calc.dec(
                calc.TIER_MULTIPLIERS.get(tier_before, C.TIER_MULTIPLIER_BRONZE))),
            expires_at=store.plus_days(now(), C.POINTS_EXPIRY_DAYS))
        # HOP 3 — upgrade-only re-evaluation.
        tier_after = services.evaluate_tier(wallet, upgrade_only=True)
        touch(wallet)
        # HOPS 4, 5 and 6.
        services.apply_free_shipping_from_tier(account_id, tier_after)
    touch(cycle)

    if referral is not None:
        _vest_referral(referral, cycle)
    services.recompute_account_estimate(account_id)
    return ok(serialize.cycle(cycle))


def _vest_referral(referral, cycle):
    """Vesting is tied to actual delivery. The five-per-365-days cap is enforced
    at referral CREATION, never here, so an existing referral always vests."""
    referral["status"] = "VESTED"
    referral["vested_at"] = now()
    referral["vesting_cycle_id"] = cycle["id"]
    referral["credit_cents"] = calc.referral_credit_amount_cents(now())
    touch(referral)
    services.issue_credit(
        referral["referrer_account_id"], "REFERRAL", referral["credit_cents"],
        True, store.plus_days(now(), C.CREDIT_EXPIRY_DAYS),
        source_referral_id=referral["id"])
    services.recompute_account_estimate(referral["referrer_account_id"])


@api(bp, "POST", "/cycles/<id>/skip", ["AccountHolder"])
def skip(id):
    cycle = get_cycle(id)
    sub = services.subscription_of_cycle(cycle)
    require_account_owner(_owner_of(cycle))
    if cycle["status"] not in ("PLANNED", "ALLOCATED"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if now() >= cycle["cutoff_at"]:
        raise ApiError("ERR_PAST_CUTOFF")
    # Pinned order: the allowance rung is evaluated BEFORE the paused rung.
    if services.skip_allowance_remaining(sub["id"]) < 1:
        raise ApiError("ERR_SKIP_ALLOWANCE_EXHAUSTED")
    if sub["lifecycle_state"] == "PAUSED":
        raise ApiError("ERR_SKIP_WHILE_PAUSED")

    anchor_before = sub["anchor_date"]
    anchor_after = store.plus_days(anchor_before, int(sub["cadence_interval_days"]))

    services.return_cycle_stock(cycle, delete_lines=True)
    cycle["status"] = "SKIPPED"
    services.apply_pricing(cycle)
    touch(cycle)

    record = store.base_row(full=False)
    record.update({
        "subscription_id": sub["id"],
        "cycle_id": cycle["id"],
        "status": "APPLIED",
        "anchor_before": anchor_before,
        "anchor_after": anchor_after,
    })
    db.skip_records[record["id"]] = record
    sub["anchor_date"] = anchor_after
    touch(sub)
    services.recompute_account_estimate(sub["account_id"])
    return ok(serialize.cycle(cycle))


@api(bp, "DELETE", "/cycles/<id>/skip", ["AccountHolder"])
def revoke_skip(id):
    cycle = get_cycle(id)
    sub = services.subscription_of_cycle(cycle)
    require_account_owner(_owner_of(cycle))
    if cycle["status"] != "SKIPPED":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if now() >= cycle["cutoff_at"]:
        raise ApiError("ERR_PAST_CUTOFF")
    records = [r for r in db.skip_records.values()
               if r["cycle_id"] == cycle["id"] and r["status"] == "APPLIED"]
    if not records:
        raise ApiError("ERR_SKIP_RECORD_NOT_FOUND")
    record = store.by_created(records)[-1]

    cycle["status"] = "PLANNED"
    touch(cycle)
    record["status"] = "REVOKED"
    sub["anchor_date"] = record["anchor_before"]
    touch(sub)
    services.recompute_account_estimate(sub["account_id"])
    return ok(serialize.cycle(cycle))


@api(bp, "POST", "/cycles/<id>/return", ["AccountHolder", "OpsAdmin"])
def return_cycle(id):
    cycle = get_cycle(id)
    sub = services.subscription_of_cycle(cycle)
    require_account_owner(_owner_of(cycle))
    if cycle["status"] not in ("DISPATCHED", "DELIVERED"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    amount, fee = calc.cancel_refund_cents(
        cycle, sub["cadence_interval_days"], now())
    cycle["status"] = "RETURNED"
    touch(cycle)
    shipment = services.shipment_of_cycle(cycle["id"])
    if shipment is not None and shipment["status"] != "RETURNED":
        shipment["status"] = "RETURNED"
        touch(shipment)
    services.create_refund(sub["account_id"], cycle["id"], None, "RETURN",
                           amount, fee)
    services.recompute_account_estimate(sub["account_id"])
    return ok(serialize.cycle(cycle))


@api(bp, "POST", "/cycles/<id>/refund-requests", ["AccountHolder", "OpsAdmin"])
def open_refund_request(id):
    cycle = get_cycle(id)
    sub = services.subscription_of_cycle(cycle)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("reason", required=True, kind="enum",
                     members=C.REFUND_REASONS),
    ])
    require_account_owner(_owner_of(cycle))
    # Rung 15 — the Pipeline-G reason GIFT_REFUND and the operator reason
    # GOODWILL are reserved for OpsAdmin.
    if g.role == "AccountHolder" and parsed["reason"] in ("GIFT_REFUND", "GOODWILL"):
        raise ApiError("ERR_PIPELINE_R_REFUND_ACTOR")

    amount, fee = calc.cancel_refund_cents(
        cycle, sub["cadence_interval_days"], now())
    refund = services.create_refund(sub["account_id"], cycle["id"], None,
                                    parsed["reason"], amount, fee)
    return created(serialize.refund(refund))
