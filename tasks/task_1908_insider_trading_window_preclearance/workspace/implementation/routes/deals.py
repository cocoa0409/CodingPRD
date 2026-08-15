"""Deal endpoints: intake, activate, close, deal-sourced restricted entries."""
from flask import Blueprint

from db import STORE
from errors import err, ERR_DATE_RANGE_INVALID, ERR_INVALID_STATE
from middleware import require_roles
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           auto_deny_pending, create_event_window, DEAL_TYPES)
from util import Body, fmt_ts

bp = Blueprint("deals", __name__)

DEAL_READ_ROLES = ("ComplianceOfficer", "LegalAdmin")


@bp.post("/deals")
def create_deal():
    require_roles("ComplianceOfficer")
    body = Body()
    codename = body.get_str("codename")
    deal_type = body.get_enum("deal_type", DEAL_TYPES)
    ticker = body.get_str("security_ticker")
    start = body.get_dt("event_blackout_start", required=False)
    end = body.get_dt("event_blackout_end", required=False)
    # Date-range sanity (ladder: temporal, before body schema): end without
    # start, or end not strictly after start.
    if end is not None and start is None and not body.has("event_blackout_start"):
        raise err(ERR_DATE_RANGE_INVALID, "event_blackout_end present without event_blackout_start")
    if start is not None and end is not None and end <= start:
        raise err(ERR_DATE_RANGE_INVALID, "event_blackout_end must be strictly after event_blackout_start")
    body.flush()
    d = new_entity()
    d.update({
        "codename": codename,
        "deal_type": deal_type,
        "security_ticker": ticker,
        "event_blackout_start": fmt_ts(start) if start else None,
        "event_blackout_end": fmt_ts(end) if end else None,
        "status": "INTAKE",
        "activated_at": None,
        "closed_at": None,
        "_event_start_dt": start,
        "_event_end_dt": end,
        "_activated_dt": None,
        "_closed_dt": None,
    })
    STORE.deals[d["id"]] = d
    return success(serialize(d), 201)


@bp.get("/deals/<did>")
def get_deal(did):
    require_roles(*DEAL_READ_ROLES)
    d = get_or_404("deals", did, "deal")
    return success(serialize(d))


@bp.post("/deals/<did>/activate")
def activate_deal(did):
    require_roles("ComplianceOfficer")
    d = get_or_404("deals", did, "deal")
    if d["status"] != "INTAKE":
        raise err(ERR_INVALID_STATE, "only an INTAKE deal can be activated")
    now = STORE.clock
    d["status"] = "ACTIVE"
    d["activated_at"] = fmt_ts(now)
    d["_activated_dt"] = now
    touch(d)
    # Cascade hop 1: always create a DEAL_INTAKE restricted entry (multiple
    # ACTIVE entries per ticker are permitted across different sources).
    entry = new_entity()
    entry.update({
        "security_ticker": d["security_ticker"],
        "deal_id": d["id"],
        "source": "DEAL_INTAKE",
        "note": None,
        "status": "ACTIVE",
        "removed_reason": None,
    })
    STORE.restricted_entries[entry["id"]] = entry
    # Optional event-driven blackout window (merge rule applies).
    if d["_event_start_dt"] is not None:
        create_event_window(d["security_ticker"], d["_event_start_dt"], d["_event_end_dt"],
                            deal_id=d["id"])
    # Cascade hop 2: pending preclearance requests on the ticker auto-deny.
    auto_deny_pending(d["security_ticker"])
    return success(serialize(d))


@bp.post("/deals/<did>/close")
def close_deal(did):
    require_roles("ComplianceOfficer")
    d = get_or_404("deals", did, "deal")
    if d["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "only an ACTIVE deal can be closed or abandoned")
    body = Body()
    outcome = body.get_enum("outcome", {"COMPLETED", "ABANDONED"})
    body.flush()
    now = STORE.clock
    d["closed_at"] = fmt_ts(now)
    d["_closed_dt"] = now
    # Deal-sourced ACTIVE restricted entries are removed either way.
    for e in sort_created(STORE.restricted_entries.values()):
        if e["deal_id"] == d["id"] and e["status"] == "ACTIVE":
            e["status"] = "REMOVED"
            e["removed_reason"] = "DEAL_CLOSED"
            touch(e)
    if outcome == "COMPLETED":
        d["status"] = "CLOSED"
        for w in sort_created(STORE.blackout_windows.values()):
            if w["deal_id"] == d["id"] and w["status"] == "ACTIVE":
                w["status"] = "LIFTED"
                touch(w)
            elif w["deal_id"] == d["id"] and w["status"] == "SCHEDULED":
                w["status"] = "CANCELLED"
                touch(w)
    else:  # ABANDONED
        d["status"] = "ABANDONED"
        for w in sort_created(STORE.blackout_windows.values()):
            if w["deal_id"] == d["id"] and w["status"] in ("SCHEDULED", "ACTIVE"):
                w["status"] = "CANCELLED"
                touch(w)
    touch(d)
    return success(serialize(d))


@bp.get("/deals/<did>/restricted-list-entries")
def deal_entries(did):
    require_roles(*DEAL_READ_ROLES)
    get_or_404("deals", did, "deal")
    items = [e for e in sort_created(STORE.restricted_entries.values()) if e["deal_id"] == did]
    return paginate([serialize(e) for e in items])
