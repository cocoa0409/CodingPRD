"""Hierarchical cascade helpers (PRD 2.6) and deficiency factory.

Every resource touched by a cascade is itself mutated: updated_at refreshes
and version increments by 1 (via touch()).
"""
from db import store
from calc import SEVERITY_DAYS
from store_ops import new_id, new_common_fields, touch
from timeutil import days


def cancel_order_cascade(order):
    """REQUESTED/SCHEDULED -> CANCELLED; a linked RE_TEST_SCHEDULED deficiency
    falls back to CORRECTED."""
    if order["status"] not in ("REQUESTED", "SCHEDULED"):
        return
    order["status"] = "CANCELLED"
    touch(order)
    d = store.deficiencies.get(order.get("linked_deficiency_id") or "")
    if d is not None and d["status"] == "RE_TEST_SCHEDULED":
        d["status"] = "CORRECTED"
        touch(d)


def close_tank_cascade(tank, to_status):
    """Tank -> TEMPORARILY_CLOSED or PERMANENTLY_CLOSED.

    Both paths cancel the tank's REQUESTED/SCHEDULED orders (with the linked
    re-test deficiency fallback); PERMANENT additionally retires components
    in IN_SERVICE/DEFICIENT to OUT_OF_SERVICE.
    """
    if tank["status"] != to_status:
        tank["status"] = to_status
        touch(tank)
    for o in sorted(store.service_orders.values(), key=lambda o: o["_seq"]):
        if o["tank_system_id"] == tank["id"] and o["status"] in ("REQUESTED", "SCHEDULED"):
            cancel_order_cascade(o)
    if to_status == "PERMANENTLY_CLOSED":
        for c in sorted(store.components.values(), key=lambda c: c["_seq"]):
            if c["tank_system_id"] == tank["id"] and c["status"] in ("IN_SERVICE", "DEFICIENT"):
                c["status"] = "OUT_OF_SERVICE"
                touch(c)


def create_deficiency(facility_id, tank_system_id, component_id,
                      source_service_order_id, origin, period_month,
                      severity, description):
    """Open a deficiency (status OPEN), fix its correction_deadline at
    created_at + SEVERITY_DAYS[severity], and mark a referenced component
    DEFICIENT (component state machine: IN_SERVICE -> DEFICIENT on a
    deficiency referencing it being opened)."""
    d = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_id": facility_id,
        "tank_system_id": tank_system_id,
        "component_id": component_id,
        "source_service_order_id": source_service_order_id,
        "verified_by_service_order_id": None,
        "origin": origin,
        "period_month": period_month,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "escalated_at": None,
    }
    d.update(new_common_fields())
    d["correction_deadline"] = d["created_at"] + days(SEVERITY_DAYS[severity])
    store.deficiencies[d["id"]] = d
    if component_id:
        comp = store.components.get(component_id)
        if comp is not None and comp["status"] == "IN_SERVICE":
            comp["status"] = "DEFICIENT"
            touch(comp)
    return d


def create_release_event(facility_id, tank_system_id, discovered_at, source_description):
    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_id": facility_id,
        "tank_system_id": tank_system_id,
        "discovered_at": discovered_at,
        "source_description": source_description,
        "report_deadline": discovered_at + days(1),  # REPORT_WINDOW_HOURS = 24
        "reported_to_state_at": None,
        "late_notification": False,
        "status": "SUSPECTED",
    }
    r.update(new_common_fields())
    store.release_events[r["id"]] = r
    return r
