"""Shared helpers: input validation, lookups, serializers, ledger, derived state.

Validation ladder (PRD section 2.9) is enforced per-endpoint in the route
modules; these helpers provide the primitives each ladder rung uses.
"""

import re
from datetime import datetime, timezone

from flask import request

from db import store, new_id, next_ix, now, fmt_dt
from errors import ApiError
from response import success

# ---------------------------------------------------------------------------
# Body and field validation (ladder rung 4 -> ERR_VALIDATION)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def check_allowed_fields(data, allowed):
    for key in data.keys():
        if key not in allowed:
            raise ApiError("ERR_VALIDATION", "Unknown body field: %s" % key)


def _missing(name):
    raise ApiError("ERR_VALIDATION", "Missing required field: %s" % name)


def _bad(name):
    raise ApiError("ERR_VALIDATION", "Invalid value for field: %s" % name)


def req_string(data, name):
    if name not in data or data[name] is None:
        _missing(name)
    if not isinstance(data[name], str):
        _bad(name)
    return data[name]


def opt_string(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], str):
        _bad(name)
    return data[name]


def _as_int(data, name, lo, hi):
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name)
    if lo is not None and v < lo:
        _bad(name)
    if hi is not None and v > hi:
        _bad(name)
    return v


def req_int(data, name, lo=None, hi=None):
    if name not in data or data[name] is None:
        _missing(name)
    return _as_int(data, name, lo, hi)


def opt_int(data, name, lo=None, hi=None, default=None):
    if name not in data or data[name] is None:
        return default
    return _as_int(data, name, lo, hi)


def req_bool(data, name):
    if name not in data or data[name] is None:
        _missing(name)
    if not isinstance(data[name], bool):
        _bad(name)
    return data[name]


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], bool):
        _bad(name)
    return data[name]


def req_enum(data, name, values):
    if name not in data or data[name] is None:
        _missing(name)
    if data[name] not in values:
        _bad(name)
    return data[name]


def opt_enum(data, name, values, default=None):
    if name not in data or data[name] is None:
        return default
    if data[name] not in values:
        _bad(name)
    return data[name]


