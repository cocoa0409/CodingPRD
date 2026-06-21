"""Reservation lifecycle helpers, including the lazy clock-driven transitions
REQUESTED->EXPIRED and CONFIRMED->NO_SHOW (PRD §3.5, §3.9).

These system transitions are applied on observation: whenever a reservation is
read or acted upon, we first reconcile it against the current server clock.
"""
import db
from clock import current_utc, parse_iso

RESERVATION_BUFFER_MIN = 15  # turnaround buffer for overlap checks


def observe(res):
    """Apply clock-driven system transitions to a single reservation in place."""
    now = current_utc()
    status = res["status"]
    if status == "REQUESTED":
        # clock PASSES window_start while still REQUESTED -> EXPIRED.
        # Strictly past: a REQUESTED reservation can still be confirmed at the
        # exact window_start instant (PRD §3.5: expiry only once the clock
        # "passes" window_start).
        if now > parse_iso(res["window_start"]):
            res["status"] = "EXPIRED"
            db.touch(res)
    elif status == "CONFIRMED":
        # clock passes window_end with no check-in -> NO_SHOW (deposit forfeited)
        if now >= parse_iso(res["window_end"]):
            res["status"] = "NO_SHOW"
            db.touch(res)


def observe_all():
    for res in db.reservations.values():
        observe(res)
