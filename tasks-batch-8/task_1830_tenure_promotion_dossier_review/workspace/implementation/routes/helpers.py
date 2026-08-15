"""Shared route helpers: serialization, list pagination (PRD §2.3), and the
candidate confidentiality seal (PRD §2.7)."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_CONFIDENTIAL_LETTERS_SEALED
from middleware import authorized, ALL_READ_ROLES
from response import success_list, success_object
from validate import require_path


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(collection, filters=None):
    """List with created_at-ascending sort, query filters, and pagination."""
    authorized(ALL_READ_ROLES)
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(collection, rid, error_spec):
    """GET one resource; auth priorities 1-2 then existence (priority 3)."""
    authorized(ALL_READ_ROLES)
    rec = require_path(collection, rid, error_spec)
    return success_object(public(rec))


# ---------------------------------------------------------------------------
# Candidate confidentiality seal (PRD §2.7): Candidate reads of invitations,
# rounds, and votes of a waiver-signed case are rejected with
# ERR_CONFIDENTIAL_LETTERS_SEALED.
# ---------------------------------------------------------------------------

def _case_sealed(case):
    return case is not None and bool(case.get("waiver_signed"))


def check_seal_single(caller, case):
    """Priority 5 (confidentiality clause) for single-resource GETs."""
    if caller.role == "Candidate" and _case_sealed(case):
        raise_error(ERR_CONFIDENTIAL_LETTERS_SEALED,
                    "candidate reads of the review record are sealed by the signed waiver")


def list_sealed(collection, filters, case_id_of):
    """List for invitations/rounds/votes with the candidate seal applied.

    - Candidate + explicit case_id filter on a sealed case -> 403.
    - Candidate without a case_id filter -> sealed-case records excluded.
    """
    caller = authorized(ALL_READ_ROLES)
    items = list(db[collection].values())
    case_filter = (filters or {}).get("case_id")
    if caller.role == "Candidate":
        if case_filter is not None:
            check_seal_single(caller, db["cases"].get(case_filter))
        else:
            items = [r for r in items if not _case_sealed(db["cases"].get(case_id_of(r)))]
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)
