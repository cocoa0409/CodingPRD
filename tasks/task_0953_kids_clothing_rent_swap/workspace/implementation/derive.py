"""Computed aggregates (SCAFFOLD calculations: aggregation family)."""

import constants as K
import store
import timeutil


# ---------- member money -------------------------------------------------

def member_credit_balance(member_id):
    total = 0
    for entry in store.db["credit_entries"].values():
        if entry["member_id"] == member_id and entry["status"] in ("AVAILABLE", "PARTIALLY_APPLIED"):
            total += entry["remaining_cents"]
    return total


def member_outstanding_balance(member_id):
    total = 0
    for charge in store.db["charge_entries"].values():
        if charge["member_id"] == member_id and charge["status"] in ("ASSESSED", "PARTIALLY_SETTLED"):
            total += charge["net_due_cents"]
    return total


# ---------- pause budgets ------------------------------------------------

def pause_days_used_period(member_id):
    floor = timeutil.add_days(timeutil.now(), -K.PAUSE_PERIOD_LENGTH_DAYS)
    total = 0
    for req in store.db["pause_requests"].values():
        if req["member_id"] != member_id:
            continue
        if req["status"] not in ("ACTIVE", "ENDED"):
            continue
        if req["start_at"] > floor:
            total += req["days_requested"]
    return total


def pause_days_used_lifetime(member_id):
    total = 0
    for req in store.db["pause_requests"].values():
        if req["member_id"] == member_id and req["status"] in ("ACTIVE", "ENDED"):
            total += req["days_requested"]
    return total


def completed_cycles(member_id):
    return len([c for c in store.db["cycles"].values()
                if c["member_id"] == member_id and c["status"] == "CLOSED"])


# ---------- box slots ----------------------------------------------------

OCCUPYING_FULFILLMENT = ("ALLOCATED", "SHIPPED", "WITH_MEMBER", "RETURNING")


def box_items(box_id):
    return [i for i in store.all_rows("box_items") if i["box_id"] == box_id]


def box_occupied(box_id):
    return len([i for i in box_items(box_id) if i["fulfillment_status"] in OCCUPYING_FULFILLMENT])


def box_permanently_consumed(box_id):
    return len([i for i in box_items(box_id) if i["settlement_status"] == "BOUGHT_OUT"])


def box_slots_free(box):
    return box["slot_capacity"] - box_occupied(box["id"]) - box_permanently_consumed(box["id"])


# ---------- cycle aggregates --------------------------------------------

def cycle_boxes(cycle_id):
    return [b for b in store.all_rows("boxes") if b["cycle_id"] == cycle_id]


def cycle_box_items(cycle_id):
    out = []
    for box in cycle_boxes(cycle_id):
        out.extend(box_items(box["id"]))
    out.sort(key=lambda i: (i["slot_index"], store.order_key(i)))
    return out


def cycle_slots_occupied(cycle_id):
    return len([i for i in cycle_box_items(cycle_id)
                if i["fulfillment_status"] in OCCUPYING_FULFILLMENT])


def cycle_swap_requests(cycle_id):
    return [s for s in store.all_rows("swap_requests") if s["cycle_id"] == cycle_id]


def cycle_swaps_used(cycle_id):
    return len([s for s in cycle_swap_requests(cycle_id) if s["status"] == "FULFILLED"])


def swap_entitlement_remaining(cycle, plan):
    requests = cycle_swap_requests(cycle["id"])
    used = len([s for s in requests if s["status"] == "FULFILLED"])
    in_flight = len([s for s in requests if s["status"] in ("SUBMITTED", "APPROVED")])
    return plan["swaps_per_cycle"] - used - in_flight


def cycle_paused_days(cycle):
    total = 0
    for req in store.all_rows("pause_requests"):
        if req["member_id"] != cycle["member_id"]:
            continue
        if req["status"] not in ("ACTIVE", "ENDED"):
            continue
        total += timeutil.days_overlap(
            req["start_at"], req["end_at"], cycle["start_at"], cycle["return_due_at"]
        )
    return total


def cycle_damage_fee(cycle_id):
    return sum(i["damage_fee_cents"] for i in cycle_box_items(cycle_id))


def cycle_credit_applied(cycle_id):
    total = 0
    for charge in store.db["charge_entries"].values():
        if charge.get("cycle_id") == cycle_id:
            total += charge["credit_applied_cents"]
    return total


def member_charges(member_id):
    return [c for c in store.all_rows("charge_entries") if c["member_id"] == member_id]


def member_credits(member_id):
    return [c for c in store.all_rows("credit_entries") if c["member_id"] == member_id]


def member_box_items(member_id):
    out = []
    for box in store.all_rows("boxes"):
        if box["member_id"] == member_id:
            out.extend(box_items(box["id"]))
    return out
