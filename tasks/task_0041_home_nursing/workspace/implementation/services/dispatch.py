"""Dispatch selector + lifecycle."""
from datetime import timedelta
from decimal import Decimal

import db
from clock import now, parse_iso, iso
from errors import err
from services.audit import audit
from services.constants import (
    ACCEPTANCE_WINDOW_SECONDS, MAX_DISPATCH_RADIUS_KM, MAX_DISPATCH_ATTEMPTS,
    W_DIST, W_LOAD, W_RATING,
)
from services.util import haversine_km_3dp, round_half_up_decimals


# -------------------------------------------------------------- Selection --
def _candidate_filter(order: dict, item: dict, exclude_nurse_ids: set):
    """Return (candidate_nurse, distance_km) tuples."""
    candidates = []
    for nurse in db.nurses.values():
        if nurse["id"] in exclude_nurse_ids:
            continue
        if nurse.get("certification_status") not in ("CERTIFIED", "EXPIRING"):
            continue
        if item["required_skill"] not in (nurse.get("specialty_tags") or []):
            continue
        # gender preference
        pref_gender = order.get("preferred_gender") or "ANY"
        if pref_gender != "ANY" and nurse.get("gender") != pref_gender:
            continue
        # language preference
        pref_lang = order.get("preferred_language") or "any"
        if pref_lang != "any" and pref_lang not in (nurse.get("languages") or []):
            continue
        # distance
        dist = haversine_km_3dp(
            nurse["home_lat"], nurse["home_lng"],
            order["service_lat"], order["service_lng"],
        )
        if dist > MAX_DISPATCH_RADIUS_KM:
            continue
        # daily workload
        load = _current_daily_load(nurse["id"])
        if load >= int(nurse.get("max_daily_orders") or 0):
            continue
        candidates.append((nurse, dist, load))
    return candidates


def _current_daily_load(nurse_id: str) -> int:
    """Count orders currently DISPATCHED or IN_PROGRESS assigned to this nurse for today (UTC)."""
    today = now().date()
    count = 0
    for order in db.orders.values():
        if order.get("status") not in ("DISPATCHED", "IN_PROGRESS"):
            continue
        # Determine assigned nurse via accepted dispatch
        assigned = _accepted_nurse_id_for_order(order["id"])
        if assigned != nurse_id:
            continue
        try:
            created_dt = parse_iso(order["created_at"])
        except Exception:
            continue
        if created_dt.date() == today:
            count += 1
    return count


def _accepted_nurse_id_for_order(order_id: str):
    for d in db.dispatches.values():
        if d.get("order_id") == order_id and d.get("status") == "ACCEPTED":
            return d.get("nurse_id")
    return None


def _excluded_nurses_for_order(order_id: str) -> set:
    """Nurses tied to prior REJECTED or EXPIRED dispatches on this order are excluded."""
    excluded = set()
    for d in db.dispatches.values():
        if d.get("order_id") != order_id:
            continue
        if d.get("status") in ("REJECTED", "EXPIRED"):
            excluded.add(d["nurse_id"])
    return excluded


def _composite_score(distance: float, load: int, max_daily: int, rating: float) -> Decimal:
    d = Decimal(W_DIST) * (Decimal(str(distance)) / Decimal(str(MAX_DISPATCH_RADIUS_KM)))
    l = Decimal(W_LOAD) * (Decimal(str(load)) / Decimal(str(max_daily)))
    r = Decimal(W_RATING) * (Decimal("5") - Decimal(str(rating)))
    score = d + l + r
    return round_half_up_decimals(score, 4)


