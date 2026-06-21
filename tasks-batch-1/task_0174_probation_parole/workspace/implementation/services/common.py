"""Shared service helpers: lookups, body validation, pagination, balances."""
from flask import request

import clock
import db
from calculations import outstanding_now
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)
from timeutil import parse_iso

TERMINAL_SUPERVISEE_STATES = {"REVOKED", "TERMINATED_EARLY", "COMPLETED", "TRANSFERRED_OUT"}


# ---- Existence resolution (PRD §2.5: left-to-right path validation) -------
def get_supervisee_or_404(sid):
    s = db.supervisees.get(sid)
    if s is None:
        raise ApiError(*ERR_NOT_FOUND, "Supervisee not found.")
    return s


def get_child_or_404(store, child_id, supervisee_id, fk="supervisee_id", label="Resource"):
    """Resolve a child by id and confirm it belongs to the supervisee in the path."""
    rec = store.get(child_id)
    if rec is None or rec.get(fk) != supervisee_id:
        raise ApiError(*ERR_NOT_FOUND, f"{label} not found.")
    return rec


def get_body():
    """Parse the JSON request body, tolerating an empty body as {}."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # An empty/whitespace body is treated as an empty object.
        if request.data.strip() == b"":
            return {}
        raise ApiError(*ERR_INVALID_REQUEST, "Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise ApiError(*ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


# ---- Request-body validation primitives (ERR_INVALID_REQUEST, 400) -------
def require_fields(body, fields):
    if not isinstance(body, dict):
        raise ApiError(*ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(*ERR_INVALID_REQUEST, f"Missing required field: {f}.")


def check_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError(*ERR_INVALID_REQUEST, f"Invalid value for {field}.")


def require_int_min(value, minimum, field):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(*ERR_INVALID_REQUEST, f"{field} must be an integer.")
    if value < minimum:
        raise ApiError(*ERR_INVALID_REQUEST, f"{field} must be >= {minimum}.")
    return value


def require_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError(*ERR_INVALID_REQUEST, f"{field} must be a non-empty string.")
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError(*ERR_INVALID_REQUEST, f"{field} must be a boolean.")
    return value


def require_datetime(value, field):
    if not isinstance(value, str) or parse_iso(value) is None:
        raise ApiError(*ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 datetime.")
    return value


# ---- Pagination (PRD §2.3) ----------------------------------------------
def paginate(args):
    """Read limit/offset from query args. Default limit 10 (min 1, max 100),
    default offset 0. Out-of-range values raise ERR_INVALID_REQUEST."""
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (TypeError, ValueError):
            raise ApiError(*ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(*ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (TypeError, ValueError):
            raise ApiError(*ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise ApiError(*ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def sorted_by_created(records):
    """Sort by created_at ascending, with insertion-seq as the stable tie-break
    (PRD §2.3: list endpoints sort by created_at ASC)."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def apply_page(records, limit, offset):
    total = len(records)
    page = records[offset : offset + limit]
    return page, total


# ---- Supervisee balance recomputation (PRD §3.6) ------------------------
def recompute_balances(supervisee):
    """Recompute posted restitution/fee balances from the supervisee's
    obligations measured to the present moment. Returns True if any stored
    value changed."""
    now = clock.now()
    rest = 0
    fee = 0
    for ob in db.obligations.values():
        if ob.get("supervisee_id") != supervisee["id"]:
            continue
        if ob["status"] not in ("OPEN", "PARTIALLY_PAID"):
            continue
        out = outstanding_now(ob, now)
        if ob["obligation_type"] == "RESTITUTION":
            rest += out
        else:
            fee += out
    changed = (
        supervisee["restitution_balance_cents"] != rest
        or supervisee["fee_balance_cents"] != fee
    )
    supervisee["restitution_balance_cents"] = rest
    supervisee["fee_balance_cents"] = fee
    return changed


def recompute_cumulative_points(supervisee):
    """Full recompute of cumulative_violation_points over SUSTAINED violations
    (PRD §3.5: full recompute, not increment). Returns True if changed."""
    total = 0
    for v in db.violations.values():
        if v.get("supervisee_id") == supervisee["id"] and v["status"] == "SUSTAINED":
            total += v["points"]
    changed = supervisee["cumulative_violation_points"] != total
    supervisee["cumulative_violation_points"] = total
    return changed
