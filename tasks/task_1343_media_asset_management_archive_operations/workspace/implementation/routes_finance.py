"""UsageEvent and RoyaltyStatement routes (reporting, verification, settlement)."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, require_roles
from db import STORE, new_id, now, stamp
from envelope import ok, paginate
from errors import raise_err
from serializers import event_out, statement_out
from validate import USAGE_TYPES, body, req_dt, req_enum, req_int, req_str

bp = Blueprint("finance", __name__, url_prefix="/archive")


def _get_event(eid):
    rec = STORE.events.get(eid)
    if rec is None:
        raise_err("ERR_EVENT_NOT_FOUND", "Usage event not found")
    return rec


def _get_statement(sid):
    rec = STORE.statements.get(sid)
    if rec is None:
        raise_err("ERR_STATEMENT_NOT_FOUND", "Royalty statement not found")
    return rec


# --- UsageEvent ------------------------------------------------------------------
@bp.post("/usage-events")
def create_event():
    require_roles("Requester")
    j = body()
    asset_id = req_str(j, "asset_id")
    if asset_id not in STORE.assets:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    reported_by_id = req_str(j, "reported_by_id")
    if reported_by_id not in STORE.staff:
        raise_err("ERR_STAFF_MEMBER_NOT_FOUND", "Reporter staff member not found")
    usage_type = req_enum(j, "usage_type", USAGE_TYPES)
    market_size = req_int(j, "market_size", positive=True)
    duration_seconds_used = req_int(j, "duration_seconds_used", positive=True)
    aired_at = req_dt(j, "aired_at")
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "reported_by_id": reported_by_id,
        "usage_type": usage_type,
        "market_size": market_size,
        "duration_seconds_used": duration_seconds_used,
        "aired_at": aired_at,
        "status": "REPORTED",
        "provisional_accrual_cents": None,
        "final_accrual_cents": None,
        "statement_id": None,
        "dispute_reason": None,
    }
    stamp(rec)
    STORE.events[rec["id"]] = rec
    return ok(event_out(rec), 201)


@bp.get("/usage-events")
def list_events():
    require_roles(*ALL_ROLES)
    recs = list(STORE.events.values())
    for param, field in (
        ("asset_id", "asset_id"),
        ("reported_by_id", "reported_by_id"),
        ("statement_id", "statement_id"),
        ("status", "status"),
    ):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, event_out)


@bp.get("/usage-events/<eid>")
def get_event(eid):
    require_roles(*ALL_ROLES)
    return ok(event_out(_get_event(eid)))


@bp.post("/usage-events/<eid>/verify")
def verify_event(eid):
    require_roles("FinanceOfficer")
    rec = _get_event(eid)
    if rec["status"] != "REPORTED":
        raise_err("ERR_EVENT_NOT_REPORTED", "verify requires REPORTED")
    rec["provisional_accrual_cents"] = calc.accrual_provisional(rec)
    rec["status"] = "VERIFIED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(event_out(rec))


@bp.post("/usage-events/<eid>/dispute")
def dispute_event(eid):
    require_roles("FinanceOfficer")
    rec = _get_event(eid)
    if rec["status"] not in ("REPORTED", "VERIFIED"):
        raise_err("ERR_EVENT_NOT_DISPUTABLE", "dispute requires REPORTED or VERIFIED")
    j = body()
    reason = req_str(j, "reason")
    rec["status"] = "DISPUTED"
    rec["dispute_reason"] = reason
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(event_out(rec))


@bp.post("/usage-events/<eid>/resubmit")
def resubmit_event(eid):
    uid, _ = require_roles("Requester")
    rec = _get_event(eid)
    if uid != rec["reported_by_id"]:
        raise_err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Only the original reporter may resubmit this event",
        )
    if rec["status"] != "DISPUTED":
        raise_err("ERR_EVENT_NOT_DISPUTED", "resubmit requires DISPUTED")
    rec["status"] = "REPORTED"
    rec["provisional_accrual_cents"] = None
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(event_out(rec))


# --- RoyaltyStatement --------------------------------------------------------------
@bp.post("/royalty-statements")
def create_statement():
    require_roles("FinanceOfficer")
    j = body()
    rights_holder = req_str(j, "rights_holder")
    period_start = req_dt(j, "period_start")
    period_end = req_dt(j, "period_end")
    if not (period_end > period_start):
        raise_err("ERR_INVALID_REQUEST", "period_end must be strictly after period_start")
    for s in STORE.statements.values():
        if (
            s["rights_holder"] == rights_holder
            and s["status"] in ("OPEN", "CLOSED")
            and period_start < s["period_end"]
            and s["period_start"] < period_end
        ):
            raise_err(
                "ERR_STATEMENT_PERIOD_OVERLAP",
                "Period overlaps a non-terminal statement for this rights holder",
            )
    rec = {
        "id": new_id(),
        "rights_holder": rights_holder,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "event_ids": [],
        "total_verified_seconds": 0,
        "volume_tier": None,
        "provisional_total_cents": None,
        "total_accrual_cents": None,
    }
    stamp(rec)
    STORE.statements[rec["id"]] = rec
    return ok(statement_out(rec), 201)


@bp.get("/royalty-statements")
def list_statements():
    require_roles(*ALL_ROLES)
    recs = list(STORE.statements.values())
    for param, field in (("rights_holder", "rights_holder"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, statement_out)


@bp.get("/royalty-statements/<sid>")
def get_statement(sid):
    require_roles(*ALL_ROLES)
    return ok(statement_out(_get_statement(sid)))


def _swept_events(stmt):
    """VERIFIED events whose asset rights_holder matches and whose aired_at is
    inside [period_start, period_end) — creation order."""
    out = []
    for e in STORE.events.values():
        if e["status"] != "VERIFIED":
            continue
        if not (stmt["period_start"] <= e["aired_at"] < stmt["period_end"]):
            continue
        asset = STORE.assets.get(e["asset_id"])
        if asset is None or asset["rights_holder"] != stmt["rights_holder"]:
            continue
        out.append(e)
    out.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return out


@bp.post("/royalty-statements/<sid>/close")
def close_statement(sid):
    require_roles("FinanceOfficer")
    rec = _get_statement(sid)
    if rec["status"] != "OPEN":
        raise_err("ERR_STATEMENT_NOT_OPEN", "close requires OPEN")
    swept = _swept_events(rec)
    if not swept:
        raise_err("ERR_STATEMENT_EMPTY", "No matching VERIFIED usage events in the period")
    # Fixed, non-recomputable evaluation order:
    # 1. swept set (above); 2. total seconds; 3. volume tier;
    # 4. per-event finals; 5. total accrual; 6. provisional total.
    total_seconds = sum(e["duration_seconds_used"] for e in swept)
    tier = calc.volume_tier_for(total_seconds)
    t = now()
    finals = []
    for e in swept:
        e["final_accrual_cents"] = calc.accrual_final(e, tier)
        e["statement_id"] = rec["id"]
        e["updated_at"] = t
        e["version"] += 1
        finals.append(e["final_accrual_cents"])
    rec["event_ids"] = [e["id"] for e in swept]
    rec["total_verified_seconds"] = total_seconds
    rec["volume_tier"] = tier
    rec["total_accrual_cents"] = sum(finals)
    rec["provisional_total_cents"] = sum(e["provisional_accrual_cents"] for e in swept)
    rec["status"] = "CLOSED"
    rec["updated_at"] = t
    rec["version"] += 1
    return ok(statement_out(rec))


@bp.post("/royalty-statements/<sid>/reopen")
def reopen_statement(sid):
    require_roles("FinanceOfficer")
    rec = _get_statement(sid)
    if rec["status"] != "CLOSED":
        raise_err("ERR_STATEMENT_NOT_CLOSED", "reopen requires CLOSED")
    t = now()
    for eid in rec["event_ids"]:
        e = STORE.events.get(eid)
        if e is not None:
            e["statement_id"] = None
            e["updated_at"] = t
            e["version"] += 1
    rec["event_ids"] = []
    rec["total_verified_seconds"] = 0
    rec["volume_tier"] = None
    rec["provisional_total_cents"] = None
    rec["total_accrual_cents"] = None
    rec["status"] = "OPEN"
    rec["updated_at"] = t
    rec["version"] += 1
    return ok(statement_out(rec))


@bp.post("/royalty-statements/<sid>/post")
def post_statement(sid):
    require_roles("FinanceOfficer")
    rec = _get_statement(sid)
    # PRD 3.7 sequence: state -> period ended -> payout minimum -> snapshot clean
    if rec["status"] != "CLOSED":
        raise_err("ERR_STATEMENT_NOT_CLOSED", "post requires CLOSED")
    if now() < rec["period_end"]:
        raise_err("ERR_PERIOD_NOT_ENDED", "The statement period has not ended")
    if rec["total_accrual_cents"] is None or rec["total_accrual_cents"] < calc.MIN_PAYOUT_CENTS:
        raise_err(
            "ERR_PAYOUT_BELOW_MINIMUM",
            "total_accrual_cents is below the 1000-cent payout minimum",
        )
    swept = [STORE.events.get(eid) for eid in rec["event_ids"]]
    if any(e is None or e["status"] != "VERIFIED" for e in swept):
        raise_err(
            "ERR_STATEMENT_EVENTS_DIRTY",
            "A snapshotted event is no longer VERIFIED",
        )
    t = now()
    for e in swept:
        e["status"] = "ROYALTY_POSTED"
        e["updated_at"] = t
        e["version"] += 1
    rec["status"] = "POSTED"
    rec["updated_at"] = t
    rec["version"] += 1
    return ok(statement_out(rec))
