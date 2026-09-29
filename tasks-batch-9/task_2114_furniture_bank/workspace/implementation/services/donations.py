"""Donation intake, warehouse grading and the quarantine protocol
(PRD 3.4, 3.5), plus the two resource-window conflict predicates.
"""

from datetime import timedelta

from core import (
    QUARANTINE_DAYS_LIVE_PEST, QUARANTINE_DAYS_STANDARD,
    VOLUNTEER_REST_BUFFER_MINUTES, clock, days,
)
from db import db, new_entity, touch, items_of_offer
from services.delivery import bed_bug_intake_cascade


# --------------------------------------------------------------------------
# Resource windows
# --------------------------------------------------------------------------
def truck_window_conflict(truck_id, start, end, exclude_offer_id=None):
    """Half-open [start, end) semantics - touching endpoints do not overlap."""
    for offer in db.donation_offers.values():
        if offer["id"] == exclude_offer_id:
            continue
        if offer["truck_id"] != truck_id or offer["status"] != "PICKUP_SCHEDULED":
            continue
        if start < offer["pickup_window_end"] and offer["pickup_window_start"] < end:
            return True
    for run in db.delivery_runs.values():
        if run["truck_id"] != truck_id:
            continue
        if run["status"] not in ("PLANNED", "CREWED", "DISPATCHED"):
            continue
        if start < run["window_end"] and run["window_start"] < end:
            return True
    return False


def volunteer_rest_conflict(volunteer_id, new_run):
    """Closed interval plus a 60 minute buffer on both sides."""
    buffer = timedelta(minutes=VOLUNTEER_REST_BUFFER_MINUTES)
    for assignment in db.crew_assignments.values():
        if assignment["volunteer_id"] != volunteer_id:
            continue
        if assignment["status"] not in ("INVITED", "CONFIRMED"):
            continue
        other = db.delivery_runs.get(assignment["run_id"])
        if other is None or other["id"] == new_run["id"]:
            continue
        if other["status"] not in ("PLANNED", "CREWED", "DISPATCHED"):
            continue
        if new_run["window_start"] <= other["window_end"] + buffer and \
                other["window_start"] <= new_run["window_end"] + buffer:
            return True
    return False


# --------------------------------------------------------------------------
# Warehouse intake (PRD 3.5)
# --------------------------------------------------------------------------
def recompute_offer_counts(offer):
    items = items_of_offer(offer["id"])
    offer["accepted_item_count"] = len([i for i in items if i["decision"] == "ACCEPTED"])
    offer["rejected_item_count"] = len([i for i in items if i["decision"] == "REJECTED"])


def perform_intake(offer, inspections, actor_user_id):
    now = clock.now()
    by_id = dict((insp["item_id"], insp) for insp in inspections)
    accepted_items = [i for i in items_of_offer(offer["id"]) if i["decision"] == "ACCEPTED"]

    live_pest = any(insp["live_pest_observed"] for insp in inspections)
    soft_accepted = any(i["soft_surface"] for i in accepted_items)
    risk_branch = live_pest or soft_accepted

    for item in accepted_items:
        inspection = by_id[item["id"]]
        grade = inspection["graded_condition"]
        item["graded_condition"] = grade
        if grade == "D":
            # D-graded pieces never become stock.
            item["decision"] = "REJECTED"
            item["reject_reason"] = "CONDITION_BELOW_MIN"
            touch(item)
            continue
        touch(item)

        # A stock unit's canonical starting state is QUARANTINED; the landing
        # edge is applied inside the very request that mints the unit.
        unit = new_entity(
            donation_item_id=item["id"],
            category=item["category"],
            condition=grade,
            cubic_feet=item["cubic_feet"],
            status="QUARANTINED",
            reserved_for_voucher_line_id=None,
            available_since=None,
        )
        db.inventory_items[unit["id"]] = unit

        if not risk_branch:
            unit["status"] = "AVAILABLE"
            unit["available_since"] = now
            touch(unit)
        elif item["soft_surface"] and live_pest:
            unit["status"] = "DISPOSED"
            touch(unit)

    recompute_offer_counts(offer)
    offer["inspector_user_id"] = actor_user_id

    if risk_branch:
        offer["status"] = "QUARANTINED"
        offer["quarantine_started_at"] = now
        dwell = QUARANTINE_DAYS_LIVE_PEST if live_pest else QUARANTINE_DAYS_STANDARD
        offer["quarantine_release_due_at"] = now + days(dwell)
    else:
        offer["status"] = "INSPECTED"
    touch(offer)

    if live_pest:
        bed_bug_intake_cascade(db.trucks.get(offer["truck_id"]))


def release_quarantine(offer):
    now = clock.now()
    item_ids = set(i["id"] for i in items_of_offer(offer["id"]))
    for unit in db.inventory_items.values():
        if unit["donation_item_id"] in item_ids and unit["status"] == "QUARANTINED":
            unit["status"] = "AVAILABLE"
            unit["available_since"] = now
            touch(unit)
    offer["status"] = "RELEASED"
    touch(offer)
