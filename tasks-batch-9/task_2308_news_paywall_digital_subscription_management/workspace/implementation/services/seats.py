"""Seat admission by aggregate peak concurrency (PRD 3.9)."""
from datetime import timedelta

import config
from clock import clock, parse_date
from db import db, new_entity
from response import mark_created, touch
from services.derive import (
    funding_subscription_live,
    group_seats,
    peak_occupancy,
    recompute_group_counters,
    seat_intervals,
)
from services.entitlement import entitlement_source


def interval_invalid(starts_on, ends_on):
    start = parse_date(starts_on)
    if start < clock.date():
        return True
    if ends_on is not None and parse_date(ends_on) <= start:
        return True
    return False


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open intersection; a null end extends indefinitely."""
    if a_end is not None and a_end <= b_start:
        return False
    if b_end is not None and b_end <= a_start:
        return False
    return True


def reader_duplicate(group_account_id, reader_id, starts_on, ends_on):
    start = parse_date(starts_on)
    end = parse_date(ends_on) if ends_on else None
    for seat in group_seats(group_account_id):
        if seat["reader_id"] != reader_id:
            continue
        if seat["status"] not in config.SEAT_OCCUPYING_STATUSES:
            continue
        other_start = parse_date(seat["starts_on"])
        other_end = parse_date(seat["ends_on"]) if seat.get("ends_on") else None
        if _overlaps(start, end, other_start, other_end):
            return True
    return False


def capacity_exceeded(group, starts_on, ends_on):
    candidate = (parse_date(starts_on), parse_date(ends_on) if ends_on else None)
    intervals = seat_intervals(group["id"]) + [candidate]
    return peak_occupancy(intervals) > group["seat_capacity"]


def invite(group, reader_id, starts_on, ends_on):
    today = clock.date()
    seat = new_entity()
    seat.update(
        {
            "group_account_id": group["id"],
            "reader_id": reader_id,
            "status": "INVITED",
            "starts_on": starts_on,
            "ends_on": ends_on,
            "invited_on": today.isoformat(),
            "invite_expires_on": (
                today + timedelta(days=config.SEAT_INVITE_EXPIRY_DAYS)
            ).isoformat(),
            "claimed_on": None,
        }
    )
    db.seats[seat["id"]] = seat
    mark_created(seat)

    recompute_group_counters(group)
    touch(group)
    reader = db.readers.get(reader_id)
    if reader is not None:
        touch(reader)
    return seat


def domain_matches(reader, group):
    email = reader.get("email")
    if not email:
        return False
    return email.lower().endswith("@" + group["allowed_email_domain"].lower())


def claim(seat, group, reader):
    seat["status"] = "ACTIVE"
    seat["claimed_on"] = clock.date().isoformat()
    touch(seat)
    recompute_group_counters(group)
    touch(group)
    reader["entitlement_source"] = entitlement_source(reader)
    touch(reader)
    return seat


def reclaim(seat, group):
    seat["status"] = "RECLAIMED"
    seat["ends_on"] = clock.date().isoformat()
    touch(seat)
    recompute_group_counters(group)
    touch(group)
    reader = db.readers.get(seat["reader_id"])
    if reader is not None:
        reader["entitlement_source"] = entitlement_source(reader)
        touch(reader)
    return seat


def funding_is_live(group):
    return funding_subscription_live(group["id"]) is not None
