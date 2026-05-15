"""Settlement instruction lifecycle."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

from app.auth import require_auth
from app.clock import clock
from app.errors import make_error
from app.numeric import to_decimal, ZERO
from app.responses import success_array, success_object
from app.services.counterparty import recompute_counterparty
from app.services.fx import base_in_usd_rate
from app.services.serializers import settlement_dto
from app.services.settlement import (
    generate_for_counterparty,
    linked_trades_for_instruction,
)
from app.services import positions as positions_service
from app.store import store
from app.validation import get_json_body, require_str


bp = Blueprint("settlements", __name__, url_prefix="/fx-risk")


@bp.route("/settlements/generate", methods=["POST"])
@require_auth(["SettlementOperator"])
def generate_settlements():
    with store.lock:
        body = get_json_body()
        counterparty_id = require_str(body, "counterparty_id")
        value_date = require_str(body, "value_date")
        client_request_id = require_str(body, "client_request_id")
        if counterparty_id not in store.counterparties:
            raise make_error("ERR_NOT_FOUND")
        rows, is_replay = generate_for_counterparty(
            store,
            counterparty_id=counterparty_id,
            value_date=value_date,
            client_request_id=client_request_id,
        )
        status = 200 if is_replay else 201
        return success_array(
            [settlement_dto(r) for r in rows],
            limit=len(rows) if rows else 10,
            offset=0,
            total_count=len(rows),
            status=status,
        )


def _load_instruction(instruction_id: str) -> dict:
    instr = store.settlement_instructions.get(instruction_id)
    if instr is None:
        raise make_error("ERR_NOT_FOUND")
    return instr


@bp.route("/settlements/<instruction_id>/send", methods=["POST"])
@require_auth(["SettlementOperator"])
def send_instruction(instruction_id: str):
    with store.lock:
        instr = _load_instruction(instruction_id)
        if instr["status"] != "GENERATED":
            raise make_error("ERR_INVALID_STATE")
        cp = store.counterparties.get(instr["counterparty_id"])
        if cp is None:
            raise make_error("ERR_NOT_FOUND")
        if cp.get("on_watchlist"):
            raise make_error("ERR_COUNTERPARTY_WATCHLIST")
        before = {"status": "GENERATED"}
        instr["status"] = "SENT"
        instr["updated_at"] = clock.now_iso()
        instr["version"] = instr["version"] + 1
        store.audit(
            event_type="SETTLEMENT_FAILED",  # generic settlement-mutation audit type
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="SettlementInstruction",
            subject_id=instr["id"],
            before_snapshot=before,
            after_snapshot={"status": "SENT"},
        )
        return success_object(settlement_dto(instr))


@bp.route("/settlements/<instruction_id>/confirm", methods=["POST"])
@require_auth(["SettlementOperator"])
def confirm_instruction(instruction_id: str):
    with store.lock:
        instr = _load_instruction(instruction_id)
        if instr["status"] != "SENT":
            raise make_error("ERR_INVALID_STATE")
        before = {"status": "SENT"}
        instr["status"] = "SETTLED"
        instr["nostro_balance_delta"] = -to_decimal(instr["net_amount"])
        instr["updated_at"] = clock.now_iso()
        instr["version"] = instr["version"] + 1
        # Cascade: linked BOOKED trades for this counterparty -> SETTLED
        for trade in linked_trades_for_instruction(store, instr):
            trade["status"] = "SETTLED"
        store.audit(
            event_type="SETTLEMENT_FAILED",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="SettlementInstruction",
            subject_id=instr["id"],
            before_snapshot=before,
            after_snapshot={"status": "SETTLED",
                            "nostro_balance_delta": float(instr["nostro_balance_delta"])},
        )
        return success_object(settlement_dto(instr))


@bp.route("/settlements/<instruction_id>/mark-failed", methods=["POST"])
@require_auth(["SettlementOperator"])
def fail_instruction(instruction_id: str):
    with store.lock:
        instr = _load_instruction(instruction_id)
        if instr["status"] != "SENT":
            raise make_error("ERR_INVALID_STATE")
        before = {"status": "SENT"}
        instr["status"] = "FAILED"
        instr["updated_at"] = clock.now_iso()
        instr["version"] = instr["version"] + 1

        # Snapshot per-trader facing notional BEFORE flipping linked trades
        # to FAILED, so the depth-4 trader-suspension step can see the
        # pre-failure exposure ("aggregate facing notional" per PRD §3.7).
        cp = store.counterparties.get(instr["counterparty_id"])
        facing_by_trader: dict[str, "Decimal"] = {}
        if cp is not None:
            for trade in store.trades.values():
                if trade["counterparty_id"] != cp["id"]:
                    continue
                if trade["status"] != "BOOKED":
                    continue
                pair_id = store.pair_index_by_code.get(trade["pair_code"])
                if pair_id is None:
                    continue
                pair = store.currency_pairs[pair_id]
                rate = base_in_usd_rate(store, pair)
                notional_usd = abs(to_decimal(trade["notional_base"]) * rate)
                facing_by_trader[trade["trader_id"]] = (
                    facing_by_trader.get(trade["trader_id"], ZERO) + notional_usd
                )

        # Cascade: linked BOOKED trades -> FAILED
        affected_traders: set[str] = set()
        for trade in linked_trades_for_instruction(store, instr):
            trade["status"] = "FAILED"
            affected_traders.add(trade["trader_id"])
        store.audit(
            event_type="SETTLEMENT_FAILED",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="SettlementInstruction",
            subject_id=instr["id"],
            before_snapshot=before,
            after_snapshot={"status": "FAILED"},
        )
        # Counterparty penalty cascade
        if cp is not None:
            new_score = max(0, cp["internal_score"] - 5)
            cp_before = {
                "internal_score": cp["internal_score"],
                "rating_band": cp["rating_band"],
                "credit_limit_usd": float(cp["credit_limit_usd"]),
                "on_watchlist": cp["on_watchlist"],
            }
            cp["internal_score"] = new_score
            recompute_counterparty(cp)
            cp["updated_at"] = clock.now_iso()
            cp["version"] = cp["version"] + 1
            store.audit(
                event_type="RATING_CHANGE",
                actor_user_id="SYSTEM",
                actor_role="SYSTEM",
                subject_entity="Counterparty",
                subject_id=cp["id"],
                before_snapshot=cp_before,
                after_snapshot={
                    "internal_score": cp["internal_score"],
                    "rating_band": cp["rating_band"],
                    "credit_limit_usd": float(cp["credit_limit_usd"]),
                    "on_watchlist": cp["on_watchlist"],
                },
            )
            # Trader suspension cascade — measure facing notional from the
            # snapshot taken before linked trades flipped to FAILED. PRD
            # §3.7: "for every Trader whose aggregate facing notional now
            # exceeds the lower credit_limit_usd".
            cp_credit = to_decimal(cp["credit_limit_usd"])
            for trader_id, facing in facing_by_trader.items():
                if facing <= cp_credit:
                    continue
                trader = store.traders.get(trader_id)
                if trader is None or trader["status"] == "SUSPENDED":
                    continue
                t_before = {"status": "ACTIVE"}
                trader["status"] = "SUSPENDED"
                trader["updated_at"] = clock.now_iso()
                trader["version"] = trader["version"] + 1
                store.audit(
                    event_type="RATING_CHANGE",
                    actor_user_id="SYSTEM",
                    actor_role="SYSTEM",
                    subject_entity="Trader",
                    subject_id=trader["id"],
                    before_snapshot=t_before,
                    after_snapshot={"status": "SUSPENDED"},
                )
        return success_object(settlement_dto(instr))


@bp.route("/settlements/<instruction_id>/reconcile", methods=["POST"])
@require_auth(["SettlementOperator"])
def reconcile_instruction(instruction_id: str):
    with store.lock:
        instr = _load_instruction(instruction_id)
        if instr["status"] != "SETTLED":
            raise make_error("ERR_INVALID_STATE")
        before = {"status": "SETTLED"}
        instr["status"] = "RECONCILED"
        instr["updated_at"] = clock.now_iso()
        instr["version"] = instr["version"] + 1
        store.audit(
            event_type="SETTLEMENT_FAILED",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="SettlementInstruction",
            subject_id=instr["id"],
            before_snapshot=before,
            after_snapshot={"status": "RECONCILED"},
        )
        return success_object(settlement_dto(instr))
