"""Stop-loss trigger evaluation per §3.5 / §1.3 stop_loss_evaluation."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.numeric import round_half_up, to_decimal, ZERO
from app.services.fx import base_in_usd_rate
from app.store import Store, now_iso


def _position_for(store: Store, trader_id: str, pair_code: str) -> Optional[dict]:
    pid = store.position_index.get((trader_id, pair_code))
    return store.positions[pid] if pid else None


def evaluate_rule(store: Store, event: dict) -> Optional[Decimal]:
    """Return the observed metric value when the rule trips, else None.

    Does not mutate `event`.  Caller is responsible for transitioning state.
    """
    if event["state"] != "ARMED":
        return None
    pair_id = store.pair_index_by_code.get(event["pair_code"])
    if pair_id is None:
        return None
    pair = store.currency_pairs[pair_id]
    position = _position_for(store, event["trader_id"], event["pair_code"])
    net_base = to_decimal(position["net_base"]) if position else ZERO
    mtm = to_decimal(position["mtm_pnl_usd"]) if position else ZERO
    mid = to_decimal(pair["mid_rate"])
    threshold = to_decimal(event["threshold_value"])
    mode = event["rule_mode"]

    if mode == "PRICE":
        if net_base > 0:
            if mid <= threshold:
                return mid
        elif net_base < 0:
            if mid >= threshold:
                return mid
        return None

    if mode == "LOSS_AMOUNT":
        if mtm < 0 and abs(mtm) >= threshold:
            return abs(mtm)
        return None

    if mode == "LOSS_RATIO":
        if mtm >= 0 or net_base == 0:
            return None
        rate = base_in_usd_rate(store, pair)
        notional_usd = abs(net_base * rate)
        if notional_usd == 0:
            return None
        ratio = abs(mtm) / notional_usd
        ratio_rounded = round_half_up(ratio, 6)
        if ratio_rounded >= threshold:
            return ratio_rounded
        return None

    return None


def evaluate_all_armed_for_pair(store: Store, pair_code: str) -> list[dict]:
    """Walk every ARMED stop-loss on this pair; fire when crossed.

    Mutates events in place.  Returns the list of newly-TRIGGERED events.
    """
    triggered: list[dict] = []
    candidates = [e for e in store.stop_loss_events.values()
                  if e["pair_code"] == pair_code and e["state"] == "ARMED"]
    # Stable ordering: created_at then id.
    candidates.sort(key=lambda e: (e["created_at"], e["id"]))
    for event in candidates:
        observed = evaluate_rule(store, event)
        if observed is None:
            continue
        event["state"] = "TRIGGERED"
        event["triggered_at"] = now_iso()
        event["triggering_value"] = observed
        event["updated_at"] = now_iso()
        event["version"] = event["version"] + 1
        triggered.append(event)
        store.audit(
            event_type="STOP_LOSS_TRIGGERED",
            actor_user_id="SYSTEM",
            actor_role="SYSTEM",
            subject_entity="StopLossEvent",
            subject_id=event["id"],
            before_snapshot={"state": "ARMED"},
            after_snapshot={"state": "TRIGGERED",
                            "triggered_at": event["triggered_at"],
                            "triggering_value": float(observed)},
        )
    return triggered
