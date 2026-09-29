"""Shared route helpers: existence resolution (rungs 7-26), the state band
(rungs 34-41) and the cross-entity cascades of section 3."""
from flask import request

import calc
import clock
import posture
import store
from errors import ApiError, NOT_FOUND

TERMINAL = {
    "drawing": {"APPROVED", "APPROVED_AS_NOTED", "VOID"},
    "adjustment": {"ACCEPTED", "WITHDRAWN"},
    "allocation": {"CONSUMED", "RELEASED", "PREEMPTED"},
    "fat": {"PASSED", "ABANDONED"},
    "assignment": {"WAIVED", "RELEASED"},
    "label": {"ISSUED", "VOIDED"},
    "report": {"SUPERSEDED"},
    "release": {"DELIVERED", "CANCELLED"},
    "storage": {"CLOSED", "WAIVED"},
    "job": {"COMPLETE", "CANCELLED"},
    "punch": {"CLOSED", "REJECTED"},
    "claim": {"SETTLED", "REJECTED"},
    "failure_report": {"RETRACTED"},
    "component": {"OBSOLETE"},
    "supplier": {"SUSPENDED"},
}


# --------------------------------------------------------------------------- #
# existence resolution
# --------------------------------------------------------------------------- #

def resolve(family, oid, parent_field=None, parent_id=None):
    row = store.get(family, oid)
    if row is None:
        raise ApiError(NOT_FOUND[family], "%s %s not found" % (family, oid))
    if parent_field is not None and row.get(parent_field) != parent_id:
        raise ApiError(NOT_FOUND[family], "%s %s not found under that parent" % (family, oid))
    return row


def resolve_body_ref(family, payload, field, required=True):
    """Resolve a body-borne foreign key. Existence (rungs 7-26) precedes the
    payload band, so a missing mandatory reference is reported here only as a
    missing field when the caller omitted it entirely."""
    value = payload.get(field)
    if value is None:
        if required:
            raise ApiError("ERR_MISSING_REQUIRED_FIELD", "%s is required" % field)
        return None
    if not isinstance(value, str):
        raise ApiError("ERR_FIELD_TYPE_INVALID", "%s must be of type string" % field)
    return resolve(family, value)


# --------------------------------------------------------------------------- #
# state band
# --------------------------------------------------------------------------- #

def check_state(family, row, allowed_sources):
    """Rung 34 then rung 35: terminal first, then illegal source."""
    status = row.get("status")
    if status in allowed_sources:
        return
    if status in TERMINAL.get(family, set()):
        raise ApiError("ERR_TERMINAL_STATE", "%s is in terminal state %s" % (family, status))
    raise ApiError("ERR_INVALID_STATE_TRANSITION",
                   "%s cannot move from %s" % (family, status))


def check_order_not_cancelled(order):
    """Rung 36."""
    if order.get("fulfillment_status") == "CANCELLED":
        raise ApiError("ERR_ORDER_CANCELLED", "the order is cancelled")


def check_order_fulfillment(order, allowed):
    """Rung 37."""
    if order.get("fulfillment_status") not in allowed:
        raise ApiError("ERR_ORDER_FULFILLMENT_STATE_INVALID",
                       "order fulfillment_status is %s" % order.get("fulfillment_status"))


def check_design_released(order):
    """Rung 38."""
    if order.get("engineering_status") != "DESIGN_RELEASED":
        raise ApiError("ERR_DESIGN_NOT_RELEASED", "the order's design is not released")


def check_engineering_open(order):
    """Rung 40."""
    if order.get("engineering_status") == "ENG_CLOSED":
        raise ApiError("ERR_ENGINEERING_CLOSED", "engineering is closed on this order")


ADMINISTRABLE = ("REQUESTED", "BAY_SCHEDULED", "WITNESS_CONFIRMED")


def check_fat_administrable(fat):
    """Rung 41."""
    if fat.get("status") not in ADMINISTRABLE:
        raise ApiError("ERR_FAT_NOT_ADMINISTRABLE",
                       "test in status %s does not admit witness administration" % fat.get("status"))


# --------------------------------------------------------------------------- #
# query helpers
# --------------------------------------------------------------------------- #

