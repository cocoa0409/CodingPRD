"""Shared helpers: pagination, OCC version bump, JSON parsing, lookups."""

from __future__ import annotations

from typing import Iterable, Optional

from flask import request

from .. import errors as E
from ..store import store
from ..timeutil import clock


def get_json_body() -> dict:
    """Return the request body as a dict; reject malformed bodies with ERR_INVALID_REQUEST."""
    if request.method in ("GET", "DELETE"):
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Body must be a JSON object.")
    return body


def require_fields(body: dict, *fields: str) -> None:
    for f in fields:
        if f not in body or body[f] is None:
            raise E.ApiError(E.ERR_INVALID_REQUEST, 400, f"Missing required field: {f}.")


def parse_pagination(default_limit: int = 10) -> tuple[int, int]:
    try:
        limit = int(request.args.get("limit", default_limit))
    except (TypeError, ValueError):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid limit.")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid offset.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int, bool]:
    total = len(items)
    end = offset + limit
    page = items[offset:end]
    has_more = end < total
    return page, total, has_more


def bump_version(resource: dict, now=None) -> None:
    """Increment version and refresh updated_at."""
    if now is None:
        now = clock.now()
    resource["version"] = resource.get("version", 0) + 1
    resource["updated_at"] = now


def check_version(resource: dict, body: dict) -> None:
    """Optimistic concurrency check: when 'version' is supplied, compare; mismatch ⇒ conflict."""
    if "version" not in body or body["version"] is None:
        return
    expected = body["version"]
    if not isinstance(expected, int):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "version must be an integer.")
    if expected != resource.get("version", 0):
        raise E.ApiError(E.ERR_VERSION_CONFLICT, 409, "Version conflict.")


# -----------------------------------------------------------------------------
# Resource existence / ownership lookups.
# Path validation is left-to-right per PRD §2.6.
# -----------------------------------------------------------------------------

def get_member_or_404(member_id: str) -> dict:
    m = store.members.get(member_id)
    if not m:
        raise E.ApiError(E.ERR_MEMBER_NOT_FOUND, 404, "Member not found.")
    return m


def get_flight_or_404(flight_id: str) -> dict:
    f = store.flights.get(flight_id)
    if not f:
        raise E.ApiError(E.ERR_FLIGHT_NOT_FOUND, 404, "Flight not found.")
    return f


def get_segment_owned(member_id: str, segment_id: str) -> dict:
    s = store.segments.get(segment_id)
    if not s or s["member_id"] != member_id:
        raise E.ApiError(E.ERR_SEGMENT_NOT_FOUND, 404, "Segment not found.")
    return s


def get_booking_owned(member_id: str, booking_id: str) -> dict:
    b = store.award_bookings.get(booking_id)
    if not b or b["member_id"] != member_id:
        raise E.ApiError(E.ERR_BOOKING_NOT_FOUND, 404, "Booking not found.")
    return b


def get_certificate_owned(member_id: str, cert_id: str) -> dict:
    c = store.companion_certificates.get(cert_id)
    if not c or c["member_id"] != member_id:
        raise E.ApiError(E.ERR_CERTIFICATE_NOT_FOUND, 404, "Certificate not found.")
    return c


def get_status_match_owned(member_id: str, rid: str) -> dict:
    r = store.status_match_requests.get(rid)
    if not r or r["member_id"] != member_id:
        raise E.ApiError(E.ERR_STATUS_MATCH_REQUEST_NOT_FOUND, 404, "Status-match request not found.")
    return r


def get_upgrade_or_404(upgrade_id: str) -> dict:
    u = store.upgrade_requests.get(upgrade_id)
    if not u:
        raise E.ApiError(E.ERR_UPGRADE_REQUEST_NOT_FOUND, 404, "Upgrade request not found.")
    return u


# -----------------------------------------------------------------------------
# Ownership checks for the Member role.
# -----------------------------------------------------------------------------

def enforce_member_ownership(acting_id: str, acting_role: str, owner_id: str) -> None:
    if acting_role == "Member" and acting_id != owner_id:
        raise E.ApiError(E.ERR_OWNERSHIP_MISMATCH, 403, "Caller does not own this resource.")


def enforce_member_status(member: dict) -> None:
    if member["status"] == "FROZEN":
        raise E.ApiError(E.ERR_MEMBER_FROZEN, 403, "Member is FROZEN.")
    if member["status"] == "CLOSED":
        raise E.ApiError(E.ERR_MEMBER_CLOSED, 403, "Member is CLOSED.")
