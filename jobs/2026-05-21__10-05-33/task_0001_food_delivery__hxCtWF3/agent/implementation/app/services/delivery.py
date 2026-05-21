"""Delivery cascade and fiscal reconciliation."""
from datetime import datetime, timezone

from ..auth import parse_headers, require_role
from ..clock import format_iso
from ..envelope import success
from ..errors import fail
from ..formulas import (
    delivery_fee_solo, commission_tiered, commission_override,
    merge_discount, late_fine_amount,
)
from ..resource import bump
from ..server import store, clock


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def deliver_assignment(aid):
    user_id, role = parse_headers()
    require_role("Rider")
    a = store.assignments.get(aid)
    if not a:
        raise fail("ERR_NOT_FOUND")
    if user_id != a["rider_id"]:
        raise fail("ERR_FORBIDDEN")
    if a["status"] != "PICKED_UP":
        raise fail("ERR_INVALID_STATE")
    o = store.orders[a["order_id"]]
    if o["status"] != "PICKED_UP":
        raise fail("ERR_INVALID_STATE")
    restaurant = store.restaurants[o["restaurant_id"]]
    rider = store.riders[a["rider_id"]]

    now = clock.now()
    now_iso = format_iso(now)
    a["status"] = "DELIVERED"
    a["delivered_at"] = now_iso
    o["status"] = "DELIVERED"
    o["actual_delivery_time"] = now_iso

    promised_dt = _parse_iso(o["promised_delivery_time"])
    diff_seconds = (now - promised_dt).total_seconds()
    if diff_seconds <= 0:
        minutes_late = 0
    else:
        minutes_late = int(diff_seconds // 60)
    o["minutes_late"] = minutes_late

    # Final delivery fee — reconciled from frozen inputs.
    solo_fee = delivery_fee_solo(o["distance_km"], o["is_peak"])
    rg = store.route_groups.get(a["route_group_id"]) if a["route_group_id"] else None
    if rg and len(rg["assignment_ids"]) >= 2:
        discount = merge_discount(solo_fee)
        final_fee = solo_fee - discount
    else:
        final_fee = solo_fee
    o["final_delivery_fee_cents"] = final_fee
    a["final_delivery_fee_cents"] = final_fee

    # Final commission — override at delivery time, or tiered.
    if restaurant["commission_rate_override"] is not None:
        final_comm = commission_override(o["subtotal_cents"], restaurant["commission_rate_override"])
    else:
        final_comm = commission_tiered(o["subtotal_cents"])
    o["final_commission_cents"] = final_comm

    # Payment captured.
    o["payment_status"] = "CAPTURED"

    bump(o)

    # Restaurant settlement increment.
    restaurant["pending_settlement_cents"] += o["subtotal_cents"] - final_comm
    bump(restaurant)

    # Rider wallet credit + on-time tracking + tier recompute.
    rider["wallet_balance_cents"] += final_fee
    rider["_recent_on_time"].append(minutes_late == 0)
    if len(rider["_recent_on_time"]) > 30:
        rider["_recent_on_time"] = rider["_recent_on_time"][-30:]
    rider["completed_deliveries"] += 1
    rider["on_time_rate"] = _on_time_rate(rider)
    _recompute_bonus_tier(rider)

    # Late fine cascade.
    if minutes_late > 0:
        amount = late_fine_amount(minutes_late, final_fee)
        from ..services.fines import create_fine
        # create_fine debits the rider wallet + bumps + recomputes tier as a sub-cascade
        create_fine("RIDER", rider["id"], "LATE_DELIVERY", amount)

    # If no other live assignments remain, return rider to AVAILABLE
    if not any(x for x in store.assignments.values()
               if x["rider_id"] == rider["id"] and x["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
               and x["id"] != a["id"]):
        if rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
    bump(rider)

    # Route group completion check.
    if rg:
        all_done = all(store.assignments[aid_]["status"] == "DELIVERED" for aid_ in rg["assignment_ids"])
        if all_done:
            rg["status"] = "COMPLETED"

    return success(a)


def _on_time_rate(rider) -> float:
    vals = rider["_recent_on_time"]
    if len(vals) < 10:
        return 1.0
    return round(sum(1 for v in vals if v) / len(vals), 6)


def _recompute_bonus_tier(rider):
    from ..formulas import bonus_tier
    rider["bonus_tier"] = bonus_tier(rider["on_time_rate"], rider["acceptance_rate"], rider["rating"])
