"""Cross-entity cascades: call events, call close chain, fleet suspension,
reorder trigger, dispatch reversion."""
from db import store, new_id, touch
from serializers import fleet_mtd
from util import now_wall_iso

CALL_ACTIVE_DISPATCH_STATES = ("PROPOSED", "ACCEPTED", "EN_ROUTE", "ON_SITE")


def wall_now():
    return now_wall_iso()


def append_event(call_id, event_type, actor_role, actor_id, note=None):
    rec = {
        "id": new_id(),
        "_seq": next(store.seq),
        "_created": wall_now(),
        "service_call_id": call_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "note": note,
    }
    store.call_events[rec["id"]] = rec
    return rec


def call_dispatches(call_id):
    return [d for d in store.dispatches.values()
            if d["service_call_id"] == call_id]


def has_active_dispatch(call_id):
    return any(d["status"] in CALL_ACTIVE_DISPATCH_STATES
               for d in call_dispatches(call_id))


def revert_call_if_no_active_dispatch(call):
    """DISPATCHED -> TRIAGED when no PROPOSED/ACCEPTED/EN_ROUTE/ON_SITE remains."""
    if call["status"] == "DISPATCHED" and not has_active_dispatch(call["id"]):
        call["status"] = "TRIAGED"
        touch(call, wall_now())


def free_technician(technician_id):
    tech = store.technicians.get(technician_id)
    if tech is not None and tech["status"] == "ON_DISPATCH":
        tech["status"] = "AVAILABLE"
        tech["current_dispatch_id"] = None
        touch(tech, wall_now())


def close_call(call):
    """INVOICED -> CLOSED with CALL_CLOSED plus the repeat-failure cascade
    (CONFIRMED_COMEBACK case -> RESOLVED; original REOPENED -> CLOSED)."""
    if call["status"] != "INVOICED":
        return
    call["status"] = "CLOSED"
    touch(call, wall_now())
    append_event(call["id"], "CALL_CLOSED", "system", "system")
    for case in store.repeat_cases.values():
        if (case["new_service_call_id"] == call["id"]
                and case["status"] == "CONFIRMED_COMEBACK"):
            case["status"] = "RESOLVED"
            touch(case, wall_now())
            original = store.service_calls.get(case["original_service_call_id"])
            if original is not None and original["status"] == "REOPENED":
                original["status"] = "CLOSED"
                touch(original, wall_now())


def suspend_fleet_credit_hold(fleet):
    """Invoice-issue cascade hops 2-4: SUSPEND with CREDIT_HOLD, flag open calls,
    expire their PROPOSED dispatches, revert DISPATCHED calls."""
    fleet["status"] = "SUSPENDED"
    fleet["suspension_reason"] = "CREDIT_HOLD"
    touch(fleet, wall_now())
    for call in store.service_calls.values():
        if (call.get("fleet_account_id") == fleet["id"]
                and call["status"] in ("RECEIVED", "TRIAGED", "DISPATCHED")):
            call["hold_reason"] = "FLEET_CREDIT_HOLD"
            touch(call, wall_now())
            append_event(call["id"], "HOLD_FLAGGED", "system", "system")
            for disp in call_dispatches(call["id"]):
                if disp["status"] == "PROPOSED":
                    disp["status"] = "EXPIRED"
                    touch(disp, wall_now())
            revert_call_if_no_active_dispatch(call)


def maybe_reinstate_credit_hold(fleet):
    """Auto-reinstate a CREDIT_HOLD fleet whose mtd is back within cap."""
    if (fleet["status"] == "SUSPENDED"
            and fleet["suspension_reason"] == "CREDIT_HOLD"
            and fleet_mtd(fleet["id"]) <= fleet["monthly_spend_cap_cents"]):
        fleet["status"] = "ACTIVE"
        fleet["suspension_reason"] = "NONE"
        touch(fleet, wall_now())
        return True
    return False


def reorder_trigger(item):
    """Open an AUTO_LOW_STOCK RestockRequest when qty_on_hand <= reorder_point
    and no PENDING/APPROVED request exists for the item."""
    if item["qty_on_hand"] > item["reorder_point"]:
        return
    for r in store.restock_requests.values():
        if (r["van_stock_item_id"] == item["id"]
                and r["status"] in ("PENDING", "APPROVED")):
            return
    qty = max(1, item["reorder_point"] + 2 - item["qty_on_hand"])
    rec = {
        "id": new_id(),
        "version": 1,
        "_seq": next(store.seq),
        "_created": wall_now(),
        "_updated": wall_now(),
        "van_stock_item_id": item["id"],
        "technician_id": item["technician_id"],
        "source": "AUTO_LOW_STOCK",
        "qty_requested": qty,
        "status": "PENDING",
        "fulfilled_qty": None,
        "reject_reason": None,
    }
    store.restock_requests[rec["id"]] = rec
