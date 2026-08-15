"""Domain logic: shared helpers for accounts, subscriptions, sweeps."""
from datetime import timedelta
from decimal import Decimal

import db
from errors import ApiError
from util import (
    new_uuid, now_iso, format_ts, parse_iso, round_half_up_cents, touch,
    whole_days, add_months,
)
from services.billing import (
    post_event, recompute_outstanding_balance_v2, current_price_cents,
    payment_will_succeed, DAYS_PER_PERIOD_NOMINAL, DUNNING_RETRY_OFFSETS_HOURS,
    MAX_DUNNING_ATTEMPTS,
)

TIER_ORDER = {"BASIC": 0, "STANDARD": 1, "PREMIUM": 2}

LIVE_SUBSCRIPTION_STATUSES = {"TRIALING", "ACTIVE", "PAST_DUE", "PAUSED"}


def refresh_account_balance(account):
    account["outstanding_balance_cents"] = recompute_outstanding_balance_v2(account)
    return account["outstanding_balance_cents"]


def deactivate_account_profiles(account):
    """Cascade: all profiles DEACTIVATED, each touched independently (PRD §2.10)."""
    for p in db.profiles.values():
        if p["account_id"] == account["account_id"] and p["profile_status"] == "ACTIVE":
            p["profile_status"] = "DEACTIVATED"
            touch(p)


def suspend_account(account):
    if account["account_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Account not ACTIVE")
    account["account_status"] = "SUSPENDED"
    touch(account)
    deactivate_account_profiles(account)


def find_account_subscriptions(account_id):
    return [s for s in db.subscriptions.values() if s["account_id"] == account_id]


def live_subscription(account_id):
    for s in find_account_subscriptions(account_id):
        if s["subscription_status"] in LIVE_SUBSCRIPTION_STATUSES:
            return s
    return None


def most_recent_closed_subscription(account_id):
    """Most recent CANCELLED or EXPIRED subscription by updated_at."""
    closed = [s for s in find_account_subscriptions(account_id)
              if s["subscription_status"] in ("CANCELLED", "EXPIRED")]
    if not closed:
        return None
    closed.sort(key=lambda s: (s["updated_at"], s["created_at"]))
    return closed[-1]


