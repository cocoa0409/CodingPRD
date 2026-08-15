from flask import Blueprint, request

from auth import parse_auth, require_role, check_ownership
from db import store
from envelope import ok, paginate
from errors import (not_found, invalid_request, conflict, ERR_INVALID_STATE,
                    ERR_OUTAGE_OVERLAP)
from routes.generators import get_generator
from util import (get_body, check_unknown, req_string, req_int, req_enum,
                  req_datetime, opt_int, opt_datetime, opt_string, new_record,
                  serialize, sort_key, touch)
from services.availability import recompute_availability

bp = Blueprint("outages", __name__)
LIVE_STATUSES = ("SUBMITTED", "ACKNOWLEDGED", "APPROVED")


def get_outage(oid):
    o = store.outages.get(oid)
    if o is None:
        raise not_found("outage report not found")
    return o


def _check_derate(outage_type, derate_pct):
    if outage_type == "FULL" and derate_pct != 100:
        raise invalid_request("FULL outages require derate_pct exactly 100")
    if outage_type == "PARTIAL" and not (1 <= derate_pct <= 99):
        raise invalid_request("PARTIAL outages require derate_pct in 1..99")


def _overlap_violation(gen_id, start_dt, end_dt, exclude_id=None):
    """Half-open [start, end) intersection; adjacency is allowed."""
    for o in store.outages.values():
        if o["generator_asset_id"] != gen_id or o["id"] == exclude_id:
            continue
        if o["status"] not in LIVE_STATUSES:
            continue
        if start_dt < o["_end_dt"] and o["_start_dt"] < end_dt:
            return True
    return False


@bp.post("/market/generators/<generatorId>/outages")
def create_outage(generatorId):
    auth = parse_auth()
    require_role(auth, ["Trader"])
    body = get_body()
    check_unknown(body, {"outage_type", "derate_pct", "start_at", "end_at", "reason"})
    outage_type = req_enum(body, "outage_type", ("FULL", "PARTIAL"))
    derate_pct = req_int(body, "derate_pct")
    _check_derate(outage_type, derate_pct)
    raw_start, start_dt = req_datetime(body, "start_at")
    raw_end, end_dt = req_datetime(body, "end_at")
    if not start_dt < end_dt:
        raise invalid_request("start_at must be strictly before end_at")
    reason = req_string(body, "reason", allow_empty=True)

    gen = get_generator(generatorId)
    check_ownership(auth, gen["market_participant_id"])
    if _overlap_violation(gen["id"], start_dt, end_dt):
        raise conflict(ERR_OUTAGE_OVERLAP, "outage window overlaps a live report")

    rec = new_record()
    rec.update({
        "generator_asset_id": gen["id"],
        "outage_type": outage_type,
        "derate_pct": derate_pct,
        "start_at": raw_start,
        "end_at": raw_end,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "reason": reason,
        "denial_reason": None,
        "status": "SUBMITTED",
    })
    store.outages[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.get("/market/outages/<outageId>")
def get_one(outageId):
    parse_auth()
    return ok(serialize(get_outage(outageId)))


@bp.get("/market/outages")
def list_outages():
    parse_auth()
    rows = sorted(store.outages.values(), key=sort_key)
    gen_id = request.args.get("generator_asset_id")
    status = request.args.get("status")
    if gen_id is not None:
        rows = [r for r in rows if r["generator_asset_id"] == gen_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])


@bp.post("/market/outages/<outageId>/acknowledge")
def acknowledge(outageId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    outage = get_outage(outageId)
    if outage["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE, "only a SUBMITTED report can be acknowledged")
    outage["status"] = "ACKNOWLEDGED"
    touch(outage)
    return ok(serialize(outage))


@bp.post("/market/outages/<outageId>/approve")
def approve(outageId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    outage = get_outage(outageId)
    if outage["status"] != "ACKNOWLEDGED":
        raise conflict(ERR_INVALID_STATE, "only an ACKNOWLEDGED report can be approved")
    outage["status"] = "APPROVED"
    touch(outage)
    # cascade: availability -> obligations -> credit posture
    recompute_availability(store.generators[outage["generator_asset_id"]])
    return ok(serialize(outage))


@bp.post("/market/outages/<outageId>/deny")
def deny(outageId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"denial_reason"})
    denial_reason = req_string(body, "denial_reason", allow_empty=True)
    outage = get_outage(outageId)
    if outage["status"] != "ACKNOWLEDGED":
        raise conflict(ERR_INVALID_STATE, "only an ACKNOWLEDGED report can be denied")
    outage["status"] = "DENIED"
    outage["denial_reason"] = denial_reason
    touch(outage)
    return ok(serialize(outage))


@bp.post("/market/outages/<outageId>/resubmit")
def resubmit(outageId):
    auth = parse_auth()
    require_role(auth, ["Trader"])
    body = get_body()
    check_unknown(body, {"derate_pct", "start_at", "end_at", "reason"})
    derate_pct = opt_int(body, "derate_pct")
    raw_start, start_dt = opt_datetime(body, "start_at")
    raw_end, end_dt = opt_datetime(body, "end_at")
    reason = opt_string(body, "reason")

    outage = get_outage(outageId)
    gen = store.generators[outage["generator_asset_id"]]
    check_ownership(auth, gen["market_participant_id"])
    if outage["status"] != "DENIED":
        raise conflict(ERR_INVALID_STATE, "only a DENIED report can be resubmitted")

    new_derate = derate_pct if derate_pct is not None else outage["derate_pct"]
    new_start_dt = start_dt if start_dt is not None else outage["_start_dt"]
    new_end_dt = end_dt if end_dt is not None else outage["_end_dt"]
    _check_derate(outage["outage_type"], new_derate)
    if not new_start_dt < new_end_dt:
        raise invalid_request("start_at must be strictly before end_at")
    if _overlap_violation(gen["id"], new_start_dt, new_end_dt, exclude_id=outage["id"]):
        raise conflict(ERR_OUTAGE_OVERLAP, "outage window overlaps a live report")

    outage["derate_pct"] = new_derate
    if raw_start is not None:
        outage["start_at"] = raw_start
        outage["_start_dt"] = start_dt
    if raw_end is not None:
        outage["end_at"] = raw_end
        outage["_end_dt"] = end_dt
    if reason is not None:
        outage["reason"] = reason
    outage["status"] = "SUBMITTED"
    touch(outage)
    return ok(serialize(outage))


@bp.post("/market/outages/<outageId>/cancel")
def cancel(outageId):
    auth = parse_auth()
    require_role(auth, ["Trader"])
    outage = get_outage(outageId)
    gen = store.generators[outage["generator_asset_id"]]
    check_ownership(auth, gen["market_participant_id"])
    if outage["status"] not in LIVE_STATUSES:
        raise conflict(ERR_INVALID_STATE, "this report can no longer be cancelled")
    was_approved = outage["status"] == "APPROVED"
    outage["status"] = "CANCELLED"
    touch(outage)
    if was_approved:
        # compensate the approval cascade
        recompute_availability(gen)
    return ok(serialize(outage))
