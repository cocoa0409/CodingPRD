"""The episode cascades of PRD 2.9 -- bed return (C1), discharge (C4),
readmission -- driven in the exact sequence the PRD narrates."""

import clock
import derived
import store
from domain import beds, compliance, kits, meals

NON_TERMINAL_DELIVERY_STATES = (
    "PENDING_AUTHORIZATION",
    "AUTHORIZED",
    "OUT_FOR_DELIVERY",
    "REFUSED",
)


def convert_to_bed_return(escalation, episode):
    """CASCADE C1: the program's deepest single operation (PRD 3.8)."""
    # link 0 -- the escalation reaches its terminal converted state
    escalation["status"] = "BED_RETURN_CONVERTED"
    store.touch(escalation)

    # the earliest-created held reservation is occupied when still inside its window
    reservation = beds.earliest_held_reservation(episode["id"])
    if reservation is not None:
        expires_at = clock.parse_iso(reservation["hold_expires_at"])
        if clock.now_dt() <= expires_at:
            beds.occupy(reservation)

    # link 1 -- the episode returns to the facility
    episode["status"] = "RETURNED_TO_FACILITY"
    episode["returned_at"] = clock.now_raw()
    store.touch(episode)

    # every still-missing service date is back-filled as PENDING
    compliance.backfill(episode)

    # link 2 + 3 + 4 -- kit into refurbishment, today's day scored, claims voided
    kits.release_for_episode(episode)

    meals.suspend_active_plans(episode["id"])
    cancel_open_delivery_orders(episode["id"])


def cancel_open_delivery_orders(episode_id):
    for order in derived.episode_delivery_orders(episode_id):
        if order["status"] in NON_TERMINAL_DELIVERY_STATES:
            order["status"] = "CANCELLED"
            store.touch(order)


def begin_discharge(episode):
    episode["status"] = "DISCHARGE_PENDING"
    store.touch(episode)
    compliance.backfill(episode)
    kits.release_for_episode(episode)


def discharge(episode):
    """CASCADE C4: the program's closing cascade (PRD 3.9)."""
    episode["status"] = "DISCHARGED"
    episode["discharged_at"] = clock.now_raw()
    store.touch(episode)

    # link 1 -- every visit still open on the scheduling axis is cancelled
    for visit in store.ordered(derived.episode_visits(episode["id"])):
        if visit["scheduling_status"] in ("SCHEDULED", "EN_ROUTE"):
            visit["scheduling_status"] = "CANCELLED"
            store.touch(visit)

    # link 2 -- every compliance day still PENDING is finalized
    compliance.finalize_all_pending(episode)

    # link 3 -- meal plans end and their credits are recomputed from that set
    meals.end_plans_on_discharge(episode["id"])

    patient = store.DB.patients.get(episode["patient_id"])
    if patient is not None:
        patient["status"] = "DISCHARGED"
        store.touch(patient)
    referral = store.DB.referrals.get(episode["referral_id"])
    if referral is not None:
        referral["status"] = "CLOSED"
        store.touch(referral)


def readmit(episode):
    episode["status"] = "ACTIVE"
    episode["readmission_count"] = episode["readmission_count"] + 1
    store.touch(episode)
    beds.release_for_episode(episode["id"])
    meals.resume_suspended_plans(episode["id"])
    compliance.backfill(episode)
