"""Derived order fields: money aggregates and production_posture (PRD 2.6, 2.9).

Posture is never set by a caller: it is recomputed from scratch from the current
persisted states of the order's children after every child mutation.
"""
import store
from errors import ApiError

FREEZING = ("ORDER_CANCELLED", "ORDER_CLOSED", "COMPONENT_QUARANTINE", "LABEL_VOID", "LABEL_STALE")
RESTRICTING = ("SUBMITTAL_REJECTED", "MATERIAL_INCOMPLETE", "MATERIAL_PREEMPTED",
               "ESCALATION_DISPUTED", "WITNESS_MISSING", "SITE_NOT_READY",
               "COMMISSIONING_INCOMPLETE", "ORDER_FULFILLED")


def _statuses(rows):
    return set(r.get("status") for r in rows)


def confirmed_witness_count(fat):
    return len([a for a in store.where("assignment", factory_acceptance_test_id=fat["id"])
                if a.get("status") == "CONFIRMED"])


def reason_codes(order):
    oid = order["id"]
    codes = []
    allocations = store.where("allocation", engineered_order_id=oid)
    labels = store.where("label", engineered_order_id=oid)
    drawings = store.where("drawing", engineered_order_id=oid)
    adjustments = store.where("adjustment", engineered_order_id=oid)
    fats = store.where("fat", engineered_order_id=oid)
    releases = store.where("release", engineered_order_id=oid)
    jobs = store.where("job", engineered_order_id=oid)
    ful = order.get("fulfillment_status")
    eng = order.get("engineering_status")
    label_states = _statuses(labels)
    alloc_states = _statuses(allocations)

    # --- freezing class, in the fixed evaluation order -----------------------
    if ful == "CANCELLED":
        codes.append("ORDER_CANCELLED")
    if eng == "ENG_CLOSED":
        codes.append("ORDER_CLOSED")
    if ful in ("PLANNING", "MATERIAL_ALLOCATED", "IN_PRODUCTION"):
        for a in allocations:
            if a.get("status") != "RELEASED":
                continue
            comp = store.get("component", a.get("long_lead_component_id"))
            if comp is not None and comp.get("status") == "QUARANTINED":
                codes.append("COMPONENT_QUARANTINE")
                break
    if "VOIDED" in label_states and "ISSUED" not in label_states and ful in ("FAT_COMPLETE", "SHIPPING"):
        codes.append("LABEL_VOID")
    if "STALE" in label_states and "ISSUED" not in label_states:
        codes.append("LABEL_STALE")

    # --- restricting class ---------------------------------------------------
    dstates = _statuses(drawings)
    if "REVISE_AND_RESUBMIT" in dstates and not ({"APPROVED", "APPROVED_AS_NOTED"} & dstates):
        codes.append("SUBMITTAL_REJECTED")
    if (ful == "PLANNING" and not ({"RESERVED", "COMMITTED"} & alloc_states)
            and "RELEASED" in alloc_states):
        codes.append("MATERIAL_INCOMPLETE")
    if "PREEMPTED" in alloc_states and "COMMITTED" not in alloc_states:
        codes.append("MATERIAL_PREEMPTED")
    if {"DISPUTED", "RECALCULATING"} & _statuses(adjustments):
        codes.append("ESCALATION_DISPUTED")
    for t in fats:
        if (t.get("status") == "BAY_SCHEDULED" and t.get("witness_required")
                and confirmed_witness_count(t) == 0):
            codes.append("WITNESS_MISSING")
            break
    for r in releases:
        found = False
        for sa in store.where("storage", shipment_release_id=r["id"]):
            if sa.get("status") == "OPEN":
                codes.append("SITE_NOT_READY")
                found = True
                break
        if found:
            break
    for j in jobs:
        if j.get("status") == "DEMOBILIZED_INCOMPLETE":
            codes.append("COMMISSIONING_INCOMPLETE")
            break
    if ful == "CLOSED":
        codes.append("ORDER_FULFILLED")
    return codes


def compute_posture(order):
    codes = reason_codes(order)
    if any(c in FREEZING for c in codes):
        posture = "FROZEN"
    elif codes:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return posture, sorted(codes)


def money(order):
    oid = order["id"]
    accepted = sum(a.get("adjustment_amount_cents") or 0
                   for a in store.where("adjustment", engineered_order_id=oid)
                   if a.get("status") == "ACCEPTED")
    credits = sum(c.get("credit_issued_cents") or 0
                  for c in store.where("claim", engineered_order_id=oid)
                  if c.get("status") == "SETTLED")
    billed = sum(r.get("stage_billing_cents") or 0
                 for r in store.where("release", engineered_order_id=oid)
                 if r.get("status") in ("IN_TRANSIT", "DELIVERED"))
    contract = order.get("contract_value_cents") or 0
    return {
        "contract_value_cents": contract,
        "escalation_accepted_total_cents": accepted,
        "warranty_credit_total_cents": credits,
        "net_contract_value_cents": contract + accepted - credits,
        "billed_to_date_cents": billed,
    }


def refresh(order):
    """Recompute every derived field on the order. The row's `version` is bumped
    only when a persisted value actually changes (PRD 2.4: version increments on
    every mutation *of that row*)."""
    if order is None:
        return None
    new = money(order)
    posture, codes = compute_posture(order)
    new["production_posture"] = posture
    new["posture_reason_codes"] = codes
    changed = False
    for k, v in new.items():
        if order.get(k) != v:
            order[k] = v
            changed = True
    if changed:
        store.touch("order", order)
    return order


def refresh_by_id(order_id):
    return refresh(store.get("order", order_id))


def check_posture_blocked(order):
    """Rung 39: the five posture-gated operations reject a FROZEN posture."""
    refresh(order)
    if order.get("production_posture") == "FROZEN":
        raise ApiError("ERR_POSTURE_BLOCKED",
                       "order posture is FROZEN: %s" % ", ".join(order.get("posture_reason_codes") or []))
