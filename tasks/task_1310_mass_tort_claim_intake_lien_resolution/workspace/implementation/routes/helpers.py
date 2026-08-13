"""Shared helpers for route handlers."""

import uuid
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST


def new_id():
    return str(uuid.uuid4())


def utc_now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def new_common_fields():
    """Return dict with id, created_at, updated_at, version for common-fields entities."""
    ts = utc_now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def bump(entity):
    """Bump updated_at and version on a common-fields entity."""
    entity["updated_at"] = utc_now_iso()
    entity["version"] += 1


def get_json_body():
    """Parse and return the JSON request body, or empty dict."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def require_fields(body, fields):
    """Validate that required fields are present and non-None in the body."""
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % f, 400)


def get_pagination():
    """Parse limit and offset from query string with defaults and bounds."""
    try:
        limit = int(request.args.get("limit", "10"))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    """Slice items and return (page, pagination_meta)."""
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def sort_by_created_at(items):
    """Sort list by created_at ascending."""
    return sorted(items, key=lambda x: x.get("created_at", ""))


def resolve_program(pid):
    """Look up program by id or raise 404."""
    prog = db.programs.get(pid)
    if prog is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementProgram not found", 404)
    return prog


def resolve_claimant(pid, clid):
    """Look up claimant nested under program."""
    prog = resolve_program(pid)
    cl = db.claimants.get(clid)
    if cl is None or cl["settlement_program_id"] != pid:
        raise ApiError(ERR_NOT_FOUND, "Claimant not found", 404)
    return prog, cl


def resolve_claim(pid, cid):
    """Look up claim nested under program."""
    prog = resolve_program(pid)
    claim = db.claims.get(cid)
    if claim is None or claim["settlement_program_id"] != pid:
        raise ApiError(ERR_NOT_FOUND, "Claim not found", 404)
    return prog, claim


def resolve_tier_matrix(pid, tmid):
    """Look up tier matrix nested under program."""
    prog = resolve_program(pid)
    tm = db.tier_matrices.get(tmid)
    if tm is None or tm["settlement_program_id"] != pid:
        raise ApiError(ERR_NOT_FOUND, "TierMatrix not found", 404)
    return prog, tm


def resolve_medical_record(pid, cid, rid):
    """Look up medical record nested under claim under program."""
    prog, claim = resolve_claim(pid, cid)
    rec = db.medical_records.get(rid)
    if rec is None or rec["claim_id"] != cid:
        raise ApiError(ERR_NOT_FOUND, "MedicalRecord not found", 404)
    return prog, claim, rec


def resolve_lien(pid, cid, lid):
    """Look up lien nested under claim under program."""
    prog, claim = resolve_claim(pid, cid)
    lien = db.liens.get(lid)
    if lien is None or lien["claim_id"] != cid:
        raise ApiError(ERR_NOT_FOUND, "Lien not found", 404)
    return prog, claim, lien


def resolve_appeal(pid, cid, aid):
    """Look up appeal nested under claim under program."""
    prog, claim = resolve_claim(pid, cid)
    appeal = db.appeals.get(aid)
    if appeal is None or appeal["claim_id"] != cid:
        raise ApiError(ERR_NOT_FOUND, "Appeal not found", 404)
    return prog, claim, appeal


def resolve_disbursement(pid, cid, did):
    """Look up disbursement nested under claim under program."""
    prog, claim = resolve_claim(pid, cid)
    disb = db.disbursements.get(did)
    if disb is None or disb["claim_id"] != cid:
        raise ApiError(ERR_NOT_FOUND, "Disbursement not found", 404)
    return prog, claim, disb


import db  # placed at bottom to avoid circular import