def qstr(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qint(name):
    value = qstr(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def qbool(name):
    value = qstr(name)
    if value is None:
        return None
    return value.lower() in ("true", "1", "yes")


def apply_filters(rows, filters):
    out = rows
    for field, value in filters.items():
        if value is None:
            continue
        out = [r for r in out if r.get(field) == value]
    return out


# --------------------------------------------------------------------------- #
# cascades
# --------------------------------------------------------------------------- #

def revert_cleared_releases(order, also_staged=False):
    """A release loses its freight clearance when the order has no ISSUED label."""
    states = ("CLEARED", "STAGED") if also_staged else ("CLEARED",)
    for r in store.where("release", engineered_order_id=order["id"]):
        if r.get("status") in states:
            r["status"] = "HELD"
            r["cleared_at"] = None
            store.touch("release", r)


def order_has_issued_label(order):
    for lab in store.where("label", engineered_order_id=order["id"]):
        if lab.get("status") == "ISSUED":
            return True
    return False


def stale_labels_for_revision(order, revision_round):
    """A newer submitted revision stales the order's labels (PRD 3.6)."""
    touched = False
    for lab in store.where("label", engineered_order_id=order["id"]):
        if lab.get("status") in ("GENERATED", "VERIFIED", "ISSUED") \
                and (lab.get("pinned_drawing_revision") or 0) < revision_round:
            if lab.get("status") == "VERIFIED":
                lab["verified_by_user_id"] = None
            lab["status"] = "STALE"
            lab["void_reason"] = "DRAWING_SUPERSEDED"
            store.touch("label", lab)
            touched = True
    if touched and not order_has_issued_label(order):
        revert_cleared_releases(order)
    return touched


def refresh_fat_witness_aggregate(fat):
    """A test in BAY_SCHEDULED advances once witnessing is satisfied."""
    count = posture.confirmed_witness_count(fat)
    changed = False
    if fat.get("confirmed_witness_count") != count:
        fat["confirmed_witness_count"] = count
        changed = True
    if fat.get("status") == "BAY_SCHEDULED" and (not fat.get("witness_required") or count >= 1):
        fat["status"] = "WITNESS_CONFIRMED"
        changed = True
    elif fat.get("status") == "WITNESS_CONFIRMED" and fat.get("witness_required") and count == 0:
        fat["status"] = "BAY_SCHEDULED"
        changed = True
    if changed:
        store.touch("fat", fat)
    return fat


def release_component_reservations(component, penalty=False):
    """Quarantine and suspension release every RESERVED allocation."""
    orders = set()
    for a in store.where("allocation", long_lead_component_id=component["id"]):
        if a.get("status") != "RESERVED":
            continue
        a["status"] = "RELEASED"
        a["released_at"] = clock.now_str()
        a["release_penalty_cents"] = 0
        store.touch("allocation", a)
        orders.add(a.get("engineered_order_id"))
    calc.refresh_component_buckets(component)
    store.touch("component", component)
    for oid in orders:
        auto_material_edges(store.get("order", oid))
    return orders


def auto_material_edges(order):
    """PLANNING <-> MATERIAL_ALLOCATED are system-driven (PRD 3.1)."""
    if order is None:
        return None
    if order.get("fulfillment_status") == "PLANNING":
        allocations = store.where("allocation", engineered_order_id=order["id"])
        committed = [a for a in allocations if a.get("status") == "COMMITTED"]
        reserved = [a for a in allocations if a.get("status") == "RESERVED"]
        if committed and not reserved:
            order["fulfillment_status"] = "MATERIAL_ALLOCATED"
            store.touch("order", order)
    elif order.get("fulfillment_status") == "MATERIAL_ALLOCATED":
        committed = [a for a in store.where("allocation", engineered_order_id=order["id"])
                     if a.get("status") == "COMMITTED"]
        if not committed:
            order["fulfillment_status"] = "PLANNING"
            store.touch("order", order)
    return posture.refresh(order)


def auto_close_order(order):
    """COMMISSIONING -> CLOSED is a compound, system-driven edge (PRD 3.1)."""
    if order is None or order.get("fulfillment_status") != "COMMISSIONING":
        return order
    jobs = store.where("job", engineered_order_id=order["id"])
    if not jobs:
        return order
    if any(j.get("status") not in ("COMPLETE", "CANCELLED") for j in jobs):
        return order
    if not any(j.get("status") == "COMPLETE" for j in jobs):
        return order
    releases = store.where("release", engineered_order_id=order["id"])
    if any(r.get("status") not in ("DELIVERED", "CANCELLED") for r in releases):
        return order
    order["fulfillment_status"] = "CLOSED"
    store.touch("order", order)
    return posture.refresh(order)


def rebill_stages(order):
    calc.stage_billing_allocation(order)
    for r in store.where("release", engineered_order_id=order["id"]):
        store.touch("release", r)
    posture.refresh(order)
