"""Cross-entity derived-field recomputation and cascade helpers.

Every derived field is recomputed synchronously, inside the same request
that triggers it (PRD 2.6, consistency_model: immediate). Each distinct
mutation "hop" to a resource gets its own touch() (own updated_at advance +
version bump), matching the cascade side-effect lists in SCAFFOLD.yaml.
"""
from decimal import Decimal

from helpers import new_common_fields, new_id, touch
from timeutil import current_clock, parse_iso8601


# ---------------------------------------------------------------------------
# POD
# ---------------------------------------------------------------------------

def recompute_risk_tier_value(pod: dict) -> str:
    if pod["operational_status"] == "RESTRICTED":
        return "CRITICAL"
    if pod["queue_backlog_count"] >= 20:
        return "ELEVATED"
    return "STANDARD"


def pod_set_operational_status(pod: dict, new_status: str):
    """Sets operational_status and recomputes risk_tier as one atomic mutation."""
    pod["operational_status"] = new_status
    pod["risk_tier"] = recompute_risk_tier_value(pod)
    touch(pod)


def pod_adjust_queue_backlog(pod: dict, delta: int):
    """Adjusts queue_backlog_count and recomputes risk_tier as one atomic mutation."""
    pod["queue_backlog_count"] += delta
    pod["risk_tier"] = recompute_risk_tier_value(pod)
    touch(pod)


def pod_adjust_open_allocation_count(pod: dict, delta: int):
    pod["open_allocation_request_count"] += delta
    touch(pod)


def pod_adjust_committed_hours(pod: dict, delta_hours):
    current = Decimal(str(pod["committed_staff_hours"]))
    current += Decimal(str(delta_hours))
    pod["committed_staff_hours"] = float(current)
    touch(pod)


def shift_duration_hours(shift: dict) -> Decimal:
    start = parse_iso8601(shift["start_time"])
    end = parse_iso8601(shift["end_time"])
    delta = end - start
    return Decimal(delta.total_seconds()) / Decimal(3600)


def maybe_cascade_restrict_from_dispense(pod: dict, lot: dict, countermeasure: dict):
    """Cascade A hop 2 + hop 3: called after InventoryLot.on_hand_quantity has been
    decremented by a dispense. Returns the auto-created AllocationRequest dict, or None.
    """
    if lot["available_quantity"] < countermeasure["reorder_point_quantity"] and pod["operational_status"] == "OPERATIONAL":
        pod_set_operational_status(pod, "RESTRICTED")  # hop 2
        # hop 3: auto-file a replenishment AllocationRequest against the SNS cache
        auto_request = dict(new_common_fields())
        auto_request.update({
            "pod_id": pod["id"],
            "countermeasure_id": countermeasure["id"],
            "source_type": "SNS_CACHE",
            "partner_pod_id": None,
            "requested_quantity": countermeasure["reorder_point_quantity"],
            "status": "REQUESTED",
            "reserved_quantity": 0,
            "fulfilled_quantity": 0,
            "source_inventory_lot_id": None,
            "priority_score": 0,
            "reimbursement_cost_usd": 0,
        })
        pod_adjust_open_allocation_count(pod, 1)  # hop 3 counter bump
        return auto_request
    return None


# ---------------------------------------------------------------------------
# InventoryLot
# ---------------------------------------------------------------------------

def recompute_lot_available(lot: dict):
    lot["available_quantity"] = lot["on_hand_quantity"] - lot["reserved_quantity"]


def lot_adjust_on_hand(lot: dict, delta: int):
    lot["on_hand_quantity"] += delta
    recompute_lot_available(lot)
    touch(lot)


def lot_adjust_reserved(lot: dict, delta: int):
    lot["reserved_quantity"] += delta
    recompute_lot_available(lot)
    touch(lot)


def lot_adjust_both(lot: dict, on_hand_delta: int, reserved_delta: int):
    lot["on_hand_quantity"] += on_hand_delta
    lot["reserved_quantity"] += reserved_delta
    recompute_lot_available(lot)
    touch(lot)


# ---------------------------------------------------------------------------
# HazardPlan readiness score
# ---------------------------------------------------------------------------

def recompute_readiness_score(hazard_plan: dict, drills_store: dict):
    plan_drills = [d for d in drills_store.values() if d["hazard_plan_id"] == hazard_plan["id"]]
    denom = max(len(plan_drills), 1)
    resolved = sum(
        1 for d in plan_drills
        if d["status"] == "COMPLETED" and d["corrective_action_status"] in ("NONE", "CLOSED")
    )
    from decimalutil import round_half_up
    hazard_plan["readiness_score"] = round_half_up(100 * resolved / denom, 0)
    touch(hazard_plan)
