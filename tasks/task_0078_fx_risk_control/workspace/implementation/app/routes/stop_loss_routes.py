"""Stop-loss rule lifecycle."""
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
from app.services.serializers import stop_loss_dto
from app.services.stop_loss import evaluate_rule
from app.store import store, new_id, now_iso
from app.validation import get_json_body, require_decimal, require_enum, require_str


bp = Blueprint("stop_loss", __name__, url_prefix="/fx-risk")

VALID_MODES = {"PRICE", "LOSS_AMOUNT", "LOSS_RATIO"}
VALID_ACTIONS = {"ALERT", "FORCED_FLATTEN"}


@bp.route("/stop-loss", methods=["POST"])
@require_auth(["RiskOfficer"])
def create_stop_loss():
    with store.lock:
        body = get_json_body()
        trader_id = require_str(body, "trader_id")
        pair_code = require_str(body, "pair_code")
        # Mode/threshold use ERR_INVALID_STOPLOSS_MODE for the narrower failure.
        mode = body.get("rule_mode")
        if mode not in VALID_MODES:
            raise make_error("ERR_INVALID_STOPLOSS_MODE")
        if "threshold_value" not in body or body["threshold_value"] is None:
            raise make_error("ERR_INVALID_STOPLOSS_MODE")
        try:
            threshold = to_decimal(body["threshold_value"])
        except Exception:
            raise make_error("ERR_INVALID_STOPLOSS_MODE")
        if threshold <= ZERO:
            raise make_error("ERR_INVALID_STOPLOSS_MODE")
        action = require_enum(body, "action", VALID_ACTIONS)
        if trader_id not in store.traders:
            raise make_error("ERR_NOT_FOUND")
        if pair_code not in store.pair_index_by_code:
            raise make_error("ERR_NOT_FOUND")
        meta = store.stamp_common(create=True)
        row = {
            **meta,
            "trader_id": trader_id,
            "pair_code": pair_code,
            "rule_mode": mode,
            "threshold_value": threshold,
            "action": action,
            "state": "ARMED",
            "triggered_at": None,
            "triggering_value": None,
        }
        store.stop_loss_events[row["id"]] = row
        return success_object(stop_loss_dto(row), status=201)


def _load_event(event_id: str) -> dict:
    event = store.stop_loss_events.get(event_id)
    if event is None:
        raise make_error("ERR_NOT_FOUND")
    return event


@bp.route("/stop-loss/<event_id>/evaluate", methods=["POST"])
@require_auth(["RiskOfficer", "MarketDataSystem"])
def evaluate_stop_loss(event_id: str):
    with store.lock:
        event = _load_event(event_id)
        if event["state"] != "ARMED":
            return success_object(stop_loss_dto(event))
        observed = evaluate_rule(store, event)
        if observed is None:
            return success_object(stop_loss_dto(event))
        before = {"state": "ARMED"}
        event["state"] = "TRIGGERED"
        event["triggered_at"] = now_iso()
        event["triggering_value"] = observed
        event["updated_at"] = now_iso()
        event["version"] = event["version"] + 1
        store.audit(
            event_type="STOP_LOSS_TRIGGERED",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="StopLossEvent",
            subject_id=event["id"],
            before_snapshot=before,
            after_snapshot={"state": "TRIGGERED",
                            "triggered_at": event["triggered_at"],
                            "triggering_value": float(observed)},
        )
        return success_object(stop_loss_dto(event))


@bp.route("/stop-loss/<event_id>/acknowledge", methods=["POST"])
@require_auth(["Trader"])
def acknowledge_stop_loss(event_id: str):
    with store.lock:
        event = _load_event(event_id)
        if event["state"] != "TRIGGERED":
            raise make_error("ERR_INVALID_STATE")
        if g.user_id != event["trader_id"]:
            raise make_error("ERR_FORBIDDEN")
        trader = store.traders.get(event["trader_id"])
        if trader is None or trader["status"] != "ACTIVE":
            raise make_error("ERR_TRADER_SUSPENDED")
        before = {"state": "TRIGGERED"}
        event["state"] = "ACKNOWLEDGED"
        event["updated_at"] = now_iso()
        event["version"] = event["version"] + 1
        store.audit(
            event_type="STOP_LOSS_OVERRIDDEN",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="StopLossEvent",
            subject_id=event["id"],
            before_snapshot=before,
            after_snapshot={"state": "ACKNOWLEDGED"},
        )
        return success_object(stop_loss_dto(event))


