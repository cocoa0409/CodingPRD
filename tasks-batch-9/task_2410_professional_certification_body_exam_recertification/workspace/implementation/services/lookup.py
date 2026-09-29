"""Existence resolution.

Validation layer 3 (path identifiers) and layer 4 (foreign identifiers carried in
a request body) both resolve records here, each raising the 404 that matches the
entity being addressed.
"""

from db import DB
from errors import ApiError


def _get(table, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    record = table.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def program(identifier):
    return _get(DB.programs, identifier, "ERR_PROGRAM_NOT_FOUND")


def item(identifier):
    return _get(DB.items, identifier, "ERR_ITEM_NOT_FOUND")


def form(identifier):
    return _get(DB.forms, identifier, "ERR_FORM_NOT_FOUND")


def candidate(identifier):
    return _get(DB.candidates, identifier, "ERR_CANDIDATE_NOT_FOUND")


def application(identifier):
    return _get(DB.applications, identifier, "ERR_APPLICATION_NOT_FOUND")


def session(identifier):
    return _get(DB.sessions, identifier, "ERR_SESSION_NOT_FOUND")


def registration(identifier):
    return _get(DB.registrations, identifier, "ERR_REGISTRATION_NOT_FOUND")


def incident(identifier):
    return _get(DB.incidents, identifier, "ERR_INCIDENT_NOT_FOUND")


def certificant(identifier):
    return _get(DB.certificants, identifier, "ERR_CERTIFICANT_NOT_FOUND")


def cycle(identifier):
    return _get(DB.cycles, identifier, "ERR_CYCLE_NOT_FOUND")


def activity(identifier):
    return _get(DB.activities, identifier, "ERR_ACTIVITY_NOT_FOUND")


def case(identifier):
    return _get(DB.cases, identifier, "ERR_CASE_NOT_FOUND")


# --- convenience joins ------------------------------------------------------

def program_of_certificant(certificant_record):
    return DB.programs[certificant_record["program_id"]]


def program_of_cycle(cycle_record):
    holder = DB.certificants[cycle_record["certificant_id"]]
    return DB.programs[holder["program_id"]]


def certificant_of_cycle(cycle_record):
    return DB.certificants[cycle_record["certificant_id"]]


def cycle_of_activity(activity_record):
    return DB.cycles[activity_record["cycle_id"]]
