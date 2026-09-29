"""Entitlement resolution (PRD 3.3 "What counts as an entitlement")."""
from clock import clock, parse_date
from db import db


def subscription_entitles(sub):
    if sub.get("lifecycle_status") not in ("ACTIVE", "CANCEL_SCHEDULED"):
        return False
    if sub.get("dunning_status") == "FAILED_FINAL":
        return False
    access_until = sub.get("access_until")
    if access_until is not None and parse_date(access_until) < clock.date():
        return False
    return True


def seat_entitles(seat):
    if seat.get("status") != "ACTIVE":
        return False
    today = clock.date()
    starts_on = parse_date(seat["starts_on"])
    if today < starts_on:
        return False
    ends_on = seat.get("ends_on")
    if ends_on is not None and today >= parse_date(ends_on):
        return False
    return True


def reader_subscriptions(reader_id):
    return [s for s in db.subscriptions.values() if s.get("reader_id") == reader_id]


def reader_seats(reader_id):
    return [s for s in db.seats.values() if s.get("reader_id") == reader_id]


def entitlement_source(reader):
    """SUBSCRIPTION outranks SEAT; NONE when nothing is live."""
    reader_id = reader["id"]
    for sub in reader_subscriptions(reader_id):
        if subscription_entitles(sub):
            return "SUBSCRIPTION"
    for seat in reader_seats(reader_id):
        if seat_entitles(seat):
            return "SEAT"
    return "NONE"
