"""Shared lookup, pagination, validation and ownership helpers."""
from flask import request

import db
from errors import err

# ---- pagination defaults (SCAFFOLD response_envelope / PRD 2.3) ----
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def get_body():
    """Parse JSON body; tolerate empty body for no-input transition endpoints."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err("ERR_INVALID_REQUEST", "Body must be valid JSON")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def paginate(items):
    """Apply limit/offset query params, returning (page, pagination_meta).

    items must already be sorted. Invalid pagination -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST", "limit out of range")

    if offset_raw is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    """Creation order ascending (oldest first) — stable via _seq (PRD 2.3)."""
    return sorted(items, key=lambda r: r["_seq"])


# ---- existence lookups (PRD 2.5: parent before child, first not-found wins) --
def get_client(cid):
    c = db.clients.get(cid)
    if c is None:
        raise err("ERR_CLIENT_NOT_FOUND", "Client not found")
    return c


def get_freelancer(fid):
    f = db.freelancers.get(fid)
    if f is None:
        raise err("ERR_FREELANCER_NOT_FOUND", "Freelancer not found")
    return f


def get_job_posting(jid):
    j = db.job_postings.get(jid)
    if j is None:
        raise err("ERR_JOB_POSTING_NOT_FOUND", "Job posting not found")
    return j


def get_proposal(pid):
    p = db.proposals.get(pid)
    if p is None:
        raise err("ERR_PROPOSAL_NOT_FOUND", "Proposal not found")
    return p


def get_contract(cid):
    c = db.contracts.get(cid)
    if c is None:
        raise err("ERR_CONTRACT_NOT_FOUND", "Contract not found")
    return c


def get_milestone(mid):
    m = db.milestones.get(mid)
    if m is None:
        raise err("ERR_MILESTONE_NOT_FOUND", "Milestone not found")
    return m


def get_milestone_in_contract(contract_id, milestone_id):
    m = get_milestone(milestone_id)
    if m["contract_id"] != contract_id:
        raise err("ERR_MILESTONE_NOT_FOUND", "Milestone not found in contract")
    return m


def get_timelog(tid):
    t = db.timelogs.get(tid)
    if t is None:
        raise err("ERR_TIMELOG_NOT_FOUND", "TimeLog not found")
    return t


def get_timelog_in_contract(contract_id, timelog_id):
    t = get_timelog(timelog_id)
    if t["contract_id"] != contract_id:
        raise err("ERR_TIMELOG_NOT_FOUND", "TimeLog not found in contract")
    return t


def get_dispute(did):
    d = db.disputes.get(did)
    if d is None:
        raise err("ERR_DISPUTE_NOT_FOUND", "Dispute not found")
    return d


def get_payout(pid):
    p = db.payouts.get(pid)
    if p is None:
        raise err("ERR_PAYOUT_NOT_FOUND", "Payout not found")
    return p


def get_tax_record(tid):
    t = db.tax_records.get(tid)
    if t is None:
        raise err("ERR_TAX_RECORD_NOT_FOUND", "Tax record not found")
    return t


# ---- field validation helpers (ERR_INVALID_REQUEST) ----
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {n}")


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"{name} must be a non-empty string")
    return v


def require_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"{name} below minimum")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"{name} above maximum")
    return v


def require_enum(body, name, choices):
    v = body.get(name)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(choices)}")
    return v


# ---- ownership (PRD 2.1) ----
def check_client_owns(role, user_id, owner_client_id):
    """Entity-backed Client ownership check (PRD 2.1)."""
    if role == "Client" and user_id != owner_client_id:
        raise err("ERR_FORBIDDEN_ROLE", "Client does not own this resource")


def check_freelancer_owns(role, user_id, owner_freelancer_id):
    """Entity-backed Freelancer ownership check (PRD 2.1)."""
    if role == "Freelancer" and user_id != owner_freelancer_id:
        raise err("ERR_FORBIDDEN_ROLE", "Freelancer does not own this resource")
