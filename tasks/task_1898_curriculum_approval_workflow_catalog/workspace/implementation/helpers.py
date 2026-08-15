"""Body validation, pagination, and shared query helpers."""

import json
import re
from datetime import datetime, timezone

from flask import request

from db import STORE
from errors import ApiError
from response import ok_list

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_QINT_RE = re.compile(r"-?\d+")


def get_json_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return parsed


def parse_date(s):
    """Strict YYYY-MM-DD date parse; returns a date or None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_dt(s):
    """ISO 8601 datetime parse (naive values are treated as UTC); None on failure."""
    if not isinstance(s, str):
        return None
    t = s
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _check_kind(kind, v):
    if kind == "str":
        return isinstance(v, str)
    if kind == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == "num":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if kind == "bool":
        return isinstance(v, bool)
    if kind == "list":
        return isinstance(v, list)
    if kind == "str_list":
        return isinstance(v, list) and all(isinstance(x, str) for x in v)
    if kind == "int_list":
        return isinstance(v, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in v)
    if kind == "date":
        return parse_date(v) is not None
    if kind == "datetime":
        return parse_dt(v) is not None
    raise AssertionError(f"unknown kind {kind}")


def check_fields(body, spec):
    """Validate body shape against spec {field: (kind, required)}.

    Unknown fields, missing required fields, null required fields, and type
    mismatches are all ERR_VALIDATION (priority 4).
    """
    unknown = sorted(set(body.keys()) - set(spec.keys()))
    if unknown:
        raise ApiError("ERR_VALIDATION", 400, f"unknown field: {unknown[0]}")
    for name, (kind, required) in spec.items():
        if name not in body:
            if required:
                raise ApiError("ERR_VALIDATION", 400, f"missing required field: {name}")
            continue
        v = body[name]
        if v is None:
            if required:
                raise ApiError("ERR_VALIDATION", 400, f"field {name} must not be null")
            continue  # explicit null on an optional field is treated as absent
        if not _check_kind(kind, v):
            raise ApiError("ERR_VALIDATION", 400, f"field {name} has invalid type")


def validate_requisites(value):
    """Shape-check a proposed_requisites array; returns list of normalized entries."""
    if not isinstance(value, list):
        raise ApiError("ERR_VALIDATION", 400, "proposed_requisites must be an array")
    out = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", 400, "proposed_requisites entries must be objects")
        extra = sorted(set(entry.keys()) - {"requisite_course_id", "requisite_type"})
        if extra:
            raise ApiError("ERR_VALIDATION", 400, f"unknown requisite field: {extra[0]}")
        rid = entry.get("requisite_course_id")
        rtype = entry.get("requisite_type")
        if not isinstance(rid, str):
            raise ApiError("ERR_VALIDATION", 400, "requisite_course_id must be a string")
        if rtype not in ("PREREQUISITE", "COREQUISITE"):
            raise ApiError("ERR_VALIDATION", 400, "requisite_type must be PREREQUISITE or COREQUISITE")
        if rid not in STORE["courses"]:
            raise ApiError("ERR_VALIDATION", 400, "requisite_course_id does not reference an existing course")
        out.append({"requisite_course_id": rid, "requisite_type": rtype})
    return out


def body_fk(store_key, value, field):
    """Body-referenced FK that fails to resolve is ERR_VALIDATION (PRD 2.7)."""
    rec = STORE[store_key].get(value)
    if rec is None:
        raise ApiError("ERR_VALIDATION", 400, f"{field} does not reference an existing resource")
    return rec


def path_param(store_key, value):
    """Templated path id that fails to resolve is ERR_NOT_FOUND (priority 3)."""
    rec = STORE[store_key].get(value)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return rec


def _parse_qint(raw):
    if raw is None:
        return None, True
    if not _QINT_RE.fullmatch(raw):
        return None, False
    return int(raw), True


def pagination_params():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit, ok_ = _parse_qint(raw_limit)
        if not ok_ or limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "invalid limit")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset, ok_ = _parse_qint(raw_offset)
        if not ok_ or offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "invalid offset")
    return limit, offset


def list_response(records, serialize):
    """Sort by creation order ascending, paginate, and wrap in the envelope."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize(r) for r in page], total, limit, offset)


# --- Shared derived values ---------------------------------------------------

def compute_scheduled_count(term_id):
    return sum(
        1
        for p in STORE["proposals"].values()
        if p["effective_term_id"] == term_id and p["status"] in ("APPROVED", "EFFECTIVE")
    )


def compute_prereq_summary(course_id):
    links = [
        l for l in STORE["requisite_links"].values()
        if l["course_id"] == course_id and l["status"] == "ACTIVE" and l["requisite_type"] == "PREREQUISITE"
    ]
    links.sort(key=lambda l: l["_seq"])
    parts = []
    for l in links:
        rc = STORE["courses"].get(l["requisite_course_id"])
        if rc is not None:
            parts.append(f"{rc['subject_code']} {rc['course_number']}")
    return ",".join(parts)


def is_number_held(subject_code, course_number, exclude_proposal_id=None):
    """A (subject_code, course_number) pair is held by an ACTIVE/DEACTIVATING
    course or by another in-flight proposal."""
    for c in STORE["courses"].values():
        if (
            c["subject_code"] == subject_code
            and c["course_number"] == course_number
            and c["status"] in ("ACTIVE", "DEACTIVATING")
        ):
            return True
    for p in STORE["proposals"].values():
        if exclude_proposal_id is not None and p["id"] == exclude_proposal_id:
            continue
        if (
            p["proposal_type"] == "NEW_COURSE"
            and p["status"] in ("DEPT_REVIEW", "COMMITTEE_REVIEW", "SENATE_REVIEW", "REGISTRAR_REVIEW", "APPROVED")
            and p["proposed_subject_code"] == subject_code
            and p["proposed_course_number"] == course_number
        ):
            return True
    return False


# --- Serializers ---------------------------------------------------------------

def serialize_term(t):
    d = dict((k, v) for k, v in t.items() if not k.startswith("_"))
    d["scheduled_proposal_count"] = compute_scheduled_count(t["id"])
    return d


def serialize_course(c):
    d = dict((k, v) for k, v in c.items() if not k.startswith("_"))
    d["prerequisite_summary"] = compute_prereq_summary(c["id"])
    return d
