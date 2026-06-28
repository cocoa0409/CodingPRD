"""Common entity helpers: system fields, request parsing, pagination, FK lookup."""
from flask import request

import errors
from db import db, iso

# Whether a project status is terminal (PRD §1.2).
PROJECT_TERMINAL = {"COMPLETED", "CANCELLED"}


def stamp_create(entity, with_version=True):
    """Set id/created_at/updated_at/version on a new entity. PRD §2.4.

    with_version=False for Warranty (immutable, only id + created_at).
    """
    now = db.now()
    entity["id"] = db.new_id()
    entity["created_at"] = now
    entity["_seq"] = db.next_seq()
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutation. PRD §2.4."""
    entity["updated_at"] = db.now()
    if "version" in entity:
        entity["version"] += 1


def get_json():
    """Return request JSON dict, or {} when absent. Raises on malformed JSON."""
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            # empty body permitted for action endpoints with no input
            if request.data and request.data.strip():
                raise errors.invalid_request("Malformed JSON body.")
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Body must be a JSON object.")
        return data
    return {}


def require_field(body, name, expected_types=None, validator=None, error=None):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field '{name}'.")
    value = body[name]
    if expected_types is not None and not _type_ok(value, expected_types):
        raise errors.invalid_request(f"Field '{name}' has wrong type.")
    if validator is not None and not validator(value):
        raise (error or errors.invalid_request(f"Field '{name}' is invalid."))
    return value


def optional_field(body, name, default, expected_types=None, validator=None, error=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if expected_types is not None and not _type_ok(value, expected_types):
        raise errors.invalid_request(f"Field '{name}' has wrong type.")
    if validator is not None and not validator(value):
        raise (error or errors.invalid_request(f"Field '{name}' is invalid."))
    return value


def _type_ok(value, expected_types):
    # bool is a subclass of int; treat carefully.
    if "number" in expected_types:
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
    if "integer" in expected_types:
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        # allow integral floats? PRD implies ints; reject non-int floats.
        return False
    if "string" in expected_types and isinstance(value, str):
        return True
    if "boolean" in expected_types and isinstance(value, bool):
        return True
    return False


def parse_pagination():
    """Parse limit/offset query params. PRD §2.3. Raises ERR_INVALID_PAGINATION."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_pagination("limit out of range [1,100].")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_pagination("offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (via _seq) then slice. PRD §2.3."""
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---- FK / existence lookups (raise ERR_NOT_FOUND) ----
def get_homeowner(hid):
    e = db.homeowners.get(hid)
    if e is None:
        raise errors.not_found("Homeowner not found.")
    return e


def get_project(pid):
    e = db.projects.get(pid)
    if e is None:
        raise errors.not_found("Project not found.")
    return e


def get_measurement(mid):
    e = db.measurements.get(mid)
    if e is None:
        raise errors.not_found("Measurement not found.")
    return e


def get_quote(qid):
    e = db.quotes.get(qid)
    if e is None:
        raise errors.not_found("Quote not found.")
    return e


def get_financing(fid):
    e = db.financing_applications.get(fid)
    if e is None:
        raise errors.not_found("Financing application not found.")
    return e


def get_permit(pid):
    e = db.permit_applications.get(pid)
    if e is None:
        raise errors.not_found("Permit application not found.")
    return e


def get_engineering(eid):
    e = db.engineering_reviews.get(eid)
    if e is None:
        raise errors.not_found("Engineering review not found.")
    return e


def get_manufacture(mid):
    e = db.manufacture_orders.get(mid)
    if e is None:
        raise errors.not_found("Manufacture order not found.")
    return e


def get_crew(cid):
    e = db.install_crews.get(cid)
    if e is None:
        raise errors.not_found("Install crew not found.")
    return e


def get_install_job(jid):
    e = db.install_jobs.get(jid)
    if e is None:
        raise errors.not_found("Install job not found.")
    return e


def get_inspection(iid):
    e = db.inspections.get(iid)
    if e is None:
        raise errors.not_found("Inspection not found.")
    return e
