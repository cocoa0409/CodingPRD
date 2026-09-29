"""Cascade discipline (PRD 2.10).

Every hop here is mandatory, immediate and part of the calling request.  The
functions are written so a caller only ever needs to state the *first* hop:

    place a compliance hold  -> set_hold_counter() -> recompute_posture()
                             -> skip_pending_stops() -> release_stop_allocations()

`touch()` is idempotent per request, so a resource that participates in two
hops of the same cascade still advances its `version` exactly once.
"""

from calc import alert_band, outlet_service_posture
from core import D, db, sort_rows, touch


# ---------------------------------------------------------------------------
# hop 3 - releasing the consumable committed to a stop (PRD 2.10, four moves)
# ---------------------------------------------------------------------------
def release_stop_allocations(stop):
    released_total = 0
    positions = sort_rows([p for p in db.positions.values() if p["planned_route_stop_id"] == stop["id"]])
    route = db.routes.get(stop["route_id"])
    for position in positions:
        released = position["allocated_units"]
        position["allocated_units"] = 0
        position["planned_route_stop_id"] = None
        touch(position)
        item = db.supply_items.get(position["supply_item_id"])
        if item is not None and released:
            item["reserved_pool_units"] = item["reserved_pool_units"] - released
            if item["reserved_pool_units"] < 0:
                item["reserved_pool_units"] = 0
            touch(item)
        if route is not None and released:
            route["committed_units"] = route["committed_units"] - released
            if route["committed_units"] < 0:
                route["committed_units"] = 0
            touch(route)
        released_total += released
    return released_total


# ---------------------------------------------------------------------------
# hop 2 - skipping a stop
# ---------------------------------------------------------------------------
def skip_stop(stop, reason_code):
    stop["status"] = "SKIPPED"
    stop["skip_reason_code"] = reason_code
    touch(stop)
    release_stop_allocations(stop)


def skip_outlet_stops(outlet_id, reason_code, statuses=("PENDING",)):
    stops = sort_rows(
        [s for s in db.stops.values() if s["outlet_id"] == outlet_id and s["status"] in statuses]
    )
    for stop in stops:
        skip_stop(stop, reason_code)


# ---------------------------------------------------------------------------
# hop 1 - the derived compliance gate
# ---------------------------------------------------------------------------
def recompute_posture(outlet):
    """Recomputed immediately after either counter changes.  Landing on FROZEN
    continues the chain into the outlet's PENDING stops."""
    outlet["service_posture"] = outlet_service_posture(outlet)
    touch(outlet)
    if outlet["service_posture"] == "FROZEN":
        skip_outlet_stops(outlet["id"], "POSTURE_FROZEN", ("PENDING",))


def bump_overdue(outlet, delta):
    outlet["overdue_task_count"] = max(0, outlet["overdue_task_count"] + delta)
    recompute_posture(outlet)


# ---------------------------------------------------------------------------
# server-driven suspension (PRD 3.1 last paragraph)
# ---------------------------------------------------------------------------
def suspend_outlet(outlet):
    """Same stop-skip / allocation-release cascade and the same single version
    increment as the operator action.  The posture is NOT recomputed: neither
    counter changed."""
    if outlet["status"] != "ACTIVE":
        return
    outlet["status"] = "SUSPENDED"
    touch(outlet)
    skip_outlet_stops(outlet["id"], "OUTLET_CLOSED", ("PENDING", "ARRIVED"))


LIVE_AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "SHORTFALL_REVIEW", "RECALL_PENDING")


def suspend_outlet_if_no_live_agreement(outlet):
    live = [
        a
        for a in db.agreements.values()
        if a["outlet_id"] == outlet["id"] and a["status"] in LIVE_AGREEMENT_STATUSES
    ]
    if not live:
        suspend_outlet(outlet)


# ---------------------------------------------------------------------------
# van parts: the compensating release shared by escalation and cancellation
# ---------------------------------------------------------------------------
def release_call_parts(call):
    stock_id = call.get("reserved_part_stock_id")
    held = call.get("reserved_part_units") or 0
    if stock_id is not None:
        stock = db.van_stocks.get(stock_id)
        if stock is not None and held:
            stock["reserved_units"] = max(0, stock["reserved_units"] - held)
            stock["on_van_units"] = stock["on_van_units"] + held
            touch(stock)
    call["reserved_part_units"] = 0
    call["reserved_part_stock_id"] = None


# ---------------------------------------------------------------------------
# confirm-return: the deepest cascade in the system (PRD 3.3)
# ---------------------------------------------------------------------------
def confirm_return_cascade(unit):
    outlet = db.outlets.get(unit["outlet_id"])

    # (a) every open maintenance task of the unit is waived by the server
    tasks = sort_rows(
        [
            t
            for t in db.tasks.values()
            if t["dispenser_unit_id"] == unit["id"] and t["status"] in ("SCHEDULED", "DUE", "OVERDUE")
        ]
    )
    for task in tasks:
        was_overdue = task["status"] == "OVERDUE"
        task["status"] = "WAIVED"
        task["waiver_reason"] = "EQUIPMENT_RETURNED"
        touch(task)
        if was_overdue and outlet is not None:
            bump_overdue(outlet, -1)

    # (b) every live service call of the unit is cancelled, parts back to the van
    calls = sort_rows(
        [
            c
            for c in db.calls.values()
            if c["dispenser_unit_id"] == unit["id"]
            and c["status"] in ("OPEN", "DISPATCHED", "ON_SITE", "ESCALATED")
        ]
    )
    for call in calls:
        release_call_parts(call)
        call["status"] = "CANCELLED"
        touch(call)

    # (c) the last return under an agreement terminates it, which may suspend
    #     the outlet, which skips its pending stops, which releases allocations
    agreement = db.agreements.get(unit["agreement_id"])
    if agreement is not None and agreement["status"] == "RECALL_PENDING":
        siblings = [u for u in db.units.values() if u["agreement_id"] == agreement["id"]]
        if all(u["status"] == "RETURNED" for u in siblings):
            agreement["status"] = "TERMINATED"
            touch(agreement)
            if outlet is not None:
                suspend_outlet_if_no_live_agreement(outlet)


# ---------------------------------------------------------------------------
# delivery: recompute one position's alert band against its new on_hand_units
# ---------------------------------------------------------------------------
def recompute_alert_after_delivery(position, item):
    daily = D(position.get("_daily_ounces", 0))
    position["alert_level"] = alert_band(position["on_hand_units"], item["ounces_per_unit"], daily)
