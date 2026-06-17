"""Reservation lifecycle helpers shared across routes (PRD §3)."""
import db
from db import touch
from services import calc
from services.aggregates import recompute_outstanding_balance


def stamp_estimate(reservation):
    """Run estimate_quote and stamp quote_estimate_total_cents (PRD §3.2).

    Also records the estimate's discounted base / gratuity privately so the
    cancellation penalty base (quote total - gratuity - tolls) is exact.
    """
    vclass = db.vehicle_classes[reservation["vehicle_class_id"]]
    account = db.corporate_accounts[reservation["corporate_account_id"]]
    total, discounted_base, gratuity = calc.estimate_quote(reservation, vclass, account)
    reservation["quote_estimate_total_cents"] = total
    reservation["_estimate_discounted_base"] = discounted_base
    reservation["_estimate_gratuity"] = gratuity


def run_final_settlement(reservation):
    """Run final_settlement and stamp final_total_cents (PRD §3.4, §3.5)."""
    vclass = db.vehicle_classes[reservation["vehicle_class_id"]]
    account = db.corporate_accounts[reservation["corporate_account_id"]]
    reservation["final_total_cents"] = calc.final_settlement(reservation, vclass, account)


def active_assignment_for(reservation_id):
    for a in db.assignments.values():
        if a["reservation_id"] == reservation_id and a["status"] == "ACTIVE":
            return a
    return None


def open_farmout_for(reservation_id):
    """An OFFERED or ACCEPTED farm-out order for the reservation, if any."""
    for fo in db.farm_out_orders.values():
        if fo["reservation_id"] == reservation_id and fo["status"] in ("OFFERED", "ACCEPTED"):
            return fo
    return None


def release_assignment(assignment):
    assignment["status"] = "RELEASED"
    touch(assignment)


def chauffeur_off_duty(chauffeur):
    chauffeur["status"] = "OFF_DUTY"
    chauffeur["active_assignment_id"] = None
    touch(chauffeur)


def invoice_billable_amount(reservation):
    """The amount that makes a reservation billable, or None (PRD §3.8)."""
    if reservation["trip_status"] == "COMPLETED":
        return reservation.get("final_total_cents")
    if reservation["trip_status"] == "CANCELLED":
        return reservation.get("cancellation_fee_cents")
    return None
