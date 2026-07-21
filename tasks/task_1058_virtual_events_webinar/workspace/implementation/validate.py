"""Lookup, body-shape, pagination and state-machine guard helpers."""

from flask import request

import db
from db import S, parse_dt
from errors import ApiError

# ---------------------------------------------------------------- lookups

_NOT_FOUND = {
    "events": "ERR_EVENT_NOT_FOUND",
    "ticket_types": "ERR_TICKET_TYPE_NOT_FOUND",
    "registrations": "ERR_REGISTRATION_NOT_FOUND",
    "tracks": "ERR_TRACK_NOT_FOUND",
    "sessions": "ERR_SESSION_NOT_FOUND",
    "speakers": "ERR_SPEAKER_NOT_FOUND",
    "session_speakers": "ERR_SESSION_SPEAKER_NOT_FOUND",
    "broadcasts": "ERR_BROADCAST_NOT_FOUND",
    "recordings": "ERR_RECORDING_NOT_FOUND",
    "sponsors": "ERR_SPONSOR_NOT_FOUND",
    "booths": "ERR_BOOTH_NOT_FOUND",
    "leads": "ERR_LEAD_NOT_FOUND",
    "match_requests": "ERR_MATCH_REQUEST_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
}


def lookup(collection, row_id):
    row = getattr(S, collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection])
    return row


def get_event(event_id):
    return lookup("events", event_id)


def get_ticket_type(x):
    return lookup("ticket_types", x)


def get_registration(x):
    return lookup("registrations", x)


def get_track(x):
    return lookup("tracks", x)


def get_session(x):
    return lookup("sessions", x)


def get_speaker(x):
    return lookup("speakers", x)


def get_session_speaker(x):
    return lookup("session_speakers", x)


def get_broadcast(x):
    return lookup("broadcasts", x)


def get_recording(x):
    """A DELETED recording answers individual reads with ERR_RECORDING_NOT_FOUND."""
    row = lookup("recordings", x)
    if row.get("state") == "DELETED":
        raise ApiError("ERR_RECORDING_NOT_FOUND")
    return row


def get_sponsor(x):
    return lookup("sponsors", x)


def get_booth(x):
    return lookup("booths", x)


def get_lead(x):
    return lookup("leads", x)


def get_match_request(x):
    return lookup("match_requests", x)


def get_settlement(x):
    return lookup("settlements", x)


# ------------------------------------------------------ body-shape helpers


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def _fail(field, reason):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (field, reason))


def req_str(b, field):
    value = b.get(field)
    if not isinstance(value, str) or value == "":
        _fail(field, "is required and must be a non-empty string")
    return value


def opt_str(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    value = b[field]
    if not isinstance(value, str):
        _fail(field, "must be a string")
    return value


def req_int(b, field, minimum=None):
    value = b.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "is required and must be an integer")
    if minimum is not None and value < minimum:
        _fail(field, "must be >= %d" % minimum)
    return value


def opt_int(b, field, default=None, minimum=None):
    if field not in b or b[field] is None:
        return default
    value = b[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(field, "must be >= %d" % minimum)
    return value


def req_bool(b, field):
    value = b.get(field)
    if not isinstance(value, bool):
        _fail(field, "is required and must be a boolean")
    return value


def opt_bool(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    value = b[field]
    if not isinstance(value, bool):
        _fail(field, "must be a boolean")
    return value


def req_enum(b, field, allowed):
    value = b.get(field)
    if not isinstance(value, str) or value not in allowed:
        _fail(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(b, field, allowed, default=None):
    if field not in b or b[field] is None:
        return default
    return req_enum(b, field, allowed)


def req_dt(b, field):
    value = b.get(field)
    if not isinstance(value, str):
        _fail(field, "is required and must be an ISO 8601 timestamp")
    parsed = parse_dt(value)
    if parsed is None:
        _fail(field, "must be a valid ISO 8601 timestamp")
    return parsed


def opt_dt(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    return req_dt(b, field)


# -------------------------------------------------------------- pagination


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    ordered = db.sort_rows(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [db.serialize(r) for r in page], total


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# --------------------------------------------------------- state machinery


def guard_state(row, allowed_from, terminal_states):
    """PRD 2.7 rung 10: declared-transition check, then terminal-state check.

    A resource sitting in a terminal state has no declared transitions at all, so
    the terminal-state code is the one that is reported for it; any other state
    from which this particular transition is not declared yields ERR_INVALID_STATE.
    """
    current = row.get("state")
    if current in allowed_from:
        return
    if current in terminal_states:
        raise ApiError("ERR_ALREADY_TERMINAL")
    raise ApiError("ERR_INVALID_STATE")


def invalid_state():
    raise ApiError("ERR_INVALID_STATE")