def cancel_subscription(sub, reason):
    """Cancel with side effects: supersede offers, clear pending plan."""
    if sub["subscription_status"] in ("CANCELLED", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription already terminal")
    if sub["subscription_status"] not in ("TRIALING", "ACTIVE", "PAUSED", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Cannot cancel from current state")
    sub["subscription_status"] = "CANCELLED"
    sub["cancel_reason"] = reason
    if sub.get("pending_plan_id"):
        sub["pending_plan_id"] = None
    # Supersede any PRESENTED save offers on this subscription
    for offer in db.save_offers.values():
        if offer["subscription_id"] == sub["subscription_id"] and offer["offer_status"] == "PRESENTED":
            offer["offer_status"] = "SUPERSEDED"
            touch(offer)
    touch(sub)
    account = db.accounts.get(sub["account_id"])
    if account and account.get("active_subscription_id") == sub["subscription_id"]:
        account["active_subscription_id"] = None
        touch(account)


def apply_pause(sub, months):
    """ACTIVE → PAUSED with proration credit."""
    now = db.get_now()
    credit = 0
    from services.billing import pause_credit_cents
    credit = pause_credit_cents(sub, now)
    sub["subscription_status"] = "PAUSED"
    sub["paused_until_utc"] = format_ts(add_months(now, months))
    sub["_last_pause_at"] = now_iso()
    touch(sub)
    post_event(sub["account_id"], sub["subscription_id"], "PRORATION_CREDIT", -abs(credit))


def apply_resume(sub):
    """PAUSED → ACTIVE with prorated charge and clawback correction."""
    from services.billing import resume_charge_cents, pause_credit_cents
    now = db.get_now()
    charge = resume_charge_cents(sub, now)
    sub["subscription_status"] = "ACTIVE"
    sub["paused_until_utc"] = None
    touch(sub)
    post_event(sub["account_id"], sub["subscription_id"], "CHARGE", charge)


def apply_plan_change_upgrade(sub, target_plan):
    """Immediate upgrade with proration; clears grandfathered price."""
    from services.billing import proration_components
    now = db.get_now()
    comp = proration_components(sub, target_plan, now)
    sub["plan_id"] = target_plan["plan_id"]
    sub["grandfathered_price_cents"] = None
    touch(sub)
    # Post CHARGE and PRORATION_CREDIT pair
    post_event(sub["account_id"], sub["subscription_id"], "PRORATION_CREDIT",
               -abs(comp["unused_credit_cents"]))
    post_event(sub["account_id"], sub["subscription_id"], "CHARGE",
               comp["prorated_charge_cents"])


def apply_scheduled_downgrade(sub):
    """At period boundary, a pending_plan_id takes effect."""
    if sub.get("pending_plan_id"):
        target = db.plans.get(sub["pending_plan_id"])
        if target:
            sub["plan_id"] = target["plan_id"]
            sub["grandfathered_price_cents"] = None
        sub["pending_plan_id"] = None


def retention_flag(subscription, attribution, days):
    """retained_at_day_N: subscription in live set at attribution.created_at + N days."""
    created = parse_iso(attribution["created_at"])
    boundary = created + timedelta(days=days)
    # The sweep only computes this flag once 'now' reaches the boundary.
    # At that instant, check the subscription's current status.
    if db.get_now() < boundary:
        return None  # not yet due
    return subscription["subscription_status"] in LIVE_SUBSCRIPTION_STATUSES


# ============================ SWEEPS (§2.4) ============================

def run_sweeps():
    """Run all scheduled sweeps in order; returns number of applied transitions.
    Order per PRD §2.4: trial-end conversions, dunning retries, pause expirations,
    price-change effectiveness, save-offer expirations, retention sweeps day 30/90,
    password-sharing reconciliation."""
    applied = 0
    now = db.get_now()

    # 1. Trial-end conversions
    for sub in list(db.subscriptions.values()):
        if sub["subscription_status"] != "TRIALING":
            continue
        trial_end = sub.get("trial_end_utc")
        if not trial_end:
            continue
        if now >= parse_iso(trial_end):
            # First renewal charge. Payment method simulation: account has none
            # stored by default -> trial ends with no valid payment method -> EXPIRED.
            # We model "valid payment method on file" via account attribute set by tests.
            account = db.accounts.get(sub["account_id"])
            has_pm = account.get("_payment_method_token") if account else None
            if not has_pm:
                sub["subscription_status"] = "EXPIRED"
                sub["cancel_reason"] = "PAYMENT_FAILED"
                touch(sub)
                applied += 1
                if account and account.get("active_subscription_id") == sub["subscription_id"]:
                    account["active_subscription_id"] = None
                    touch(account)
            else:
                if payment_will_succeed(has_pm):
                    # TRIALING → ACTIVE, post CHARGE
                    sub["subscription_status"] = "ACTIVE"
                    touch(sub)
                    price = current_price_cents(sub)
                    post_event(sub["account_id"], sub["subscription_id"], "CHARGE", price)
                    applied += 1
                else:
                    # First charge fails -> dunning against the trial (ACTIVE→PAST_DUE
                    # semantics applied to TRIALING: fall to PAST_DUE + DUNNING)
                    sub["subscription_status"] = "PAST_DUE"
                    sub["billing_state"] = "DUNNING"
                    sub["dunning_attempt_count"] = 1
                    sub["_first_failure_at"] = now_iso()
                    touch(sub)
                    post_event(sub["account_id"], sub["subscription_id"],
                               "CHARGE_FAILED", current_price_cents(sub))
                    applied += 1

    # 2. Dunning retries
    for sub in list(db.subscriptions.values()):
        if sub["subscription_status"] != "PAST_DUE" or sub["billing_state"] != "DUNNING":
            continue
        first_failure = sub.get("_first_failure_at")
        if not first_failure:
            continue
        first_failure_dt = parse_iso(first_failure)
        count = sub.get("dunning_attempt_count", 0)
        # Fire every retry whose offset has been reached, in order
        while count < MAX_DUNNING_ATTEMPTS:
            offset_h = DUNNING_RETRY_OFFSETS_HOURS[count]
            retry_at = first_failure_dt + timedelta(hours=offset_h)
            if now >= retry_at:
                # Retry the charge using stored payment method
                account = db.accounts.get(sub["account_id"])
                token = account.get("_payment_method_token") if account else None
                if token and payment_will_succeed(token):
                    # DUNNING → RECOVERED; PAST_DUE → ACTIVE
                    sub["billing_state"] = "RECOVERED"
                    sub["subscription_status"] = "ACTIVE"
                    sub["dunning_attempt_count"] = 0
                    touch(sub)
                    post_event(sub["account_id"], sub["subscription_id"],
                               "RECOVERY", current_price_cents(sub))
                    applied += 1
                    break
                else:
                    count += 1
                    sub["dunning_attempt_count"] = count
                    touch(sub)
                    post_event(sub["account_id"], sub["subscription_id"],
                               "CHARGE_FAILED", current_price_cents(sub))
                    applied += 1
            else:
                break
        # Exhaustion check
        if sub.get("dunning_attempt_count", 0) >= MAX_DUNNING_ATTEMPTS and \
           sub["subscription_status"] == "PAST_DUE":
            sub["subscription_status"] = "EXPIRED"
            sub["cancel_reason"] = "PAYMENT_FAILED"
            touch(sub)
            applied += 1
            account = db.accounts.get(sub["account_id"])
            if account:
                refresh_account_balance(account)
                touch(account)
                if account.get("active_subscription_id") == sub["subscription_id"]:
                    account["active_subscription_id"] = None
                if account["account_status"] == "ACTIVE":
                    account["account_status"] = "SUSPENDED"
                    touch(account)
                    deactivate_account_profiles(account)

    # 3. Pause expirations
    for sub in list(db.subscriptions.values()):
        if sub["subscription_status"] != "PAUSED":
            continue
        paused_until = sub.get("paused_until_utc")
        if paused_until and now >= parse_iso(paused_until):
            apply_resume(sub)
            applied += 1

    # 4. Price-change effectiveness
    for notice in list(db.price_change_notices.values()):
        if notice["notice_status"] != "ANNOUNCED":
            continue
        effective_at = parse_iso(notice["effective_at_utc"])
        if now >= effective_at:
            apply_price_change(notice)
            applied += 1

    # 5. Save-offer expirations
    for offer in list(db.save_offers.values()):
        if offer["offer_status"] != "PRESENTED":
            continue
        if now >= parse_iso(offer["expires_at_utc"]):
            offer["offer_status"] = "EXPIRED"
            touch(offer)
            applied += 1

    # 6. Retention sweeps day+30 / day+90
    for attr in list(db.signup_attributions.values()):
        sub = db.subscriptions.get(attr["subscription_id"])
        if not sub:
            continue
        r30 = retention_flag(sub, attr, 30)
        if r30 is not None and attr.get("retained_at_day_30") != r30:
            attr["retained_at_day_30"] = r30
            touch(attr)
            applied += 1
        r90 = retention_flag(sub, attr, 90)
        if r90 is not None and attr.get("retained_at_day_90") != r90:
            attr["retained_at_day_90"] = r90
            touch(attr)
            applied += 1

    # 7. Password-sharing reconciliation pass — recomputes violation counts;
    # no state to persist on accounts per PRD (enforcement happens at create/
    # reactivate); this pass is a no-op beyond counting as a sweep step.

    return applied


def apply_price_change(notice):
    """ANNOUNCED → EFFECTIVE with grandfathered price carryover (SCAFFOLD §1.3)."""
    plan = db.plans.get(notice["plan_id"])
    announced = parse_iso(notice["announced_at_utc"])
    effective = parse_iso(notice["effective_at_utc"])
    months_since_announce = whole_days(effective, announced) // 30

    notice["notice_status"] = "EFFECTIVE"
    touch(notice)

    if plan:
        plan["monthly_price_cents"] = notice["new_price_cents"]
        touch(plan)

    for sub in db.subscriptions.values():
        if sub["plan_id"] != notice["plan_id"]:
            continue
        if sub["subscription_status"] not in ("TRIALING", "ACTIVE", "PAST_DUE"):
            continue
        old_price_snapshot = notice["old_price_cents"]
        if sub.get("grandfathered_price_cents") is None:
            new_gf = old_price_snapshot if notice["grandfather_period_months"] > 0 else None
        else:
            new_gf = (sub["grandfathered_price_cents"]
                      if months_since_announce < notice["grandfather_period_months"]
                      else None)
        sub["grandfathered_price_cents"] = new_gf
        sub["price_change_notice_id"] = notice["price_change_notice_id"]
        touch(sub)
        post_event(sub["account_id"], sub["subscription_id"],
                   "PRICE_CHANGE_APPLIED", current_price_cents(sub))
