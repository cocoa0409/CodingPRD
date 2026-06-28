"""Shared request helpers: body parsing, field validation, pagination, lookups."""
from flask import request

import db
import errors


def get_body():
    """Return the JSON body as a dict, or {} when empty. Malformed JSON -> 400."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if data is None:
        # Allow empty body on action endpoints.
        if not request.data or request.data.strip() == b"":
            return {}
        raise errors.invalid_request("Malformed JSON body")
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def require_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string")
    return v


def require_positive_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise errors.invalid_request(f"Field {name} must be a positive integer")
    return v


def require_nonneg_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise errors.invalid_request(f"Field {name} must be a non-negative integer")
    return v


def optional_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    return v


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def pagination_params():
    """Parse limit/offset per PRD §2.3 (defaults 10/0, limit in [1,100], offset >= 0)."""
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sort_and_page(records, limit, offset):
    """Sort by created_at ASC (stable via _seq) and apply pagination (PRD §2.3)."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---- existence lookups (PRD §2.10: validate left-to-right, 404 on miss) ----
def get_club(cid):
    rec = db.clubs.get(cid)
    if rec is None:
        raise errors.not_found(f"Club {cid} not found")
    return rec


def get_category(cid):
    rec = db.categories.get(cid)
    if rec is None:
        raise errors.not_found(f"MembershipCategory {cid} not found")
    return rec


def get_membership(mid):
    rec = db.memberships.get(mid)
    if rec is None:
        raise errors.not_found(f"Membership {mid} not found")
    return rec


def get_resource(rid):
    rec = db.resources.get(rid)
    if rec is None:
        raise errors.not_found(f"Resource {rid} not found")
    return rec


def get_reservation(rid):
    rec = db.reservations.get(rid)
    if rec is None:
        raise errors.not_found(f"Reservation {rid} not found")
    return rec


def get_chit(cid):
    rec = db.chits.get(cid)
    if rec is None:
        raise errors.not_found(f"Chit {cid} not found")
    return rec


def get_guest_pass(gid):
    rec = db.guest_passes.get(gid)
    if rec is None:
        raise errors.not_found(f"GuestPass {gid} not found")
    return rec


def get_assessment(aid):
    rec = db.assessments.get(aid)
    if rec is None:
        raise errors.not_found(f"CapitalAssessment {aid} not found")
    return rec


def get_assessment_charge(aid):
    rec = db.assessment_charges.get(aid)
    if rec is None:
        raise errors.not_found(f"AssessmentCharge {aid} not found")
    return rec


def get_waitlist(wid):
    rec = db.waitlist_entries.get(wid)
    if rec is None:
        raise errors.not_found(f"WaitlistEntry {wid} not found")
    return rec


def get_statement(sid):
    rec = db.statements.get(sid)
    if rec is None:
        raise errors.not_found(f"Statement {sid} not found")
    return rec
