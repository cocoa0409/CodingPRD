"""Entity -> JSON serialization. Each entity exposes exactly the fields the
PRD/scaffold define, with datetimes rendered as ISO 8601 UTC (3 fractional
digits). Internal-only bookkeeping keys (prefixed with '_') are never emitted.
"""
from util import iso

# Datetime-typed fields that must be rendered via iso() per entity.
_DT_FIELDS = {
    "effective_from", "effective_to",
    "period_start", "period_end", "trial_end", "next_retry_at",
    "pause_from", "pause_to", "recorded_at",
    "service_period_start", "service_period_end",
    "created_at", "updated_at",
}


def _render(obj, fields):
    out = {}
    for f in fields:
        if f not in obj:
            continue
        v = obj[f]
        if f in _DT_FIELDS and v is not None and not isinstance(v, str):
            v = iso(v)
        out[f] = v
    return out


COMMON_FULL = ["id", "created_at", "updated_at", "version"]
COMMON_LEAN = ["id", "created_at"]  # UsageRecord only


def ser_plan(o):
    return _render(o, ["id", "tier", "monthly_fee_cents", "included_usage_units",
                       "overage_tiers", "trial_days", "status",
                       "created_at", "updated_at", "version"])


def ser_price_schedule(o):
    return _render(o, ["id", "plan_id", "monthly_fee_cents", "effective_from",
                       "effective_to", "created_at", "updated_at", "version"])


def ser_addon(o):
    return _render(o, ["id", "code", "monthly_fee_cents",
                       "created_at", "updated_at", "version"])


def ser_coupon(o):
    return _render(o, ["id", "code", "discount_type", "percent_off",
                       "amount_off_cents", "duration", "max_redemptions",
                       "redemption_count", "status",
                       "created_at", "updated_at", "version"])


def ser_jurisdiction(o):
    return _render(o, ["id", "region_code", "tax_rate_bps",
                       "created_at", "updated_at", "version"])


def ser_account(o):
    return _render(o, ["id", "email", "company_name", "region_code",
                       "tax_jurisdiction_id", "payment_method_ok", "mrr_cents",
                       "status", "created_at", "updated_at", "version"])


def ser_subscription(o):
    return _render(o, ["id", "account_id", "plan_id", "coupon_id",
                       "period_start", "period_end", "trial_end",
                       "lifecycle_status", "billing_status", "dunning_attempt",
                       "next_retry_at", "mrr_contribution_cents",
                       "created_at", "updated_at", "version"])


def ser_subscription_addon(o):
    return _render(o, ["id", "subscription_id", "addon_id", "status",
                       "created_at", "updated_at", "version"])


def ser_pause_window(o):
    return _render(o, ["id", "subscription_id", "pause_from", "pause_to",
                       "status", "created_at", "updated_at", "version"])


def ser_usage_record(o):
    # Lean entity: only id and created_at (PRD §2.4). Domain fields still shown.
    return _render(o, ["id", "subscription_id", "units", "recorded_at",
                       "billed", "created_at"])


def ser_invoice(o):
    return _render(o, ["id", "account_id", "subscription_id", "coupon_id",
                       "tax_jurisdiction_id", "subtotal_cents", "discount_cents",
                       "tax_cents", "total_cents", "amount_paid_cents",
                       "period_start", "period_end", "status",
                       "created_at", "updated_at", "version"])


def ser_invoice_line(o):
    return _render(o, ["id", "invoice_id", "kind", "description", "amount_cents",
                       "created_at", "updated_at", "version"])


def ser_payment(o):
    return _render(o, ["id", "invoice_id", "amount_cents", "attempt_number",
                       "status", "created_at", "updated_at", "version"])


def ser_revenue_entry(o):
    # recognized_to_date_cents is computed at read time and injected by caller.
    return _render(o, ["id", "invoice_id", "subscription_id",
                       "service_period_start", "service_period_end",
                       "total_recognizable_cents", "recognized_to_date_cents",
                       "created_at", "updated_at", "version"])
