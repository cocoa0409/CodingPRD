"""Shared helpers: time parsing, pagination, body validation, recompute logic."""

from datetime import datetime, timezone

from flask import request

import db
from errors import invalid_request


# ---- Time ----------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO 8601 string into a tz-aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("Timestamp must be a string.")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Current simulated clock as a tz-aware UTC datetime."""
    return parse_iso(db.current_utc_iso())


# ---- Body / query parsing -----------------------------------------------
def get_json_body():
    """Return the request JSON body as a dict (empty dict if no body)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object.")
    return data


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise invalid_request(f"Missing required field: {f}")


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit defaults to 10, must be in [1, 100]; offset defaults to 0, >= 0.
    Out-of-range or malformed values raise ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer.")
        if offset < 0:
            raise invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(rows):
    """Sort rows by created_at ascending then apply limit/offset (PRD §2.3)."""
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + limit < total
    return page, limit, offset, total, has_more


# ---- Computed-field recompute -------------------------------------------
def recompute_precinct(precinct):
    """Recompute assigned_count and capacity_posture for a precinct."""
    count = sum(
        1 for r in db.registrations.values()
        if r.get("precinct_id") == precinct["id"] and r.get("status") == "ACTIVE"
    )
    precinct["assigned_count"] = count
    precinct["capacity_posture"] = (
        "OPEN" if count < precinct["max_registrations"] else "FULL"
    )


def recompute_election_counts(election):
    """Recompute total_registered and total_ballots_accepted for an election."""
    eid = election["id"]
    election["total_registered"] = sum(
        1 for r in db.registrations.values()
        if r.get("election_id") == eid and r.get("status") == "ACTIVE"
    )
    election["total_ballots_accepted"] = sum(
        1 for b in db.ballots.values()
        if b.get("election_id") == eid and b.get("request_status") == "ACCEPTED"
    )
