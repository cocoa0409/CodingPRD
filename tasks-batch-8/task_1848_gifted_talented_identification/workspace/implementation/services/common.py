"""Shared helpers: id/timestamp minting, date parsing, validation utilities,
serialization, pagination, and derived-counter reconciliation."""

import re
import uuid
from datetime import datetime, date, timezone

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND

# ---------------------------------------------------------------------------
# ID / timestamp minting
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


_seq = 0


def reset_clock_seq():
    """Called by the clock-set endpoint so each logical instant starts a fresh
    fractional-digit sequence."""
    global _seq
    _seq = 0


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits.

    Resource metadata timestamps (created_at/updated_at) are stamped from the
    server's logical clock: PRD §1 commits to 'all time is logical' so that
    window checks (45-day transfer honoring, etc.) are deterministic and
    testable, and SCAFFOLD §1.2's transfer precondition compares
    'student.created_at date + 45 days' against logical 'today'.

    A monotonic per-process sequence is folded into the fractional digits so
    that created_at ordering is strict and stable even when many records are
    minted at the same logical instant (e.g. bulk enroll, waitlist ties).
    """
    global _seq
    _seq += 1
    n = db.get_clock()
    base_ms = n.microsecond // 1000
    # Fold the sequence into fractional digits without carrying into seconds —
    # the date portion must stay exactly on the logical clock's day.
    frac_ms = (base_ms + _seq) % 1000
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{frac_ms:03d}Z"


# ---------------------------------------------------------------------------
# Date helpers — all domain dates are YYYY-MM-DD strings vs the logical clock
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field):
    """Parse a YYYY-MM-DD string into a date. ERR_INVALID_REQUEST on bad shape."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a YYYY-MM-DD string", 400)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is not a valid calendar date", 400)


def days_between(earlier, later):
    return (later - earlier).days


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a non-empty string", 400)
    return v


def optional_string(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a string", 400)
    return v


def require_int(body, field, lo=None, hi=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    if lo is not None and v < lo:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {lo}", 400)
    if hi is not None and v > hi:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be <= {hi}", 400)
    return v


def require_number(body, field, lo=None, hi=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a number", 400)
    if lo is not None and v < lo:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {lo}", 400)
    if hi is not None and v > hi:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be <= {hi}", 400)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field} must be one of {sorted(allowed)}",
            400,
        )
    return v


def require_bool(body, field, default=None):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a boolean", 400)
    return v


def one_decimal_ok(v):
    """True when a number has at most one decimal place."""
    from decimal import Decimal
    d = Decimal(str(v))
    return d == d.quantize(Decimal("0.1")) or d == d.quantize(Decimal("1"))


# ---------------------------------------------------------------------------
# Resource lookup (existence, priority 4 — left to right)
# ---------------------------------------------------------------------------


def get_or_404(store, rid, label="resource"):
    if rid is None or rid not in store:
        raise ApiError(ERR_NOT_FOUND, f"{label} not found: {rid}", 404)
    return store[rid]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination_params():
    """Read limit/offset per §2.3. Defaults 10/0, min 1, max 100.

    Out-of-range or non-integer values fall back to defaults rather than
    erroring — the PRD §2.3 names defaults/min/max but lists no error for
    violating them, and validation priority 5 covers body shape only.
    """
    def _parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _parse("limit", 10)
    offset = _parse("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


# ---------------------------------------------------------------------------
# Derived counters (§2.8 — reconciled synchronously, computed on read)
# ---------------------------------------------------------------------------

_MODEL_FIELD = {
    "PULL_OUT": ("pull_out_capacity", "pull_out_occupied"),
    "CLUSTER": ("cluster_capacity", "cluster_occupied"),
    "ACCELERATION": ("acceleration_capacity", "acceleration_occupied"),
}


def occupied_count(site_id, model):
    """ACTIVE placements for (site, model). Seats consumed by ACTIVE only."""
    n = 0
    for p in db.service_placements.values():
        if p["site_id"] == site_id and p["service_model"] == model and p["status"] == "ACTIVE":
            n += 1
    return n


def has_sped_plan(student_id):
    return any(sp["student_id"] == student_id for sp in db.sped_plans.values())


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_site(site):
    out = dict(site)
    out["pull_out_occupied"] = occupied_count(site["id"], "PULL_OUT")
    out["cluster_occupied"] = occupied_count(site["id"], "CLUSTER")
    out["acceleration_occupied"] = occupied_count(site["id"], "ACCELERATION")
    return out


def serialize_student(student):
    out = dict(student)
    out["has_active_sped_plan"] = has_sped_plan(student["id"])
    return out


def serialize_sped_plan(sp):
    return dict(sp)


def serialize_cycle(cycle):
    return dict(cycle)


def serialize_profile(profile):
    return dict(profile)


def serialize_case(case):
    return dict(case)


def serialize_measure(ms):
    return dict(ms)


def serialize_review(review):
    out = dict(review)
    q = d = a = 0
    for v in db.committee_votes.values():
        if v["review_id"] == review["id"]:
            if v["verdict"] == "QUALIFY":
                q += 1
            elif v["verdict"] == "DENY":
                d += 1
            else:
                a += 1
    out["qualify_votes"] = q
    out["deny_votes"] = d
    out["abstain_votes"] = a
    return out


def serialize_vote(vote):
    return dict(vote)


def serialize_placement(p):
    return dict(p)


def serialize_reeval(r):
    return dict(r)