def select_and_dispatch(order: dict) -> dict:
    """Run selector for an order in AWAITING_DISPATCH; create a Dispatch row.

    Returns the new Dispatch dict, or None when fallback (no nurse available) fired.
    On fallback the order is moved to CANCELLED here.
    """
    item = db.service_items.get(order["service_item_code"])
    if item is None:
        # shouldn't happen at dispatch time
        _fail_no_nurse(order)
        return None

    excluded = _excluded_nurses_for_order(order["id"])
    candidates = _candidate_filter(order, item, excluded)
    if not candidates:
        _fail_no_nurse(order)
        return None

    ranked = []
    for nurse, dist, load in candidates:
        score = _composite_score(dist, load, int(nurse["max_daily_orders"]), float(nurse["rating"]))
        ranked.append((score, dist, nurse["id"], nurse, load))
    # Sort by score asc, then distance asc, then id lexicographic asc
    ranked.sort(key=lambda t: (t[0], Decimal(str(t[1])), t[2]))
    best = ranked[0]
    score, dist, nid, nurse, load = best

    offered_at_dt = now()
    deadline_dt = offered_at_dt + timedelta(seconds=ACCEPTANCE_WINDOW_SECONDS)
    dispatch = {
        "order_id": order["id"],
        "nurse_id": nid,
        "ranked_score": float(score),
        "distance_km": dist,
        "offered_at": iso(offered_at_dt),
        "accept_deadline": iso(deadline_dt),
        "status": "OFFERED",
        "rejection_reason": None,
    }
    db.stamp_create(dispatch, common_fields=False)
    db.dispatches[dispatch["id"]] = dispatch

    order["dispatch_attempt_count"] = int(order.get("dispatch_attempt_count") or 0) + 1
    db.stamp_update(order)
    return dispatch


def _fail_no_nurse(order: dict) -> None:
    order["status"] = "CANCELLED"
    order["cancelled_reason"] = "ERR_NO_AVAILABLE_NURSE"
    db.stamp_update(order)
    if order.get("payment_status") == "AUTHORIZED":
        order["payment_status"] = "REFUNDED"
        db.stamp_update(order)


def get_dispatch(dispatch_id: str) -> dict:
    d = db.dispatches.get(dispatch_id)
    if d is None:
        raise err("ERR_DISPATCH_NOT_FOUND", f"dispatch {dispatch_id} not found")
    return d


# ------------------------------------------------------------ Transitions --
def accept_dispatch(dispatch_id: str, user_id: str, body: dict) -> dict:
    from services.util import check_occ
    d = get_dispatch(dispatch_id)
    # PRD §2.5 priority funnel:
    #   (5) cross-entity referential integrity (ERR_RESOURCE_LINK_INVALID)
    #   (6) business rules — including the §3.3 acceptance-window check
    # so the wrong-nurse referential check fires before the deadline check.
    if d["nurse_id"] != user_id:
        raise err("ERR_RESOURCE_LINK_INVALID", "only the dispatched nurse may accept")
    # PRD §3.3: 'at-or-after the deadline yields ERR_DISPATCH_WINDOW_EXPIRED
    # regardless of whether the call would have been an accept or a reject.'
    # The deadline check fires before the EXPIRED state precondition so the
    # caller sees the dedicated error code even after the clock-advance hook
    # has already flipped the dispatch to EXPIRED.
    deadline = parse_iso(d["accept_deadline"])
    if now() >= deadline:
        raise err("ERR_DISPATCH_WINDOW_EXPIRED", "accept_deadline already passed")
    # State must be OFFERED
    if d["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", f"dispatch is {d['status']}")
    # Order state check + already-taken
    order = db.orders.get(d["order_id"])
    if order is None:
        raise err("ERR_ORDER_NOT_FOUND", "order not found")
    # If another dispatch is ACCEPTED for the same order → already taken
    for other in db.dispatches.values():
        if other["id"] == d["id"]:
            continue
        if other["order_id"] == order["id"] and other["status"] == "ACCEPTED":
            raise err("ERR_DISPATCH_ALREADY_TAKEN",
                      "another dispatch on this order is already accepted")
    if order["status"] != "AWAITING_DISPATCH":
        raise err("ERR_INVALID_STATE", f"order is {order['status']}")

    check_occ(d, body or {})

    # Commit acceptance
    d["status"] = "ACCEPTED"
    # No version bump on Dispatch (no version column)
    order["status"] = "DISPATCHED"
    db.stamp_update(order)
    # Cancel sibling OFFERED dispatches
    for sib in list(db.dispatches.values()):
        if sib["id"] == d["id"]:
            continue
        if sib["order_id"] == order["id"] and sib["status"] == "OFFERED":
            sib["status"] = "CANCELLED"
    return d


