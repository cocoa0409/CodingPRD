"""Trailers, compartments, washouts."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ApiError, raise_err, ERR_TRAILER_NOT_FOUND, ERR_EVENT_IN_FUTURE,
    ERR_INVALID_REQUEST,
)
from middleware import require_role
from response import success
from util import get_body, v_str, v_int, v_enum, v_dt, paginate

bp = Blueprint("trailers", __name__)

WASH_METHODS = {"HIGH_PRESSURE", "STEAM", "CHEMICAL"}


@bp.post("/haul/trailers")
def create_trailer():
    require_role("CarrierAdmin")
    body = get_body()
    trailer_no = v_str(body, "trailer_no")
    gvwr = v_int(body, "max_gross_weight_lb", min_value=1)
    comps = body.get("compartments")
    if not isinstance(comps, list):
        raise_err(ERR_INVALID_REQUEST, "compartments must be an array")
    seen_idx = set()
    parsed = []
    for c in comps:
        if not isinstance(c, dict):
            raise_err(ERR_INVALID_REQUEST, "each compartment must be an object")
        idx = v_int(c, "compartment_index", min_value=1)
        mh = v_int(c, "max_head_count", min_value=1)
        mw = v_int(c, "max_weight_lb", min_value=1)
        if idx in seen_idx:
            raise_err(ERR_INVALID_REQUEST, "duplicate compartment_index %s" % idx)
        seen_idx.add(idx)
        parsed.append((idx, mh, mw))
    for t in db.store["trailers"].values():
        if t["trailer_no"] == trailer_no:
            raise ApiError("ERR_DUPLICATE_TRAILER_NO", 409, "trailer_no already registered")
    rec = svc.new_common()
    rec.update({"trailer_no": trailer_no, "max_gross_weight_lb": gvwr,
                "last_washed_at": None, "dirtied_at": None})
    db.store["trailers"][rec["id"]] = rec
    for idx, mh, mw in parsed:
        crec = svc.new_common()
        crec.update({"trailer_id": rec["id"], "compartment_index": idx,
                     "max_head_count": mh, "max_weight_lb": mw})
        db.store["compartments"][crec["id"]] = crec
    return success(svc.trailer_json(rec), status=201)


@bp.get("/haul/trailers")
def list_trailers():
    now = db.now()
    items = [svc.trailer_json(t, now)
             for t in sorted(db.store["trailers"].values(), key=lambda t: t["seq"])]
    ws = request.args.get("washout_status")
    if ws is not None:
        items = [t for t in items if t["washout_status"] == ws]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.get("/haul/trailers/<tid>")
def get_trailer(tid):
    t = db.store["trailers"].get(tid)
    if t is None:
        raise_err(ERR_TRAILER_NOT_FOUND)
    return success(svc.trailer_json(t))


@bp.get("/haul/trailers/<tid>/compartments")
def list_compartments(tid):
    t = db.store["trailers"].get(tid)
    if t is None:
        raise_err(ERR_TRAILER_NOT_FOUND)
    comps = [c for c in db.store["compartments"].values() if c["trailer_id"] == tid]
    comps.sort(key=lambda c: (c["compartment_index"], c["seq"]))
    page, meta = paginate([svc.compartment_json(c) for c in comps])
    return success(page, response_type="array", pagination=meta)


@bp.post("/haul/trailers/<tid>/washouts")
def record_washout(tid):
    require_role("WashoutOperator", "CarrierAdmin")
    t = db.store["trailers"].get(tid)
    if t is None:
        raise_err(ERR_TRAILER_NOT_FOUND)
    body = get_body()
    washed_at = v_dt(body, "washed_at")
    method = v_enum(body, "method", WASH_METHODS)
    note = v_str(body, "operator_note", required=False)
    if washed_at > db.now():
        raise_err(ERR_EVENT_IN_FUTURE, "washed_at is after the current time")
    rec = svc.new_immutable()
    rec.update({"trailer_id": tid, "washed_at": washed_at, "method": method,
                "operator_note": note})
    db.store["washouts"][rec["id"]] = rec
    t["last_washed_at"] = washed_at
    t["dirtied_at"] = None
    svc.touch(t)
    return success(svc.washout_json(rec), status=201)


@bp.get("/haul/trailers/<tid>/washouts")
def list_washouts(tid):
    t = db.store["trailers"].get(tid)
    if t is None:
        raise_err(ERR_TRAILER_NOT_FOUND)
    items = sorted(
        (w for w in db.store["washouts"].values() if w["trailer_id"] == tid),
        key=lambda w: w["seq"])
    page, meta = paginate([svc.washout_json(w) for w in items])
    return success(page, response_type="array", pagination=meta)
