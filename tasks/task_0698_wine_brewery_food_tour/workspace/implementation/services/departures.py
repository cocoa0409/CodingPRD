"""Departure-derived figures (PRD §3.3).

seats_taken        = sum of party_size over Bookings in {RESERVED, PAID, CHECKED_IN}
expected_headcount = sum of party_size over Bookings in {RESERVED, PAID}
"""
from db import db

SEATS_TAKEN_STATES = {"RESERVED", "PAID", "CHECKED_IN"}
EXPECTED_STATES = {"RESERVED", "PAID"}


def _bookings_for(departure_id):
    return [b for b in db.bookings.values() if b["departure_id"] == departure_id]


def compute_seats_taken(departure_id):
    return sum(b["party_size"] for b in _bookings_for(departure_id)
               if b["status"] in SEATS_TAKEN_STATES)


def compute_expected_headcount(departure_id):
    return sum(b["party_size"] for b in _bookings_for(departure_id)
               if b["status"] in EXPECTED_STATES)


def checked_in_headcount(departure_id):
    return sum(b["party_size"] for b in _bookings_for(departure_id)
               if b["status"] == "CHECKED_IN")
