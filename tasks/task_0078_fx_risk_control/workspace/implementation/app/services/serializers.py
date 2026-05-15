"""Convert internal Decimal-bearing rows into JSON-safe response shapes."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.numeric import round_half_up


def _money(value: Any) -> float:
    if value is None:
        return 0.0
    return float(round_half_up(value, 2))


def _rate(value: Any) -> float:
    if value is None:
        return 0.0
    return float(round_half_up(value, 6))


def _pct(value: Any) -> float:
    if value is None:
        return 0.0
    return float(round_half_up(value, 2))


def trader_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "name": row["name"],
        "desk_code": row["desk_code"],
        "status": row["status"],
    }


def currency_pair_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "code": row["code"],
        "base_ccy": row["base_ccy"],
        "quote_ccy": row["quote_ccy"],
        "mid_rate": _rate(row["mid_rate"]),
        "daily_volatility": _rate(row["daily_volatility"]),
    }


def limit_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "trader_id": row["trader_id"],
        "pair_code": row.get("pair_code"),
        "bucket": row["bucket"],
        "notional_cap_usd": _money(row["notional_cap_usd"]),
        "stop_loss_cap_usd": _money(row["stop_loss_cap_usd"]),
        "temporary_override_usd": _money(row.get("temporary_override_usd", 0)),
        "utilization_usd": _money(row.get("utilization_usd", 0)),
        "utilization_pct": _pct(row.get("utilization_pct", 0)),
    }


def limit_adjustment_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "limit_id": row["limit_id"],
        "requested_delta_usd": _money(row["requested_delta_usd"]),
        "justification": row["justification"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "requester_trader_id": row["requester_trader_id"],
        "approver_user_id": row.get("approver_user_id"),
    }


def trade_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "trader_id": row["trader_id"],
        "pair_code": row["pair_code"],
        "side": row["side"],
        "notional_base": _money(row["notional_base"]),
        "entry_rate": _rate(row["entry_rate"]),
        "executed_at": row["executed_at"],
        "trading_day": row["trading_day"],
        "counterparty_id": row["counterparty_id"],
        "status": row["status"],
    }


def position_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "trader_id": row["trader_id"],
        "pair_code": row["pair_code"],
        "net_base": _money(row.get("net_base", 0)),
        "net_open_usd": _money(row.get("net_open_usd", 0)),
        "mtm_pnl_usd": _money(row.get("mtm_pnl_usd", 0)),
        "warning_status": row.get("warning_status", "NORMAL"),
    }


def stop_loss_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "trader_id": row["trader_id"],
        "pair_code": row["pair_code"],
        "rule_mode": row["rule_mode"],
        "threshold_value": float(row["threshold_value"]) if isinstance(row["threshold_value"], Decimal) else row["threshold_value"],
        "action": row["action"],
        "state": row["state"],
        "triggered_at": row.get("triggered_at"),
        "triggering_value": (
            float(row["triggering_value"])
            if isinstance(row.get("triggering_value"), Decimal)
            else row.get("triggering_value")
        ),
    }


def counterparty_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "name": row["name"],
        "external_rating": row["external_rating"],
        "internal_score": row["internal_score"],
        "rating_band": row["rating_band"],
        "credit_limit_usd": _money(row["credit_limit_usd"]),
        "on_watchlist": row["on_watchlist"],
    }


def settlement_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "counterparty_id": row["counterparty_id"],
        "value_date": row["value_date"],
        "ccy": row["ccy"],
        "gross_pay_amount": _money(row.get("gross_pay_amount", 0)),
        "gross_receive_amount": _money(row.get("gross_receive_amount", 0)),
        "net_amount": _money(row.get("net_amount", 0)),
        "status": row["status"],
        "client_request_id": row["client_request_id"],
        "nostro_balance_delta": _money(row.get("nostro_balance_delta", 0)),
    }


def compliance_report_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "report_type": row["report_type"],
        "reference_trade_id": row.get("reference_trade_id"),
        "version": row["version"],
        "payload": row["payload"],
        "filed_at": row["filed_at"],
        "filed_by_user_id": row["filed_by_user_id"],
    }


def audit_log_dto(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "event_type": row["event_type"],
        "actor_user_id": row["actor_user_id"],
        "actor_role": row["actor_role"],
        "subject_entity": row["subject_entity"],
        "subject_id": row["subject_id"],
        "before_snapshot": row.get("before_snapshot"),
        "after_snapshot": row.get("after_snapshot"),
    }