def parse_date_str(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ApiError("ERR_VALIDATION", "Invalid ISO date: %r" % (s,))
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Invalid ISO date: %r" % (s,))


def req_date(data, name):
    if name not in data or data[name] is None:
        _missing(name)
    return parse_date_str(data[name])


def opt_date(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return parse_date_str(data[name])


def parse_dt_str(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "Invalid ISO8601 datetime: %r" % (s,))
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Invalid ISO8601 datetime: %r" % (s,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(data, name):
    if name not in data or data[name] is None:
        _missing(name)
    return parse_dt_str(data[name])


# ---------------------------------------------------------------------------
# Money rounding (PRD section 2.6): half-up at the final multiplication only
# ---------------------------------------------------------------------------

def rhu_mul_div(n, mul, div):
    """round_half_up(n * mul / div) for non-negative integers, exact math."""
    x = n * mul
    q, r = divmod(x, div)
    if 2 * r >= div:
        q += 1
    return q


def rhu_half(total):
    """round_half_up(total / 2) for a non-negative integer."""
    q, r = divmod(total, 2)
    if 2 * r >= 2:
        q += 1
    return q


# ---------------------------------------------------------------------------
# Entity lookups (ladder rung 3 -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def get_file_or_404(fid):
    f = store.files.get(fid)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Escrow file not found: %s" % fid)
    return f


def get_holdback_or_404(hid):
    h = store.holdbacks.get(hid)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", "Holdback not found: %s" % hid)
    return h


def get_approval_or_404(aid):
    a = store.approvals.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Approval not found: %s" % aid)
    return a


def get_bid_or_404(bid):
    b = store.bids.get(bid)
    if b is None:
        raise ApiError("ERR_NOT_FOUND", "Bid not found: %s" % bid)
    return b


def get_work_order_or_404(wid):
    w = store.work_orders.get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", "Work order not found: %s" % wid)
    return w


def get_inspection_or_404(iid):
    i = store.inspections.get(iid)
    if i is None:
        raise ApiError("ERR_NOT_FOUND", "Inspection not found: %s" % iid)
    return i


def get_draw_or_404(did):
    d = store.draws.get(did)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", "Draw request not found: %s" % did)
    return d


def get_extension_or_404(eid):
    e = store.extensions.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "Extension request not found: %s" % eid)
    return e


def get_dispute_or_404(did):
    d = store.disputes.get(did)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found: %s" % did)
    return d


def get_pledge_or_404(pid):
    p = store.pledges.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Shortfall pledge not found: %s" % pid)
    return p


def holdback_of_file(fid):
    for h in store.holdbacks.values():
        if h["escrow_file_id"] == fid:
            return h
    return None


def work_order_of(hb_id):
    for w in store.work_orders.values():
        if w["holdback_id"] == hb_id:
            return w
    return None


def file_of_holdback(hb):
    return store.files.get(hb["escrow_file_id"])


# ---------------------------------------------------------------------------
# Mutation bookkeeping
# ---------------------------------------------------------------------------

def touch(e):
    """updated_at refresh + version increment on the resource actually mutated."""
    e["updated_at"] = now()
    e["version"] += 1


def new_entity():
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_ix": next_ix()}


def append_ledger(hb, entry_type, amount_cents, memo):
    """Append an immutable ledger entry; maintains seq, running balance, trust."""
    entries = store.ledger_by_hb.setdefault(hb["id"], [])
    seq = len(entries) + 1
    running = (entries[-1]["running_balance_cents"] if entries else 0) + amount_cents
    e = {
        "id": new_id(),
        "holdback_id": hb["id"],
        "seq": seq,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "running_balance_cents": running,
        "memo": memo,
        "created_at": now(),
        "_ix": next_ix(),
    }
    entries.append(e)
    store.ledger[e["id"]] = e
    hb["trust_balance_cents"] = running
    return e


def refresh_holdback_derived(hb):
    """Recompute work_verified / disbursement_frozen / closeout_status.

    Returns True when any derived value changed (i.e. the holdback was
    actually mutated by the recompute and deserves a version bump).
    """
    wo = work_order_of(hb["id"])
    wv = bool(wo and wo["status"] == "VERIFIED")
    frozen = any(
        d["status"] == "OPEN" for d in store.disputes.values() if d["holdback_id"] == hb["id"]
    )
    pledged = any(
        p["status"] == "PLEDGED" for p in store.pledges.values() if p["holdback_id"] == hb["id"]
    )
    closeout = (
        "READY_TO_CLOSE"
        if (hb["status"] == "ACTIVE" and wv and not frozen and not pledged)
        else "NOT_READY"
    )
    changed = (
        wv != hb["work_verified"]
        or frozen != hb["disbursement_frozen"]
        or closeout != hb["closeout_status"]
    )
    hb["work_verified"] = wv
    hb["disbursement_frozen"] = frozen
    hb["closeout_status"] = closeout
    return changed


def refresh_file_status(f):
    hb = holdback_of_file(f["id"])
    new_status = (
        "CLOSED" if (hb and hb["status"] in ("CLOSED_COMPLETED", "CLOSED_EXPIRED")) else "OPEN"
    )
    if new_status != f["status"]:
        f["status"] = new_status
        touch(f)


# ---------------------------------------------------------------------------
# Serializers (internal datetimes/dates -> PRD wire formats)
# ---------------------------------------------------------------------------

def _ts(v):
    return fmt_dt(v) if v is not None else None


def _d(v):
    return v.isoformat() if v is not None else None


def ser_file(f):
    return {
        "id": f["id"],
        "property_address": f["property_address"],
        "closing_date": _d(f["closing_date"]),
        "buyer_user_id": f["buyer_user_id"],
        "seller_user_id": f["seller_user_id"],
        "lender_user_id": f["lender_user_id"],
        "insurer_user_id": f["insurer_user_id"],
        "status": f["status"],
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def ser_holdback(h):
    return {
        "id": h["id"],
        "escrow_file_id": h["escrow_file_id"],
        "repair_scope": h["repair_scope"],
        "repair_estimate_cents": h["repair_estimate_cents"],
        "contingency_pct": h["contingency_pct"],
        "holdback_amount_cents": h["holdback_amount_cents"],
        "commitment_basis_cents": h["commitment_basis_cents"],
        "funding_source": h["funding_source"],
        "overrun_responsibility": h["overrun_responsibility"],
        "expiration_terms": h["expiration_terms"],
        "work_deadline_date": _d(h["work_deadline_date"]),
        "hard_stop_date": _d(h["hard_stop_date"]),
        "exterior_work_flag": h["exterior_work_flag"],
        "granted_extension_days": h["granted_extension_days"],
        "effective_deadline_date": _d(h["effective_deadline_date"]),
        "lender_approval_required": h["lender_approval_required"],
        "insurer_approval_required": h["insurer_approval_required"],
        "selected_bid_id": h["selected_bid_id"],
        "status": h["status"],
        "trust_balance_cents": h["trust_balance_cents"],
        "reserved_cents": h["reserved_cents"],
        "total_disbursed_cents": h["total_disbursed_cents"],
        "total_shortfall_deposited_cents": h["total_shortfall_deposited_cents"],
        "work_verified": h["work_verified"],
        "disbursement_frozen": h["disbursement_frozen"],
        "closeout_status": h["closeout_status"],
        "disposition_override": h["disposition_override"],
        "created_at": _ts(h["created_at"]),
        "updated_at": _ts(h["updated_at"]),
        "version": h["version"],
    }


def ser_approval(a):
    return {
        "id": a["id"],
        "holdback_id": a["holdback_id"],
        "approver_role": a["approver_role"],
        "status": a["status"],
        "approver_user_id": a["approver_user_id"],
        "holdback_version_at_decision": a["holdback_version_at_decision"],
        "decided_at": _ts(a["decided_at"]),
        "rejection_reason": a["rejection_reason"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_bid(b):
    return {
        "id": b["id"],
        "holdback_id": b["holdback_id"],
        "contractor_user_id": b["contractor_user_id"],
        "amount_cents": b["amount_cents"],
        "scope_text": b["scope_text"],
        "status": b["status"],
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def ser_work_order(w):
    return {
        "id": w["id"],
        "holdback_id": w["holdback_id"],
        "contractor_user_id": w["contractor_user_id"],
        "agreed_amount_cents": w["agreed_amount_cents"],
        "started_at": _ts(w["started_at"]),
        "completion_deadline_date": _d(w["completion_deadline_date"]),
        "status": w["status"],
        "failed_final_count": w["failed_final_count"],
        "submitted_completion_at": _ts(w["submitted_completion_at"]),
        "created_at": _ts(w["created_at"]),
        "updated_at": _ts(w["updated_at"]),
        "version": w["version"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "holdback_id": i["holdback_id"],
        "inspector_user_id": i["inspector_user_id"],
        "purpose": i["purpose"],
        "scheduled_start": _ts(i["scheduled_start"]),
        "scheduled_end": _ts(i["scheduled_end"]),
        "status": i["status"],
        "reported_at": _ts(i["reported_at"]),
        "result_notes": i["result_notes"],
        "created_at": _ts(i["created_at"]),
        "updated_at": _ts(i["updated_at"]),
        "version": i["version"],
    }


def ser_draw(d):
    return {
        "id": d["id"],
        "holdback_id": d["holdback_id"],
        "contractor_user_id": d["contractor_user_id"],
        "amount_cents": d["amount_cents"],
        "description": d["description"],
        "is_final": d["is_final"],
        "status": d["status"],
        "approved_at": _ts(d["approved_at"]),
        "paid_at": _ts(d["paid_at"]),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def ser_extension(e):
    return {
        "id": e["id"],
        "holdback_id": e["holdback_id"],
        "requester_user_id": e["requester_user_id"],
        "reason": e["reason"],
        "requested_days": e["requested_days"],
        "evidence_ref": e["evidence_ref"],
        "status": e["status"],
        "granted_days": e["granted_days"],
        "decided_at": _ts(e["decided_at"]),
        "created_at": _ts(e["created_at"]),
        "updated_at": _ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "holdback_id": d["holdback_id"],
        "initiator_role": d["initiator_role"],
        "initiator_user_id": d["initiator_user_id"],
        "category": d["category"],
        "claimed_amount_cents": d["claimed_amount_cents"],
        "statement": d["statement"],
        "status": d["status"],
        "resolution_note": d["resolution_note"],
        "resolved_at": _ts(d["resolved_at"]),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def ser_pledge(p):
    return {
        "id": p["id"],
        "holdback_id": p["holdback_id"],
        "payer_role": p["payer_role"],
        "payer_user_id": p["payer_user_id"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "deposited_at": _ts(p["deposited_at"]),
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_ledger_entry(e):
    # Ledger entries are immutable: no updated_at, no version (PRD 2.5).
    return {
        "id": e["id"],
        "holdback_id": e["holdback_id"],
        "seq": e["seq"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "running_balance_cents": e["running_balance_cents"],
        "memo": e["memo"],
        "created_at": _ts(e["created_at"]),
    }


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0
# ---------------------------------------------------------------------------

def paginated(items, serializer):
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    pg = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success([serializer(x) for x in page], response_type="array", pagination=pg)


def sorted_default(items):
    """created_at ASC; equal timestamps keep insertion (append) order."""
    return sorted(items, key=lambda e: (e["created_at"], e["_ix"]))
