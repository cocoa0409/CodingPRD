"""Domain lookups, denormalised mirrors and the trailing-metric recomputation."""
from db import by_seq, db
from middleware import touch
from util import date_minus, rhu_div

PENDING_STATES = ("SCHEDULED", "DELAYED", "HELD")
OPEN_ALERT_STATES = ("OPEN", "UNDER_REVIEW", "ESCALATED")


# --------------------------------------------------------------------------
# collection lookups
# --------------------------------------------------------------------------
def merchant_activity(merchant_id):
    return [r for r in db.day_activity.values() if r["merchant_id"] == merchant_id]


def activity_between(merchant_id, start_date, end_date):
    """Inclusive on both bounds; ISO dates compare correctly as strings."""
    return [
        r for r in merchant_activity(merchant_id)
        if start_date <= r["business_date"] <= end_date
    ]


def merchant_batches(merchant_id):
    return [b for b in db.batches.values() if b["merchant_id"] == merchant_id]


def batches_cascade_order(merchant_id, states):
    """period_end_date ASC, ties broken by created_at ASC (PRD 2.8)."""
    rows = [b for b in merchant_batches(merchant_id) if b["payout_state"] in states]
    return sorted(rows, key=lambda b: (b["period_end_date"], b["_seq"]))


def merchant_alerts(merchant_id):
    return by_seq([a for a in db.alerts.values() if a["merchant_id"] == merchant_id])


def reserve_account_of(merchant_id):
    for acct in by_seq(list(db.reserve_accounts.values())):
        if acct["merchant_id"] == merchant_id:
            return acct
    return None


def ledger_of_account(account_id):
    return by_seq([e for e in db.ledger_entries.values() if e["reserve_account_id"] == account_id])


def programs_of(merchant_id):
    return by_seq([p for p in db.programs.values() if p["merchant_id"] == merchant_id])


def terminations_of(merchant_id):
    return by_seq([t for t in db.terminations.values() if t["merchant_id"] == merchant_id])


def appeals_of_merchant(merchant_id):
    return by_seq([a for a in db.appeals.values() if a["merchant_id"] == merchant_id])


def owners_of(application_id):
    return by_seq([o for o in db.owners.values() if o["application_id"] == application_id])


def verifications_of(application_id):
    rows = [v for v in db.verifications.values() if v["application_id"] == application_id]
    return sorted(rows, key=lambda v: v["attempt_index"])


def assessments_of(application_id):
    rows = [a for a in db.assessments.values() if a["application_id"] == application_id]
    return sorted(rows, key=lambda a: a["assessment_sequence"])


def merchant_of_application(application_id):
    for m in by_seq(list(db.merchants.values())):
        if m["application_id"] == application_id:
            return m
    return None


def rule_for_mcc(mcc_code):
    for rule in by_seq(list(db.category_rules.values())):
        if rule["mcc_code"] == mcc_code:
            return rule
    return None


def active_book():
    """Merchants in the monitoring / forecasting input set, created_at ASC."""
    rows = [m for m in db.merchants.values() if m["account_state"] in ("ACTIVE", "RESTRICTED")]
    return by_seq(rows)


# --------------------------------------------------------------------------
# ratios and trailing metrics (PRD 3.6)
# --------------------------------------------------------------------------
def ratio_bps(numerator, denominator):
    if denominator == 0:
        return 0
    return rhu_div(numerator * 10000, denominator)


def window_totals(merchant_id, w_end):
    w_start = date_minus(w_end, 29)
    rows = activity_between(merchant_id, w_start, w_end)
    return {
        "txn_count": sum(r["txn_count"] for r in rows),
        "volume_cents": sum(r["volume_cents"] for r in rows),
        "chargeback_count": sum(r["chargeback_count"] for r in rows),
        "chargeback_amount_cents": sum(r["chargeback_amount_cents"] for r in rows),
    }


def recompute_trailing_metrics(merchant, w_end):
    totals = window_totals(merchant["id"], w_end)
    merchant["trailing_30d_txn_count"] = totals["txn_count"]
    merchant["trailing_30d_volume_cents"] = totals["volume_cents"]
    merchant["trailing_30d_chargeback_count"] = totals["chargeback_count"]
    merchant["trailing_30d_chargeback_amount_cents"] = totals["chargeback_amount_cents"]
    merchant["rolling_chargeback_ratio_bps"] = ratio_bps(
        totals["chargeback_count"], totals["txn_count"])
    merchant["amount_based_chargeback_ratio_bps"] = ratio_bps(
        totals["chargeback_amount_cents"], totals["volume_cents"])
    merchant["metrics_as_of_date"] = w_end
    touch(merchant)
    return merchant


def trailing_volume_at(merchant_id, w_end):
    return window_totals(merchant_id, w_end)["volume_cents"]


# --------------------------------------------------------------------------
# denormalised mirrors (PRD 2.8)
# --------------------------------------------------------------------------
def recompute_pending_payout(merchant):
    merchant["pending_payout_cents"] = sum(
        b["net_payout_cents"] for b in merchant_batches(merchant["id"])
        if b["payout_state"] in PENDING_STATES
    )
    touch(merchant)


def recompute_open_alert_count(merchant):
    merchant["open_alert_count"] = sum(
        1 for a in merchant_alerts(merchant["id"]) if a["state"] in OPEN_ALERT_STATES
    )
    touch(merchant)


def recompute_reserve_totals(account):
    entries = ledger_of_account(account["id"])
    account["total_accrued_cents"] = sum(
        e["amount_cents"] for e in entries if e["entry_type"] == "HOLD")
    account["released_to_date_cents"] = sum(
        e["amount_cents"] for e in entries if e["entry_type"] == "RELEASE")
    account["offset_to_date_cents"] = sum(
        e["amount_cents"] for e in entries if e["entry_type"] == "OFFSET_LOSS")
    account["held_balance_cents"] = (
        account["total_accrued_cents"]
        - account["released_to_date_cents"]
        - account["offset_to_date_cents"]
    )
    touch(account)
    return account


def mirror_reserve_balance(merchant, account):
    merchant["reserve_balance_cents"] = account["held_balance_cents"] if account else 0
    touch(merchant)


def releasable_balance(account, clock_date):
    """PRD 3.10 maturity-derived releasable balance."""
    if account is None or account["state"] == "CLOSED":
        return 0
    cutoff = date_minus(clock_date, account["release_lag_days"])
    matured = sum(
        e["amount_cents"] for e in ledger_of_account(account["id"])
        if e["entry_type"] == "HOLD" and e["effective_date"] <= cutoff
    )
    candidate = matured - account["released_to_date_cents"] - account["offset_to_date_cents"]
    return max(0, min(account["held_balance_cents"], candidate))


def prior_scheduled_release(account_id):
    """RELEASE/SCHEDULED_RELEASE entry with the greatest effective_date, latest wins."""
    candidates = [
        e for e in ledger_of_account(account_id)
        if e["entry_type"] == "RELEASE" and e["reason_code"] == "SCHEDULED_RELEASE"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda e: (e["effective_date"], e["_seq"]))[-1]


def unpaid_exposure(merchant_id):
    return sum(
        b["net_payout_cents"] for b in merchant_batches(merchant_id)
        if b["payout_state"] in PENDING_STATES
    )
