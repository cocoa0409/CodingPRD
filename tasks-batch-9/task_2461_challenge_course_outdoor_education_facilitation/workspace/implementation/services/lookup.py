"""Identifier resolution (PRD 2.8) and list filtering (PRD 2.3)."""
from flask import request

from db import store
from errors import ApiError, invalid
from validation import parse_date

_RESOLVERS = (
    ("course", "courses", "ERR_COURSE_NOT_FOUND"),
    ("element", "elements", "ERR_ELEMENT_NOT_FOUND"),
    ("facilitator", "facilitators", "ERR_FACILITATOR_NOT_FOUND"),
    ("inspection", "professional_inspections", "ERR_INSPECTION_NOT_FOUND"),
    ("operational_log", "operational_logs", "ERR_OPERATIONAL_LOG_NOT_FOUND"),
    ("group_client", "group_clients", "ERR_GROUP_CLIENT_NOT_FOUND"),
    ("booking", "bookings", "ERR_BOOKING_NOT_FOUND"),
    ("participant", "participants", "ERR_PARTICIPANT_NOT_FOUND"),
    ("program_block", "program_blocks", "ERR_PROGRAM_BLOCK_NOT_FOUND"),
    ("equipment", "belay_equipment", "ERR_EQUIPMENT_NOT_FOUND"),
    ("incident", "incidents", "ERR_INCIDENT_NOT_FOUND"),
    ("training_record", "training_records", "ERR_TRAINING_RECORD_NOT_FOUND"),
    ("block_assignment", "block_assignments", "ERR_BLOCK_ASSIGNMENT_NOT_FOUND"),
    ("observation", "weather_observations", "ERR_WEATHER_OBSERVATION_NOT_FOUND"),
)


def _make(collection, error_id):
    def resolve(identifier):
        row = getattr(store, collection).get(identifier) if isinstance(identifier, str) else None
        if row is None:
            raise ApiError(error_id)
        return row
    return resolve


get_course = _make("courses", "ERR_COURSE_NOT_FOUND")
get_element = _make("elements", "ERR_ELEMENT_NOT_FOUND")
get_facilitator = _make("facilitators", "ERR_FACILITATOR_NOT_FOUND")
get_inspection = _make("professional_inspections", "ERR_INSPECTION_NOT_FOUND")
get_operational_log = _make("operational_logs", "ERR_OPERATIONAL_LOG_NOT_FOUND")
get_group_client = _make("group_clients", "ERR_GROUP_CLIENT_NOT_FOUND")
get_booking = _make("bookings", "ERR_BOOKING_NOT_FOUND")
get_participant = _make("participants", "ERR_PARTICIPANT_NOT_FOUND")
get_program_block = _make("program_blocks", "ERR_PROGRAM_BLOCK_NOT_FOUND")
get_equipment = _make("belay_equipment", "ERR_EQUIPMENT_NOT_FOUND")
get_incident = _make("incidents", "ERR_INCIDENT_NOT_FOUND")
get_training_record = _make("training_records", "ERR_TRAINING_RECORD_NOT_FOUND")
get_block_assignment = _make("block_assignments", "ERR_BLOCK_ASSIGNMENT_NOT_FOUND")
get_observation = _make("weather_observations", "ERR_WEATHER_OBSERVATION_NOT_FOUND")


# ------------------------------------------------------------------- filtering

def _as_bool(raw, name):
    lowered = str(raw).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("Query parameter '%s' must be a boolean." % name)


def apply_filters(rows, spec, accessors=None):
    """``spec`` maps a query-parameter name to ('kind', row_key).

    Kinds: 'str' (plain equality), 'bool', 'date'.  ``accessors`` optionally maps
    a row_key to a callable used instead of a dict lookup (for derived fields).
    """
    accessors = accessors or {}
    out = rows
    for param, (kind, key) in spec.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "bool":
            wanted = _as_bool(raw, param)
        elif kind == "date":
            wanted = parse_date(raw, param)
        else:
            wanted = raw

        getter = accessors.get(key)
        if getter is None:
            out = [r for r in out if r.get(key) == wanted]
        else:
            out = [r for r in out if getter(r) == wanted]
    return out
