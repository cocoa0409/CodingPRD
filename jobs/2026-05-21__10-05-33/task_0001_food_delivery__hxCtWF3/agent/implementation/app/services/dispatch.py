"""Dispatch, assignment lifecycle, route merging, offer-timeout sweep."""
from flask import request

from ..auth import parse_headers, require_role
from ..clock import format_iso
from ..envelope import success
from ..errors import fail
from ..formulas import haversine_km
from ..ids import new_uuid
from ..resource import bump
from ..server import store, clock
from datetime import datetime, timezone, timedelta


def _now_iso():
    return format_iso(clock.now())


def _parse_iso(s: str) -> datetime:
    # Accepts "...Z" or with offset; uses fromisoformat compatible form.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _has_live_assignment(order_id: str) -> bool:
    for a in store.assignments.values():
        if a["order_id"] == order_id and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return True
    return False


def _rider_has_live_for_order(rider_id: str, order_id: str) -> bool:
    for a in store.assignments.values():
        if (a["rider_id"] == rider_id and a["order_id"] == order_id
                and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")):
            return True
    return False


def _active_route_group(rider_id: str):
    for rg in store.route_groups.values():
        if rg["rider_id"] == rider_id and rg["status"] == "ACTIVE":
            return rg
    return None


def _candidate_pool(order):
    """Eligible riders: AVAILABLE or ON_DELIVERY, excluding those already holding this order."""
    pool = []
    for r in store.riders.values():
        if r["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            continue
        if _rider_has_live_for_order(r["id"], order["id"]):
            continue
        pool.append(r)
    return pool


def _merge_peer(rider, order):
    """Return an unpicked peer assignment of the rider whose pickup restaurant is within 500m of `order`'s pickup,
    or None. The first such assignment found is returned; that's enough to drive both dispatcher preference and
    lazy RouteGroup creation at accept time."""
    r_target = store.restaurants[order["restaurant_id"]]
    for a in store.assignments.values():
        if a["rider_id"] != rider["id"]:
            continue
        if a["status"] not in ("OFFERED", "ACCEPTED"):  # unpicked only
            continue
        if a["order_id"] == order["id"]:
            continue
        o = store.orders.get(a["order_id"])
        if not o:
            continue
        r_peer = store.restaurants[o["restaurant_id"]]
        dist_km = haversine_km(r_peer["lat"], r_peer["lng"], r_target["lat"], r_target["lng"])
        if dist_km * 1000 <= 500:
            return a
    return None


def _merge_eligible(rider, order):
    return _merge_peer(rider, order) is not None


def _select_candidate(order):
    pool = _candidate_pool(order)
    if not pool:
        return None
    # Preference tier 1: ON_DELIVERY + merge eligible. Tier 2: anyone else (AVAILABLE preferred).
    merge_pref = [r for r in pool if r["status"] == "ON_DELIVERY" and _merge_eligible(r, order)]
    if merge_pref:
        tier = merge_pref
    else:
        # remaining preference: AVAILABLE; fallback to anyone in the pool
        available = [r for r in pool if r["status"] == "AVAILABLE"]
        tier = available if available else pool

    def sort_key(r):
        # created_at desc => newest first; ties broken by id ascending
        return (-_parse_iso(r["created_at"]).timestamp(), r["id"])

    tier.sort(key=sort_key)
    return tier[0]


def dispatch_order(order):
    """Create a fresh OFFERED assignment to the next best rider. Returns the assignment dict or None."""
    rider = _select_candidate(order)
    if not rider:
        # called from /dispatch: empty pool => ERR_INVALID_STATE. From /start-preparing,
        # we accept that no assignment is created (the restaurant flow itself didn't fail).
        raise fail("ERR_INVALID_STATE", "no candidate rider available")
    now = _now_iso()
    a = {
        "id": new_uuid(),
        "created_at": now,
        "order_id": order["id"],
        "rider_id": rider["id"],
        "status": "OFFERED",
        "offered_at": now,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "route_group_id": None,
        "final_delivery_fee_cents": None,
    }
    store.assignments[a["id"]] = a
    return a


def accept_assignment(aid):
    user_id, role = parse_headers()
    require_role("Rider")
    a = store.assignments.get(aid)
    if not a:
        raise fail("ERR_NOT_FOUND")
    if user_id != a["rider_id"]:
        raise fail("ERR_FORBIDDEN")
    rider = store.riders[a["rider_id"]]
    order = store.orders[a["order_id"]]
    if a["status"] != "OFFERED":
        raise fail("ERR_INVALID_STATE")
    if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
        raise fail("ERR_INVALID_STATE")
    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise fail("ERR_INVALID_STATE")
    # Uniqueness: at most one ACCEPTED/PICKED_UP assignment per order. Two coexisting OFFERED
    # rows can race; the first to win the ACCEPTED transition prevails. This is the loser-side
    # behaviour described in §2.5 and §3.6.
    for other in store.assignments.values():
        if (other["id"] != a["id"] and other["order_id"] == a["order_id"]
                and other["status"] in ("ACCEPTED", "PICKED_UP")):
            raise fail("ERR_ORDER_ALREADY_ASSIGNED")
    now = _now_iso()
    a["status"] = "ACCEPTED"
    a["accepted_at"] = now
    # rider cascade
    if rider["status"] == "AVAILABLE":
        rider["status"] = "ON_DELIVERY"
    # acceptance_rate recompute
    rider["_recent_offers"].append(True)
    if len(rider["_recent_offers"]) > 30:
        rider["_recent_offers"] = rider["_recent_offers"][-30:]
    rider["acceptance_rate"] = _accept_rate(rider)
    _recompute_bonus_tier(rider)
    bump(rider)
    # Route merging — happens at the same moment as acceptance (§3.6).
    peer = _merge_peer(rider, order)
    if peer is not None:
        rg = _active_route_group(rider["id"])
        if rg is not None:
            # Attach to existing group. If the peer is somehow outside the group, also fold it in
            # so the group reflects the rider's full unpicked merge-eligible footprint.
            if peer["id"] not in rg["assignment_ids"]:
                rg["assignment_ids"].append(peer["id"])
                peer["route_group_id"] = rg["id"]
            rg["assignment_ids"].append(a["id"])
            a["route_group_id"] = rg["id"]
        else:
            # Lazy creation: first merge for this rider forms a new RouteGroup containing both legs.
            rg = {
                "id": new_uuid(),
                "created_at": now,
                "rider_id": rider["id"],
                "assignment_ids": [peer["id"], a["id"]],
                "merged_at": now,
                "status": "ACTIVE",
            }
            store.route_groups[rg["id"]] = rg
            peer["route_group_id"] = rg["id"]
            a["route_group_id"] = rg["id"]
    # Bookkeeping: cleanup losing OFFERED assignments to keep the assignment_pool tidy. We don't
    # mutate other OFFERED rows here — the redispatch path always creates a new row on rejection.
    return success(a)


def reject_assignment(aid):
    user_id, role = parse_headers()
    require_role("Rider")
    a = store.assignments.get(aid)
    if not a:
        raise fail("ERR_NOT_FOUND")
    if user_id != a["rider_id"]:
        raise fail("ERR_FORBIDDEN")
    if a["status"] != "OFFERED":
        raise fail("ERR_INVALID_STATE")
    a["status"] = "REJECTED"
    rider = store.riders[a["rider_id"]]
    rider["_recent_offers"].append(False)
    if len(rider["_recent_offers"]) > 30:
        rider["_recent_offers"] = rider["_recent_offers"][-30:]
    rider["acceptance_rate"] = _accept_rate(rider)
    _recompute_bonus_tier(rider)
    bump(rider)
    # Redispatch
    order = store.orders[a["order_id"]]
    try:
        dispatch_order(order)
    except Exception:
        pass
    return success(a)


def pickup_assignment(aid):
    user_id, role = parse_headers()
    require_role("Rider")
    a = store.assignments.get(aid)
    if not a:
        raise fail("ERR_NOT_FOUND")
    if user_id != a["rider_id"]:
        raise fail("ERR_FORBIDDEN")
    if a["status"] != "ACCEPTED":
        raise fail("ERR_INVALID_STATE")
    o = store.orders[a["order_id"]]
    if o["status"] != "READY_FOR_PICKUP":
        raise fail("ERR_INVALID_STATE")
    now = _now_iso()
    a["status"] = "PICKED_UP"
    a["picked_up_at"] = now
    o["status"] = "PICKED_UP"
    bump(o)
    return success(a)


def cancel_assignment(aid):
    user_id, role = parse_headers()
    require_role("Rider")
    a = store.assignments.get(aid)
    if not a:
        raise fail("ERR_NOT_FOUND")
    if user_id != a["rider_id"]:
        raise fail("ERR_FORBIDDEN")
    if a["status"] != "ACCEPTED":
        raise fail("ERR_INVALID_STATE")
    o = store.orders[a["order_id"]]
    if o["status"] == "PICKED_UP":
        raise fail("ERR_INVALID_STATE")
    a["status"] = "CANCELLED"
    rider = store.riders[a["rider_id"]]
    # RIDER_NO_SHOW fine: 500c. Cascade: wallet debit, tier recompute.
    from ..services.fines import create_fine
    create_fine("RIDER", rider["id"], "RIDER_NO_SHOW", 500)
    # If no other live assignments remain, return rider to AVAILABLE
    if not any(x for x in store.assignments.values()
               if x["rider_id"] == rider["id"] and x["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")):
        if rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
    bump(rider)
    # Redispatch fresh offer
    try:
        dispatch_order(o)
    except Exception:
        pass
    return success(a)


def _accept_rate(rider) -> float:
    offers = rider["_recent_offers"]
    if not offers:
        return 1.0
    return round(sum(1 for o in offers if o) / len(offers), 6)


def _on_time_rate(rider) -> float:
    vals = rider["_recent_on_time"]
    if len(vals) < 10:
        return 1.0
    return round(sum(1 for v in vals if v) / len(vals), 6)


def _rating(rider) -> float:
    vals = rider["_recent_ratings"]
    if not vals:
        return 5.0
    return round(sum(vals) / len(vals), 6)


def _recompute_bonus_tier(rider):
    from ..formulas import bonus_tier
    rider["bonus_tier"] = bonus_tier(rider["on_time_rate"], rider["acceptance_rate"], rider["rating"])


def sweep_offer_timeouts() -> int:
    """Sweep OFFERED assignments older than 60s to REJECTED + redispatch. Returns number swept."""
    now = clock.now()
    swept = 0
    # Snapshot the ids first because we'll create new rows during dispatch.
    candidates = [a for a in list(store.assignments.values()) if a["status"] == "OFFERED"]
    for a in candidates:
        offered_dt = _parse_iso(a["offered_at"])
        if (now - offered_dt).total_seconds() >= 60:
            a["status"] = "REJECTED"
            rider = store.riders.get(a["rider_id"])
            if rider:
                rider["_recent_offers"].append(False)
                if len(rider["_recent_offers"]) > 30:
                    rider["_recent_offers"] = rider["_recent_offers"][-30:]
                rider["acceptance_rate"] = _accept_rate(rider)
                _recompute_bonus_tier(rider)
                bump(rider)
            o = store.orders.get(a["order_id"])
            if o:
                try:
                    dispatch_order(o)
                except Exception:
                    pass
            swept += 1
    return swept
