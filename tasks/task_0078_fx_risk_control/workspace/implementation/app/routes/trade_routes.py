"""Trade booking — POST /fx-risk/trades."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

from app.auth import require_auth
from app.clock import clock
from app.errors import make_error
from app.numeric import to_decimal, round_half_up, ZERO
from app.responses import success_object
from app.services import positions as positions_service
from app.services.compliance import LARGE_TRADE_THRESHOLD_USD, file_report
from app.services.fx import base_in_usd_rate
from app.services.serializers import trade_dto
from app.store import store, new_id, now_iso
from app.validation import (
    get_json_body,
    require_decimal,
    require_enum,
    require_str,
)


bp = Blueprint("trades", __name__, url_prefix="/fx-risk")

VALID_SIDES = {"BUY", "SELL"}


@bp.route("/trades", methods=["POST"])
@require_auth(["Trader"])
def book_trade():
    with store.lock:
        body = get_json_body()
        pair_code = require_str(body, "pair_code")
        side = require_enum(body, "side", VALID_SIDES)
        notional_base = require_decimal(body, "notional_base", gt=ZERO)
        entry_rate = require_decimal(body, "entry_rate", gt=ZERO)
        counterparty_id = require_str(body, "counterparty_id")

        # Existence checks (NOT_FOUND for referenced resources)
        pair_id = store.pair_index_by_code.get(pair_code)
        if pair_id is None:
            raise make_error("ERR_NOT_FOUND", "Currency pair not found.")
        counterparty = store.counterparties.get(counterparty_id)
        if counterparty is None:
            raise make_error("ERR_NOT_FOUND", "Counterparty not found.")
        trader = store.traders.get(g.user_id)
        if trader is None:
            raise make_error("ERR_NOT_FOUND", "Trader not found.")

        # Trader status + counterparty watchlist gate
        if trader["status"] != "ACTIVE":
            raise make_error("ERR_TRADER_SUSPENDED")
        if counterparty.get("on_watchlist"):
            raise make_error("ERR_TRADER_SUSPENDED",
                             "Counterparty is on the watchlist.")

        # Pre-flight: per-bucket limit check
        trading_day = clock.today_iso_date()
        executed_at = clock.now_iso()
        # Determine which buckets the trade contributes to
        now_dt = clock.now()
        trade_bucket = "OVERNIGHT" if now_dt.hour >= 17 else "INTRADAY"

        # For every Limit that gates this trade (either the same pair or aggregate)
        # in either bucket, project utilisation and reject on breach.
        relevant_limits = [
            l for l in store.limits.values()
            if l["trader_id"] == g.user_id
            and (l.get("pair_code") in (None, pair_code))
        ]
        for limit in relevant_limits:
            bucket = limit["bucket"]
            # Aggregate across all pairs that contribute to this limit.
            pair_codes_in_scope: list[str]
            if limit.get("pair_code") is None:
                pair_codes_in_scope = sorted({k[1] for k in store.position_index.keys() if k[0] == g.user_id} | {pair_code})
            else:
                pair_codes_in_scope = [limit["pair_code"]]
            # Compute projected utilization by recomputing each pair's bucket exposure.
            total_usd = ZERO
            for code in pair_codes_in_scope:
                if code == pair_code:
                    total_usd = total_usd + positions_service.projected_bucket_usd_with_trade(
                        store, g.user_id, code, side, notional_base, bucket, trading_day,
                        simulated_executed_at=executed_at,
                    )
                else:
                    total_usd = total_usd + abs(
                        positions_service._bucket_position_usd(  # type: ignore[attr-defined]
                            store, g.user_id, code, bucket, trading_day,
                        )
                    )
            cap = to_decimal(limit["notional_cap_usd"]) + to_decimal(limit.get("temporary_override_usd") or 0)
            if total_usd > cap:
                raise make_error("ERR_LIMIT_BREACH")

        # Counterparty credit-limit pre-flight
        pair = store.currency_pairs[pair_id]
        rate_usd_per_base = base_in_usd_rate(store, pair)
        trade_notional_usd = round_half_up(notional_base * rate_usd_per_base, 2)
        current_facing = positions_service.aggregate_counterparty_facing_usd(
            store, counterparty_id,
        )
        projected_cp = current_facing + abs(trade_notional_usd)
        if projected_cp > to_decimal(counterparty["credit_limit_usd"]):
            raise make_error("ERR_COUNTERPARTY_LIMIT_BREACH")

        # Persist
        trade = {
            "id": new_id(),
            "created_at": executed_at,
            "trader_id": g.user_id,
            "pair_code": pair_code,
            "side": side,
            "notional_base": notional_base,
            "entry_rate": entry_rate,
            "executed_at": executed_at,
            "trading_day": trading_day,
            "counterparty_id": counterparty_id,
            "status": "BOOKED",
        }
        store.trades[trade["id"]] = trade

        # Cascade: recompute the position then limits + warning_status
        positions_service.recompute_position(store, g.user_id, pair_code, trading_day)
        positions_service.recompute_warning_status_for_trader(store, g.user_id, trading_day)

        # Large-trade compliance report
        if abs(trade_notional_usd) >= Decimal(LARGE_TRADE_THRESHOLD_USD):
            file_report(
                store,
                report_type="LARGE_TRADE",
                reference_trade_id=trade["id"],
                payload={
                    "trader_id": g.user_id,
                    "pair_code": pair_code,
                    "notional_usd": float(trade_notional_usd),
                    "counterparty_id": counterparty_id,
                    "narrative": "Trade USD notional crossed the LARGE_TRADE threshold.",
                },
                filed_by_user_id="SYSTEM",
            )

        store.audit(
            event_type="TRADE_BOOKED",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="Trade",
            subject_id=trade["id"],
            before_snapshot=None,
            after_snapshot={
                "pair_code": pair_code,
                "side": side,
                "notional_base": float(notional_base),
                "entry_rate": float(entry_rate),
                "counterparty_id": counterparty_id,
                "notional_usd": float(trade_notional_usd),
            },
        )
        return success_object(trade_dto(trade), status=201)
