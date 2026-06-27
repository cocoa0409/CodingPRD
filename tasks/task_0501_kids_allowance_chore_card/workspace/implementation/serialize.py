"""Resource serializers — produce the public JSON shape for each entity.

is_teen is recomputed at serialization time (PRD §3.2: recomputed on every read).
Computed card fields (held_cents, available_cents, funding_state) are kept
up to date by the services, so serialization just copies them.
"""
import db


def _common(rec, fields):
    out = {"id": rec["id"]}
    for f in fields:
        out[f] = rec.get(f)
    out["created_at"] = rec.get("created_at")
    if "updated_at" in rec:
        out["updated_at"] = rec.get("updated_at")
    if "version" in rec:
        out["version"] = rec.get("version")
    return out


def family(rec):
    return _common(rec, [
        "family_name", "primary_parent_id", "funding_balance_cents", "status",
        "large_spend_threshold_cents", "low_balance_threshold_cents",
    ])


def child_account(rec):
    out = _common(rec, ["family_id", "display_name", "birthdate", "status"])
    out["is_teen"] = db.compute_is_teen(rec)
    return out


def jar(rec):
    return _common(rec, [
        "child_account_id", "jar_type", "balance_cents", "lifetime_credited_cents",
    ])


def chore(rec):
    return _common(rec, [
        "child_account_id", "title", "reward_cents", "payout_jar_type",
        "is_recurring", "status",
    ])


def chore_completion(rec):
    return _common(rec, [
        "chore_id", "child_account_id", "reward_cents_snapshot",
        "payout_jar_type_snapshot", "revision_count", "status",
    ])


def debit_card(rec):
    return _common(rec, [
        "child_account_id", "lock_state", "funding_state", "held_cents",
        "available_cents",
    ])


def card_control(rec):
    return _common(rec, [
        "debit_card_id", "control_kind", "match_value", "rule",
        "per_period_cap_cents", "is_active",
    ])


def transaction(rec):
    return _common(rec, [
        "debit_card_id", "child_account_id", "merchant_id", "category",
        "amount_cents", "settled_amount_cents", "status",
    ])


def allowance_schedule(rec):
    return _common(rec, [
        "child_account_id", "amount_cents", "payout_jar_type", "cadence_days",
        "next_run_at", "status",
    ])


def allowance_run(rec):
    return _common(rec, [
        "allowance_schedule_id", "amount_cents", "ran_at", "outcome",
    ])


def interest_match_config(rec):
    return _common(rec, [
        "child_account_id", "annual_rate_bps", "monthly_cap_cents",
        "accrual_method", "status",
    ])


def interest_accrual(rec):
    return _common(rec, [
        "interest_match_config_id", "child_account_id", "period_days",
        "period_start_at", "matched_cents", "accrued_at",
    ])


def investment_account(rec):
    return _common(rec, ["child_account_id", "cash_cents", "holdings", "status"])


def investment_order(rec):
    return _common(rec, [
        "investment_account_id", "side", "symbol", "shares_milli",
        "price_cents_per_share", "gross_cents", "status",
    ])


def spend_alert(rec):
    # SpendAlert is leaner: id + created_at only, plus its data fields.
    out = {"id": rec["id"], "created_at": rec.get("created_at")}
    for f in ["transaction_id", "child_account_id", "alert_kind", "amount_cents"]:
        out[f] = rec.get(f)
    return out
