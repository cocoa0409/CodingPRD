"""Serialize internal records to API JSON.

Datetime fields are formatted to ISO8601 UTC (3 fractional digits); internal
bookkeeping fields (prefixed with '_') are stripped. Each entity has an
explicit field list so output is stable and contains exactly the declared
columns plus the common fields.
"""
from util import format_iso

# Datetime-typed fields per entity that must be ISO-formatted on output.
_DT_FIELDS = {
    "created_at", "updated_at", "adjudicated_at",
    "scheduled_start", "scheduled_end", "next_occurrence_date",
}


def _fmt(record, fields):
    out = {}
    for f in fields:
        val = record.get(f)
        if f in _DT_FIELDS:
            out[f] = format_iso(val) if val is not None else None
        else:
            out[f] = val
    return out


_COMMON = ["id", "created_at", "updated_at", "version"]
_APPEND_ONLY_COMMON = ["id", "created_at"]


def customer(r):
    return _fmt(r, ["email", "full_name", "wallet_credit_cents",
                    "lifetime_booking_count"] + _COMMON)


def address(r):
    return _fmt(r, ["customer_id", "line1", "postal_code", "home_size",
                    "archived"] + _COMMON)


def cleaner(r):
    return _fmt(r, ["email", "full_name", "service_postal_codes", "status",
                    "rating_sum", "rating_count", "completed_job_count"] + _COMMON)


def background_check(r):
    return _fmt(r, ["cleaner_id", "provider_ref", "result",
                    "adjudicated_at"] + _COMMON)


def pricing_plan(r):
    return _fmt(r, ["name", "base_price_cents", "deep_clean_surcharge_pct",
                    "move_out_surcharge_pct", "supplies_fee_cents",
                    "active"] + _COMMON)


def booking_series(r):
    return _fmt(r, ["customer_id", "address_id", "pricing_plan_id", "cadence",
                    "add_ons", "supplies_provided_by", "preferred_cleaner_id",
                    "status", "next_occurrence_date"] + _COMMON)


def booking(r):
    return _fmt(r, ["customer_id", "address_id", "pricing_plan_id", "series_id",
                    "cleaner_id", "scheduled_start", "scheduled_end",
                    "home_size", "add_ons", "supplies_provided_by", "status",
                    "quoted_price_cents", "change_fee_cents", "is_reclean",
                    "reclean_of_booking_id"] + _COMMON)


def preferred_pro(r):
    return _fmt(r, ["customer_id", "cleaner_id", "priority"] + _COMMON)


def tip(r):
    return _fmt(r, ["booking_id", "customer_id", "cleaner_id",
                    "amount_cents"] + _APPEND_ONLY_COMMON)


def cleaner_payout(r):
    return _fmt(r, ["cleaner_id", "booking_id", "base_payout_cents",
                    "tip_cents", "total_cents"] + _COMMON)


def ledger_entry(r):
    return _fmt(r, ["customer_id", "booking_id", "kind",
                    "amount_cents"] + _APPEND_ONLY_COMMON)
