"""Entity → dict (JSON) projections.

PRD §2.4 — every resource exposes `id`, `created_at`, `updated_at`,
`version` except for the two append-only audit entities
(`KYCSubmission`, `DayTrade`) which carry only `id` and `created_at`.
Each serializer here owns the field order and the timestamp formatting
for its entity so route handlers never reach into raw dicts.
"""
from __future__ import annotations

from utils import iso_utc


def _ts(dt):
    return iso_utc(dt) if dt is not None else None


def customer_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "date_of_birth": c["date_of_birth"],
        "ssn_last4": c["ssn_last4"],
        "annual_income_cents": c["annual_income_cents"],
        "liquid_net_worth_cents": c["liquid_net_worth_cents"],
        "total_net_worth_cents": c["total_net_worth_cents"],
        "years_options_experience": c["years_options_experience"],
        "kyc_status": c["kyc_status"],
        "w9_collected": c["w9_collected"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def account_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "account_type": a["account_type"],
        "status": a["status"],
        "trading_posture": a["trading_posture"],
        "options_level": a["options_level"],
        "cash_balance_cents": a["cash_balance_cents"],
        "equity_value_cents": a["equity_value_cents"],
        "pdt_flag": a["pdt_flag"],
        "pdt_flagged_at": _ts(a["pdt_flagged_at"]),
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def kyc_submission_view(k: dict) -> dict:
    """Append-only — only id + created_at per PRD §2.4."""
    return {
        "id": k["id"],
        "customer_id": k["customer_id"],
        "government_id_type": k["government_id_type"],
        "government_id_number": k["government_id_number"],
        "address_line1": k["address_line1"],
        "address_country": k["address_country"],
        "w9_signed_name": k["w9_signed_name"],
        "status": k["status"],
        "rejection_reason": k.get("rejection_reason"),
        "created_at": _ts(k["created_at"]),
    }


def options_approval_view(o: dict) -> dict:
    return {
        "id": o["id"],
        "account_id": o["account_id"],
        "requested_level": o["requested_level"],
        "status": o["status"],
        "approved_level": o.get("approved_level"),
        "review_notes": o.get("review_notes"),
        "revision_count": o["revision_count"],
        "created_at": _ts(o["created_at"]),
        "updated_at": _ts(o["updated_at"]),
        "version": o["version"],
    }


def order_view(o: dict) -> dict:
    return {
        "id": o["id"],
        "account_id": o["account_id"],
        "symbol": o["symbol"],
        "instrument_type": o["instrument_type"],
        "option_strategy": o.get("option_strategy"),
        "side": o["side"],
        "order_type": o["order_type"],
        "quantity": o["quantity"],
        "limit_price_cents": o.get("limit_price_cents"),
        "stop_price_cents": o.get("stop_price_cents"),
        "status": o["status"],
        "fill_price_cents": o.get("fill_price_cents"),
        "filled_at": _ts(o.get("filled_at")),
        "opened_for_day_trade": o["opened_for_day_trade"],
        "margin_requirement_cents": o["margin_requirement_cents"],
        "created_at": _ts(o["created_at"]),
        "updated_at": _ts(o["updated_at"]),
        "version": o["version"],
    }


def day_trade_view(d: dict) -> dict:
    """Append-only — id + created_at only."""
    return {
        "id": d["id"],
        "account_id": d["account_id"],
        "symbol": d["symbol"],
        "opening_order_id": d["opening_order_id"],
        "closing_order_id": d["closing_order_id"],
        "trade_date": d["trade_date"],
        "created_at": _ts(d["created_at"]),
    }


def acat_transfer_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "direction": t["direction"],
        "counterparty_brokerage": t["counterparty_brokerage"],
        "counterparty_account_number": t["counterparty_account_number"],
        "requested_value_cents": t["requested_value_cents"],
        "status": t["status"],
        "initiated_at": _ts(t["initiated_at"]),
        "expected_completion_at": _ts(t.get("expected_completion_at")),
        "completed_at": _ts(t.get("completed_at")),
        "business_days_elapsed": t["business_days_elapsed"],
        "created_at": _ts(t["created_at"]),
        "updated_at": _ts(t["updated_at"]),
        "version": t["version"],
    }
