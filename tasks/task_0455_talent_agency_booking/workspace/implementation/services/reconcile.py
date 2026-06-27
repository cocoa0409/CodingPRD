"""Derived-field reconciliation for Agency and Talent (PRD §2.5)."""
from db import db
from services.common import touch


def recompute_escrow(agency):
    """escrow_balance_cents = sum(held_cents) over this agency's HELD entries."""
    total = 0
    for entry in db.commission_entries.values():
        if entry["agency_id"] == agency["id"] and entry["status"] == "HELD":
            total += entry["held_cents"]
    agency["escrow_balance_cents"] = total


def recompute_booked_days_agency(agency):
    total = 0
    for booking in db.bookings.values():
        if booking["_agency_id"] == agency["id"] and booking["booking_status"] in (
            "CONFIRMED",
            "COMPLETED",
        ):
            total += booking["_day_span"]
    agency["booked_day_count"] = total


def recompute_booked_days_talent(talent):
    total = 0
    for booking in db.bookings.values():
        if booking["talent_id"] == talent["id"] and booking["booking_status"] in (
            "CONFIRMED",
            "COMPLETED",
        ):
            total += booking["_day_span"]
    talent["booked_day_count"] = total


def reconcile_agency(agency, bump=True):
    """Recompute both derived agency figures; bump version when touched."""
    recompute_escrow(agency)
    recompute_booked_days_agency(agency)
    if bump:
        touch(agency)


def reconcile_talent_booked(talent, bump=True):
    recompute_booked_days_talent(talent)
    if bump:
        touch(talent)
