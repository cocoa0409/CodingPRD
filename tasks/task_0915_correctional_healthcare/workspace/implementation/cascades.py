"""Cascades A-E and the shared multi-row state helpers (PRD 2.9)."""

import calc
import store
from constants import MAX_NO_SHOW_COUNT, OPEN_SICK_CALL_STATES


def orders_of(inmate_id, statuses=None):
    rows = [o for o in store.medication_orders.values() if o["inmate_id"] == inmate_id]
    if statuses is not None:
        rows = [o for o in rows if o["status"] in statuses]
    return store.sort_rows(rows)


def referrals_of(inmate_id, statuses=None):
    rows = [r for r in store.specialty_referrals.values() if r["inmate_id"] == inmate_id]
    if statuses is not None:
        rows = [r for r in rows if r["status"] in statuses]
    return store.sort_rows(rows)


def trips_of(referral_id, statuses=None):
    rows = [t for t in store.transport_orders.values() if t["referral_id"] == referral_id]
    if statuses is not None:
        rows = [t for t in rows if t["status"] in statuses]
    return store.sort_rows(rows)


def void_scheduled_doses(order):
    """Every SCHEDULED administration under the order becomes VOIDED."""
    rows = store.sort_rows([a for a in store.medication_administrations.values()
                            if a["order_id"] == order["id"] and a["outcome"] == "SCHEDULED"],
                           key="scheduled_at")
    for row in rows:
        row["outcome"] = "VOIDED"
        row["acted_at"] = store.now()
        row["timing_class"] = None
        store.touch(row)
    return rows


def retire_order(order, landing_status):
    """Discontinue (death / explicit / supersede) or complete (release) an order.

    Voids the remaining scheduled doses, resets both consecutive counters, drops
    the escalation flag and recomputes adherence over the surviving denominator.
    The order row itself is touched exactly once.
    """
    order["status"] = landing_status
    void_scheduled_doses(order)
    order["consecutive_missed_count"] = 0
    order["consecutive_refused_count"] = 0
    order["escalated_to_prescriber"] = False
    calc.recompute_adherence(order)
    store.touch(order)
    return order


def cancel_open_sick_calls(inmate_id):
    for row in store.sort_rows([s for s in store.sick_calls.values()
                                if s["inmate_id"] == inmate_id
                                and s["status"] in OPEN_SICK_CALL_STATES]):
        row["status"] = "CANCELLED"
        store.touch(row)


def resolve_enrollments(inmate_id, statuses):
    for row in store.sort_rows([e for e in store.chronic_enrollments.values()
                                if e["inmate_id"] == inmate_id and e["status"] in statuses]):
        row["status"] = "RESOLVED"
        row["next_due_date"] = None
        store.touch(row)


# --- Cascade A: in-custody death, five levels ------------------------------
def cascade_death(inmate, death_at, manner):
    inmate["custody_status"] = "DECEASED"        # L1
    inmate["records_state"] = "FROZEN"           # L2
    store.touch(inmate)

    for order in orders_of(inmate["id"], ("ACTIVE", "HELD")):
        retire_order(order, "DISCONTINUED")      # L3 + L4 + L5

    cancel_open_sick_calls(inmate["id"])

    for referral in referrals_of(inmate["id"], ("REQUESTED", "PENDING_UR", "AUTHORIZED", "SCHEDULED")):
        referral["status"] = "CANCELLED"
        store.touch(referral)
        for trip in trips_of(referral["id"], ("DRAFT", "ESCORT_ASSIGNED", "DISPATCHED")):
            trip["status"] = "CANCELLED"
            trip["cancel_reason"] = "CLINICAL_CHANGE"
            store.touch(trip)

    resolve_enrollments(inmate["id"], ("ACTIVE", "LAPSED"))

    for plan in store.sort_rows([p for p in store.release_plans.values()
                                 if p["inmate_id"] == inmate["id"]
                                 and p["status"] in ("DRAFT", "FINALIZED")]):
        plan["status"] = "VOIDED"
        store.touch(plan)

    review = store.base_row()
    review.update({
        "inmate_id": inmate["id"],
        "death_at": death_at,
        "manner": manner,
        "due_at": calc.mortality_review_due_at(death_at),
        "corrective_action_count": 0,
        "corrective_actions": [],
        "closed_at": None,
        "closed_late": False,
        "status": "OPEN",
    })
    store.mortality_reviews[review["id"]] = review
    return review


# --- Cascade B: release, four levels ---------------------------------------
def cascade_release(inmate):
    inmate["custody_status"] = "RELEASED"        # records_state is left untouched
    store.touch(inmate)

    for plan in store.sort_rows([p for p in store.release_plans.values()
                                 if p["inmate_id"] == inmate["id"]
                                 and p["status"] == "FINALIZED"]):
        plan["status"] = "EXECUTED"              # L1
        plan["records_packet_ready"] = True
        store.touch(plan)

    for order in orders_of(inmate["id"], ("ACTIVE", "HELD")):
        retire_order(order, "COMPLETED")         # L2 + L3 + L4

    resolve_enrollments(inmate["id"], ("ACTIVE",))
    cancel_open_sick_calls(inmate["id"])
    return inmate


# --- Cascade D: transport no-show ------------------------------------------
def cascade_no_show(trip, referral):
    trip["status"] = "NO_SHOW"                                   # L1
    store.touch(trip)

    referral["status"] = "AUTHORIZED"                            # L2
    referral["no_show_count"] = calc.referral_no_show_count(referral["id"])
    store.touch(referral)

    if referral["no_show_count"] >= MAX_NO_SHOW_COUNT:           # L3
        referral["status"] = "CANCELLED"
        store.touch(referral)
        for other in trips_of(referral["id"], ("DRAFT", "ESCORT_ASSIGNED", "DISPATCHED")):
            other["status"] = "CANCELLED"
            other["cancel_reason"] = "CLINICAL_CHANGE"
            store.touch(other)
    return trip
