"""Shared HTTP helpers for the route modules."""
from flask import request

import store
from core import fail, ok_list, ok_object, pagination, read_only

PREFIX = "/senior-games"

TERMINAL_STATES = {
    "sport_entry": ("REJECTED", "WITHDRAWN"),
    "competition_result": ("VOIDED",),
    "age_group_record": ("REJECTED", "SUPERSEDED"),
    "village_stay": ("COMPLETED", "CANCELLED"),
    "sponsorship_commitment": ("WITHDRAWN",),
}
ATHLETE_TERMINAL_STATES = ("WITHDRAWN", "EXPIRED")


def obj(row, status=200):
    return ok_object(store.CLOCK, store.serialize(row), status)


def payload(body, status=200):
    return ok_object(store.CLOCK, body, status)


def collection(kind, filter_names):
    read_only()
    limit, offset = pagination()
    criteria = {}
    for name in filter_names:
        value = request.args.get(name)
        if value is not None:
            criteria[name] = value
    rows = store.where(kind, **criteria)
    page = rows[offset : offset + limit]
    return ok_list(store.CLOCK, store.serialize_all(page), limit, offset, len(rows))


def single(kind, row_id):
    read_only()
    return obj(store.must_get(kind, row_id))


def guard_terminal(kind, row):
    if row["status"] in TERMINAL_STATES.get(kind, ()):
        fail("ERR_ALREADY_TERMINAL")


def guard_athlete_terminal(athlete):
    if athlete["registration_status"] in ATHLETE_TERMINAL_STATES:
        fail("ERR_ALREADY_TERMINAL")


def guard_state(current, allowed):
    if current not in allowed:
        fail("ERR_INVALID_STATE_TRANSITION")


def guard_owner(role, user_id, owner_id, owning_role="Athlete"):
    if role == owning_role and user_id != owner_id:
        fail("ERR_NOT_RESOURCE_OWNER")
