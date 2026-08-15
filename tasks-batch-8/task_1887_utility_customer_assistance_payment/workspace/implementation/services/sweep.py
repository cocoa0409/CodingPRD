"""Daily ops sweep (PRD §3.9): pinned stage order over all accounts.

(1) expire certificates; (2) lapse enrollments; (3) default DPAs;
(4) break DPAs past cure (reversing credits); (5) expire referrals;
(6) recompute protection per account (winter from clock, weather from this
call's inputs); (7) shutoff sync per account (auto-create / block / unblock /
cancel); (8) version bumps only where a field value actually changed.
"""

import db
from db import CLOCK
from services.common import (delinquency_tier, kept_current_active_dpa,
                             open_order, touch_account, adjust_arrearage,
                             due_installment_count, installment_due_date,
                             GRACE_DAYS, CURE_WINDOW_DAYS,
                             SHUTOFF_MIN_ARREARAGE_CENTS, auto_cancel_open_order)
from services.dpa_ops import reverse_posted_credits, recompute_dpa_derived
from services.protection import recompute as protection_recompute

ACCOUNT_WATCH_FIELDS = [
    "arrearage_balance_cents", "arrearage_since", "current_charges_balance_cents",
    "credit_balance_cents", "protection_status", "service_status",
    "reconnection_fee_due_cents", "reconnection_fee_base_cents",
    "reconnection_fee_surcharge_cents", "reconnection_deposit_topup_cents",
    "reconnection_surcharge_applied",
]


def run_sweep(observed_low_f=None, observed_heat_index_f=None):
    today = CLOCK.date()
    tally = {
        "certificates_expired": 0,
        "enrollments_lapsed": 0,
        "dpas_defaulted": 0,
        "dpas_broken": 0,
        "referrals_expired": 0,
        "orders_created": 0,
        "orders_blocked": 0,
        "orders_unblocked": 0,
        "orders_cancelled": 0,
    }

    accounts = sorted(db.accounts.values(), key=lambda a: a["_seq"])
    snapshots = {a["id"]: {f: a[f] for f in ACCOUNT_WATCH_FIELDS} for a in accounts}

    # Stage 1: expire certificates whose effective_to has been reached
    for c in sorted(db.certificates.values(), key=lambda x: x["_seq"]):
        if c["status"] == "ACTIVE" and today >= c["effective_to"]:
            c["status"] = "EXPIRED"
            db.touch(c)
            tally["certificates_expired"] += 1

    # Stage 2: lapse ACTIVE enrollments past recert_due_on
    for e in sorted(db.enrollments.values(), key=lambda x: x["_seq"]):
        if e["status"] == "ACTIVE" and e["recert_due_on"] is not None and today >= e["recert_due_on"]:
            e["status"] = "LAPSED"
            e["lapsed_on"] = today
            db.touch(e)
            tally["enrollments_lapsed"] += 1

    # Stage 3: default ACTIVE DPAs with earliest unsettled installment past grace
    for d in sorted(db.dpas.values(), key=lambda x: x["_seq"]):
        if d["status"] != "ACTIVE" or d["first_installment_due_on"] is None:
            continue
        k = d["installments_settled_count"] + 1
        if k > d["installment_count"]:
            continue
        due_k = installment_due_date(d, k)
        if db.add_days(due_k, GRACE_DAYS) < today:
            d["status"] = "DEFAULTED"
            d["defaulted_on"] = today
            d["missed_payment_count"] += 1
            db.touch(d)
            tally["dpas_defaulted"] += 1

    # Stage 4: break DEFAULTED DPAs past the cure window, reversing credits
    for d in sorted(db.dpas.values(), key=lambda x: x["_seq"]):
        if d["status"] != "DEFAULTED":
            continue
        if d["defaulted_on"] is not None and today > db.add_days(d["defaulted_on"], CURE_WINDOW_DAYS):
            account = db.accounts.get(d["account_id"])
            d["status"] = "BROKEN"
            if account is not None:
                reverse_posted_credits(d, account)
            else:
                recompute_dpa_derived(d)
            db.touch(d)
            tally["dpas_broken"] += 1

    # Stage 5: expire INITIATED referrals older than 60 days
    for r in sorted(db.referrals.values(), key=lambda x: x["_seq"]):
        if r["status"] == "INITIATED" and today > db.add_days(r["initiated_on"], 60):
            r["status"] = "EXPIRED"
            db.touch(r)
            tally["referrals_expired"] += 1

    # Stages 6-7 per account, in account creation order
    for account in accounts:
        # Stage 6: protection recompute + immediate open-order sync
        protection_recompute(account, observed_low_f, observed_heat_index_f, tally)

        # Stage 7: shutoff sync
        if (account["service_status"] == "CONNECTED"
                and delinquency_tier(account) in ("DELINQUENT", "SEVERELY_DELINQUENT")
                and account["arrearage_balance_cents"] >= SHUTOFF_MIN_ARREARAGE_CENTS
                and account["protection_status"] == "UNPROTECTED"
                and kept_current_active_dpa(account["id"]) is None
                and open_order(account["id"]) is None):
            order = {
                "id": db.new_id(),
                "account_id": account["id"],
                "reason": "NONPAYMENT",
                "scheduled_date": db.add_days(today, 15),
                "status": "SCHEDULED",
                "origin": "AUTO",
                "blocked_reason": None,
                "executed_at": None,
            }
            db.stamp_common(order)
            db.shutoff_orders[order["id"]] = order
            account["service_status"] = "DISCONNECT_PENDING"
            tally["orders_created"] += 1

        auto_cancel_open_order(account, tally)

    # Stage 8: version bumps only where a field value actually changed
    for account in accounts:
        before = snapshots[account["id"]]
        if any(account[f] != before[f] for f in ACCOUNT_WATCH_FIELDS):
            touch_account(account)

    return tally
