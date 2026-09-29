"""Courier selection, the buffered-interval rule, and courier release."""

from datetime import timedelta

from constants import (
    COLD_CLASSES,
    CONTROLLED_CLASSES,
    COURIER_TURNAROUND_BUFFER_MINUTES,
    OFFER_TTL_MINUTES,
)
from db import db, new_row, sort_rows, touch
from services import derive


def buffered_bounds(window):
    pad = timedelta(minutes=COURIER_TURNAROUND_BUFFER_MINUTES)
    return window["window_start"] - pad, window["window_end"] + pad


def has_overlap_conflict(courier, window, exclude_delivery_id=None):
    """Closed padded interval: sharing an endpoint IS a conflict."""
    for assignment in derive.courier_assignments(courier):
        if assignment["status"] != "ACCEPTED":
            continue
        if exclude_delivery_id and assignment["delivery_id"] == exclude_delivery_id:
            continue
        other = db.deliveries.get(assignment["delivery_id"])
        if other is None:
            continue
        other_window = db.delivery_windows.get(other["window_id"])
        if other_window is None:
            continue
        low, high = buffered_bounds(other_window)
        if window["window_start"] <= high and low <= window["window_end"]:
            return True
    return False


def is_candidate(courier, delivery, window, zone):
    if courier["status"] not in {"AVAILABLE", "ON_ROUTE"}:
        return False
    if courier["mode"] != window["courier_mode"]:
        return False
    if zone["zone_code"] not in courier["served_zone_codes"]:
        return False
    if courier["id"] in delivery["excluded_courier_ids"]:
        return False
    if delivery["handling_class"] in COLD_CLASSES and not courier["cold_chain_equipped"]:
        return False
    if delivery["handling_class"] in CONTROLLED_CLASSES and not courier["controlled_certified"]:
        return False
    if has_overlap_conflict(courier, window, exclude_delivery_id=delivery["id"]):
        return False
    return True


def select_courier(delivery, window, zone):
    """Deterministic ranking: rolling score DESC, active count ASC, created_at ASC."""
    pool = [c for c in db.couriers.values() if is_candidate(c, delivery, window, zone)]
    if not pool:
        return None
    ordered = sorted(
        sort_rows(pool),
        key=lambda c: (-derive.rolling_reliability_score(c),
                       derive.active_delivery_count(c)),
    )
    return ordered[0]


def create_offer(delivery, courier, rank_score):
    assignment = new_row()
    assignment["delivery_id"] = delivery["id"]
    assignment["courier_id"] = courier["id"]
    assignment["mode"] = courier["mode"]
    assignment["status"] = "OFFERED"
    assignment["offered_at"] = db.clock
    assignment["offer_expires_at"] = db.clock + timedelta(minutes=OFFER_TTL_MINUTES)
    assignment["responded_at"] = None
    assignment["rank_score"] = rank_score
    assignment["revoked_by_ops_user_id"] = None
    assignment["notes"] = None
    db.courier_assignments[assignment["id"]] = assignment
    return assignment


def release_courier(courier):
    """After an assignment stops being ACCEPTED: ON_ROUTE -> AVAILABLE at 0 legs."""
    if courier is None:
        return
    if courier["status"] == "ON_ROUTE" and derive.active_delivery_count(courier) == 0:
        courier["status"] = "AVAILABLE"
    touch(courier)


def apply_reliability(courier):
    """Recompute scores (derived) and cascade the automatic suspension."""
    if courier is None:
        return
    if derive.suspension_due(courier):
        courier["status"] = "SUSPENDED"