def reject_dispatch(dispatch_id: str, user_id: str, body: dict) -> dict:
    from services.util import check_occ
    d = get_dispatch(dispatch_id)
    # PRD §2.5 priority: ref-integrity (5) before business rules (6+).
    if d["nurse_id"] != user_id:
        raise err("ERR_RESOURCE_LINK_INVALID", "only the dispatched nurse may reject")
    # PRD §3.3: deadline check fires regardless of underlying state.
    deadline = parse_iso(d["accept_deadline"])
    if now() >= deadline:
        raise err("ERR_DISPATCH_WINDOW_EXPIRED", "accept_deadline already passed")
    if d["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", f"dispatch is {d['status']}")

    check_occ(d, body or {})

    reason = (body or {}).get("rejection_reason")
    if reason is not None and not isinstance(reason, str):
        raise err("ERR_INVALID_REQUEST", "rejection_reason must be a string")
    d["rejection_reason"] = reason
    d["status"] = "REJECTED"

    # Trigger re-dispatch on the parent order
    order = db.orders.get(d["order_id"])
    if order is not None:
        _trigger_redispatch(order)
    return d


def _trigger_redispatch(order: dict) -> None:
    """Order goes back to AWAITING_DISPATCH if attempt cap not reached and no ACCEPTED exists."""
    # Skip if order already has an ACCEPTED dispatch (race winner stands)
    for d in db.dispatches.values():
        if d.get("order_id") == order["id"] and d.get("status") == "ACCEPTED":
            return
    # Cap check
    if int(order.get("dispatch_attempt_count") or 0) >= MAX_DISPATCH_ATTEMPTS:
        order["status"] = "CANCELLED"
        order["cancelled_reason"] = "ERR_NO_AVAILABLE_NURSE"
        db.stamp_update(order)
        if order.get("payment_status") == "AUTHORIZED":
            order["payment_status"] = "REFUNDED"
            db.stamp_update(order)
        return

    # Set to AWAITING_DISPATCH and rerun selector
    if order["status"] == "DISPATCHED":
        order["status"] = "AWAITING_DISPATCH"
        db.stamp_update(order)
    select_and_dispatch(order)


def cancel_offered_dispatches_for_order(order_id: str) -> None:
    for d in list(db.dispatches.values()):
        if d.get("order_id") == order_id and d.get("status") == "OFFERED":
            d["status"] = "CANCELLED"


def cancel_offered_dispatches_for_nurse_and_redispatch(nurse_id: str) -> None:
    """When a nurse is disqualified, cancel all OFFERED dispatches and re-dispatch."""
    affected_orders = set()
    for d in list(db.dispatches.values()):
        if d.get("nurse_id") == nurse_id and d.get("status") == "OFFERED":
            d["status"] = "CANCELLED"
            affected_orders.add(d["order_id"])
    for oid in affected_orders:
        order = db.orders.get(oid)
        if order is None:
            continue
        if order["status"] == "AWAITING_DISPATCH":
            # Re-run selector
            from services.dispatch import select_and_dispatch  # noqa: F401
            select_and_dispatch(order)


def cancel_offered_dispatches_for_nurse(nurse_id: str) -> None:
    """For cert-lapse: cancel OFFERED dispatches but don't re-dispatch (test hook will, separately)."""
    for d in list(db.dispatches.values()):
        if d.get("nurse_id") == nurse_id and d.get("status") == "OFFERED":
            d["status"] = "CANCELLED"


def list_dispatches_for_order(order_id: str, limit: int, offset: int):
    rows = [d for d in db.dispatches.values() if d.get("order_id") == order_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total
