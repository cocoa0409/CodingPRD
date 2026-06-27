"""Record creation, mutation, common-field stamping, body parsing, pagination."""
from flask import request

from db import db, new_id
from clock import clock
from datetime_util import format_iso8601
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_PAGINATION)


def _now_iso():
    """System timestamp for created_at/updated_at — stamped from the LOGICAL
    clock (PRD §2.5: every deadline/expiry/decay reads the logical clock, and
    §3.16 sweeps appointments by their COMPLETED-transition updated_at against
    period bounds expressed on the same logical clock)."""
    return format_iso8601(clock.now())


def json_body(optional=True):
    """Parse the JSON request body. Transition endpoints may carry no body, so
    return {} when empty. Raise ERR_INVALID_REQUEST on malformed JSON."""
    if not request.data or request.data.strip() == b"":
        if optional:
            return {}
        raise err(ERR_INVALID_REQUEST, "Request body required")
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        if optional:
            return {}
        raise err(ERR_INVALID_REQUEST, "Request body required")
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def make_record(extra, with_common=True):
    """Create a base record dict with id and (optionally) the full common-field
    set (created_at, updated_at, version starting at 1) per PRD §2.4.

    SanitationLog and AppointmentAddOn are exceptions: with_common=False gives
    them only id + created_at (no updated_at, no version)."""
    rec = {"id": new_id()}
    ts = _now_iso()
    rec["created_at"] = ts
    if with_common:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = db.next_seq()  # internal ordering key, stripped on serialization
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a record as mutated: refresh updated_at and bump version (PRD §2.4).
    Immutable records (no version key) are never touched."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = _now_iso()


# ---- request body / query parsing -----------------------------------------

def get_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return val


def get_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    # bool is a subclass of int — reject it
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be <= {maximum}")
    return val


def get_number(body, field, required=True, default=None, gt=None, minimum=None):
    """Accept int or float (not bool)."""
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    if gt is not None and not (val > gt):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be > {gt}")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return val


def get_bool(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return val


def get_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in choices:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {choices}")
    return val


# ---- pagination (PRD §2.3) -------------------------------------------------

def parse_pagination(args):
    """Parse limit/offset. limit defaults 10 (min 1, max 100); offset defaults 0
    (min 0). A limit outside 1..100 or a negative offset is rejected with
    ERR_INVALID_PAGINATION (PRD §2.3, validation priority 18)."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_PAGINATION, "limit must be an integer 1..100")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_PAGINATION, "limit must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_PAGINATION, "offset must be a non-negative integer")
        if offset < 0:
            raise err(ERR_INVALID_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset, reverse=False):
    """Sort by created_at then _seq (deterministic tie-break, never id), then
    slice. PRD §2.3: default sort is created_at ascending. `reverse=True` yields
    newest-first (used by station sanitation-logs which lists newest first)."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)),
                     reverse=reverse)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
