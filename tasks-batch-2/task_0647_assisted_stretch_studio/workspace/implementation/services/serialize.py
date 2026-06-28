"""Resource serialization: project stored records into API representations.

Computed wallet/strike fields are reconciled at read time so GETs always
reflect current derived state (PRD §2.6).
"""
from services.wallet import (
    membership_wallet_fields,
    creditpack_wallet_fields,
)

# Common system fields carried by the "full" resources (PRD §2.4).
_FULL_COMMON = ["id", "created_at", "updated_at", "version"]
# Lean resources carry only id + created_at (PRD §2.4).
_LEAN_COMMON = ["id", "created_at"]


def _base(record, fields):
    return {k: record.get(k) for k in fields}


def location_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["name", "timezone", "open_minute_of_day", "close_minute_of_day",
              "flexologist_buffer_minutes", "no_show_fee_cents", "late_cancel_pct",
              "cancel_window_hours", "status"]:
        out[k] = r.get(k)
    return out


def flexologist_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["location_id", "full_name", "certified_intro", "status"]:
        out[k] = r.get(k)
    return out


def table_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["location_id", "label", "status"]:
        out[k] = r.get(k)
    return out


def service_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["location_id", "name", "kind", "duration_minutes", "credit_cost",
              "list_price_cents", "status"]:
        out[k] = r.get(k)
    return out


def member_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["home_location_id", "full_name", "email", "intro_completed",
              "mobility_tier", "strike_score", "status"]:
        out[k] = r.get(k)
    return out


def membership_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["member_id", "location_id", "tier", "monthly_fee_cents",
              "included_credits", "rollover_cap", "cycle_anchor_utc", "status",
              "freeze_credit_cents"]:
        out[k] = r.get(k)
    wallet = membership_wallet_fields(r)
    out["granted_credits"] = wallet["granted_credits"]
    out["held_credits"] = wallet["held_credits"]
    out["consumed_credits"] = wallet["consumed_credits"]
    out["available_credits"] = wallet["available_credits"]
    return out


def creditpack_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["member_id", "location_id", "pack_credits", "base_unit_price_cents",
              "price_cents", "expires_utc", "status"]:
        out[k] = r.get(k)
    wallet = creditpack_wallet_fields(r)
    out["held_credits"] = wallet["held_credits"]
    out["consumed_credits"] = wallet["consumed_credits"]
    out["available_credits"] = wallet["available_credits"]
    return out


def booking_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["member_id", "location_id", "service_id", "flexologist_id",
              "table_id", "series_id", "rescheduled_from_booking_id",
              "session_start_utc", "session_end_utc", "funding_source",
              "funding_id", "credit_cost", "list_price_cents", "schedule_status",
              "credit_status", "fee_charged_cents", "is_intro"]:
        out[k] = r.get(k)
    return out


def series_view(r):
    out = _base(r, _FULL_COMMON)
    for k in ["member_id", "location_id", "service_id", "flexologist_id",
              "table_id", "funding_source", "funding_id", "first_start_utc",
              "interval_days", "occurrence_count", "generated_count",
              "skipped_count", "status"]:
        out[k] = r.get(k)
    return out


def addon_view(r):
    out = _base(r, _LEAN_COMMON)
    for k in ["booking_id", "kind", "price_cents", "voided"]:
        out[k] = r.get(k)
    return out


def noshow_view(r):
    out = _base(r, _LEAN_COMMON)
    for k in ["member_id", "booking_id", "event_kind", "points", "occurred_utc"]:
        out[k] = r.get(k)
    return out


def clock_view(r):
    out = _base(r, _LEAN_COMMON)
    out["current_utc"] = r.get("current_utc")
    return out
