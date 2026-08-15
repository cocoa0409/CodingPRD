"""Shared helpers: common fields, type validation, domain lookups."""

import uuid
from datetime import datetime, timezone, date

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_SEASON_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_STOP_NOT_FOUND,
    ERR_MACHINE_NOT_FOUND,
    ERR_CREW_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_TICKET_NOT_FOUND,
    ERR_SETTLEMENT_NOT_FOUND,
    ERR_LODGING_SITE_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
)


# ---------------------------------------------------------------------------
# Common fields (§2.4)
# ---------------------------------------------------------------------------

def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_timestamp():
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def stamp_new(record):
    ts = now_timestamp()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_creation_index"] = db.next_creation_index()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = now_timestamp()
    record["version"] = record.get("version", 1) + 1
    return record


def public(record):
    """Strip internal bookkeeping fields before serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def sort_key(record):
    """created_at ascending, with creation index as a stable tiebreaker."""
    return (record.get("created_at", ""), record.get("_creation_index", 0))


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------

def get_json_body():
    """Return the parsed JSON object body or raise ERR_INVALID_REQUEST.

    An absent body (no JSON at all) is treated as an empty object, so
    bodyless POST transition endpoints work; malformed JSON and non-object
    bodies are rejected.
    """
    if request_body_is_empty():
        return {}
    from flask import request
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def request_body_is_empty():
    from flask import request
    if request.content_length in (None, 0):
        return True
    raw = request.get_data(cache=True)
    return raw is None or len(raw.strip()) == 0


def require_fields(body, fields):
    """Ensure each named field is present (and not None)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, f"Missing required field: {f}"
            )


def is_bool(v):
    return isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def is_string(v):
    return isinstance(v, str)


def require_type(body, field, kind, label=None):
    """Type-check a present field; kind in {'int','number','string','bool'}."""
    v = body[field]
    ok = {
        "int": is_int,
        "number": is_number,
        "string": is_string,
        "bool": is_bool,
    }[kind](v)
    if not ok:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"Field {label or field} has wrong type; expected {kind}",
        )
    return v


def optional_type(body, field, kind, label=None):
    if field not in body or body[field] is None:
        return None
    return require_type(body, field, kind, label)


def require_enum(body, field, allowed):
    v = require_type(body, field, "string")
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"Field {field} must be one of {sorted(allowed)}",
        )
    return v


def parse_date(value, field):
    """Parse a YYYY-MM-DD calendar date."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a YYYY-MM-DD date string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a YYYY-MM-DD date string")


def daterange(start, end):
    """Yield calendar dates in [start, end)."""
    from datetime import timedelta
    d = start
    while d < end:
        yield d
        d = d + timedelta(days=1)


# ---------------------------------------------------------------------------
# Logical clock (§2.5)
# ---------------------------------------------------------------------------

def logical_clock_date():
    """Current logical date (YYYY-MM-DD) read from the logical clock."""
    iso = db.logical_clock_iso
    # Accept both 'Z' and '+00:00' style
    s = iso.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return date(2026, 8, 1)


# ---------------------------------------------------------------------------
# Existence lookups (priority 3, left-to-right)
# ---------------------------------------------------------------------------

def get_season_or_404(season_id):
    s = db.seasons.get(season_id)
    if s is None:
        raise ApiError(ERR_SEASON_NOT_FOUND, 404, "HarvestSeason id not found")
    return s


def get_contract_or_404(contract_id):
    c = db.contracts.get(contract_id)
    if c is None:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, 404, "CustomerContract id not found")
    return c


def get_stop_or_404(stop_id):
    s = db.route_stops.get(stop_id)
    if s is None:
        raise ApiError(ERR_STOP_NOT_FOUND, 404, "RouteStop id not found")
    return s


def get_machine_or_404(machine_id):
    m = db.machines.get(machine_id)
    if m is None:
        raise ApiError(ERR_MACHINE_NOT_FOUND, 404, "Machine id not found")
    return m


def get_crew_or_404(crew_id):
    c = db.crew_members.get(crew_id)
    if c is None:
        raise ApiError(ERR_CREW_NOT_FOUND, 404, "CrewMember id not found")
    return c


def get_assignment_or_404(assignment_id):
    a = db.machine_assignments.get(assignment_id)
    if a is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, 404, "MachineAssignment id not found")
    return a


def get_ticket_or_404(ticket_id):
    t = db.delivery_tickets.get(ticket_id)
    if t is None:
        raise ApiError(ERR_TICKET_NOT_FOUND, 404, "DeliveryTicket id not found")
    return t


def get_settlement_or_404(settlement_id):
    s = db.settlements.get(settlement_id)
    if s is None:
        raise ApiError(ERR_SETTLEMENT_NOT_FOUND, 404, "Settlement id not found")
    return s


def get_site_or_404(site_id):
    s = db.lodging_sites.get(site_id)
    if s is None:
        raise ApiError(ERR_LODGING_SITE_NOT_FOUND, 404, "LodgingSite id not found")
    return s


def get_reservation_or_404(res_id):
    r = db.lodging_reservations.get(res_id)
    if r is None:
        raise ApiError(ERR_RESERVATION_NOT_FOUND, 404, "LodgingReservation id not found")
    return r