@bp.route("/stop-loss/<event_id>/override", methods=["POST"])
@require_auth(["RiskOfficer"])
def override_stop_loss(event_id: str):
    with store.lock:
        event = _load_event(event_id)
        if event["state"] != "ACKNOWLEDGED":
            raise make_error("ERR_INVALID_STATE")
        if g.user_id == event["trader_id"]:
            raise make_error("ERR_SEGREGATION_VIOLATION")
        before = {"state": "ACKNOWLEDGED"}
        event["state"] = "OVERRIDDEN"
        event["updated_at"] = now_iso()
        event["version"] = event["version"] + 1
        store.audit(
            event_type="STOP_LOSS_OVERRIDDEN",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="StopLossEvent",
            subject_id=event["id"],
            before_snapshot=before,
            after_snapshot={"state": "OVERRIDDEN"},
        )
        return success_object(stop_loss_dto(event))


@bp.route("/stop-loss/<event_id>/execute", methods=["POST"])
@require_auth(["RiskOfficer"])
def execute_stop_loss(event_id: str):
    with store.lock:
        event = _load_event(event_id)
        if event["state"] != "TRIGGERED":
            raise make_error("ERR_INVALID_STATE")
        if event["action"] != "FORCED_FLATTEN":
            raise make_error("ERR_INVALID_STATE", "Only FORCED_FLATTEN rules can execute.")
        if g.user_id == event["trader_id"]:
            raise make_error("ERR_SEGREGATION_VIOLATION")

        trader_id = event["trader_id"]
        pair_code = event["pair_code"]
        pair_id = store.pair_index_by_code.get(pair_code)
        if pair_id is None:
            raise make_error("ERR_NOT_FOUND")
        pair = store.currency_pairs[pair_id]
        position_id = store.position_index.get((trader_id, pair_code))
        position = store.positions.get(position_id) if position_id else None
        net_base = to_decimal(position["net_base"]) if position else ZERO

        # Book an offsetting trade that flattens net_base to zero.
        if net_base != 0:
            offset_side = "SELL" if net_base > 0 else "BUY"
            offset_notional = abs(net_base)
            trading_day = clock.today_iso_date()
            executed_at = clock.now_iso()
            trade = {
                "id": new_id(),
                "created_at": executed_at,
                "trader_id": trader_id,
                "pair_code": pair_code,
                "side": offset_side,
                "notional_base": offset_notional,
                "entry_rate": to_decimal(pair["mid_rate"]),
                "executed_at": executed_at,
                "trading_day": trading_day,
                "counterparty_id": "FORCED_FLATTEN",
                "status": "BOOKED",
            }
            store.trades[trade["id"]] = trade
            positions_service.recompute_position(store, trader_id, pair_code, trading_day)
            positions_service.recompute_warning_status_for_trader(store, trader_id, trading_day)
            rate = base_in_usd_rate(store, pair)
            notional_usd = round_half_up(offset_notional * rate, 2)
            if notional_usd >= Decimal(LARGE_TRADE_THRESHOLD_USD):
                file_report(
                    store,
                    report_type="LARGE_TRADE",
                    reference_trade_id=trade["id"],
                    payload={
                        "trader_id": trader_id,
                        "pair_code": pair_code,
                        "notional_usd": float(notional_usd),
                        "counterparty_id": "FORCED_FLATTEN",
                        "narrative": "Forced-flatten offsetting trade crossed the LARGE_TRADE threshold.",
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
                    "side": offset_side,
                    "notional_base": float(offset_notional),
                    "notional_usd": float(notional_usd),
                    "via": "FORCED_FLATTEN",
                },
            )

        before = {"state": "TRIGGERED"}
        event["state"] = "EXECUTED"
        event["updated_at"] = now_iso()
        event["version"] = event["version"] + 1
        store.audit(
            event_type="STOP_LOSS_OVERRIDDEN",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="StopLossEvent",
            subject_id=event["id"],
            before_snapshot=before,
            after_snapshot={"state": "EXECUTED"},
        )
        return success_object(stop_loss_dto(event))
