"""Supply agreements and offtake commitments."""
from decimal import Decimal

from flask import Blueprint, request

from common import (ApiError, actor, as_date, as_dec, as_int, as_str,
                    bad_request, body_dict, created, fk_not_found,
                    invalid_state, not_found, ok, ok_list, ownership_err,
                    paginate, raw_body, ser)
from logic import (D0, current_month, fulfillment_for, new_record,
                   rollover_agreement, rollover_commitment, sorted_items, touch)
from store import db

bp = Blueprint("agreements", __name__)


# ---------------------------------------------------------------------------
# Supply agreements
# ---------------------------------------------------------------------------

@bp.post("/api/supply-agreements")
def create_agreement():
    uid, _ = actor({"Generator"})
    raw = raw_body()
    if isinstance(raw, dict):
        gid = raw.get("generator_id")
        if gid is not None and gid != uid:
            ownership_err()
    body = body_dict()
    gen_id = as_str(body, "generator_id")
    stream_id = as_str(body, "stream_id")
    committed = as_int(body, "committed_monthly_tons")
    if committed <= 0:
        bad_request("committed_monthly_tons must be positive")
    rev_share = as_dec(body, "revenue_share_pct_to_generator")
    if not (D0 < rev_share < Decimal("1")):
        bad_request("revenue_share_pct_to_generator must be in (0, 1)")
    freight_share = as_dec(body, "freight_share_pct_to_generator")
    if not (D0 <= freight_share <= Decimal("1")):
        bad_request("freight_share_pct_to_generator must be in [0, 1]")
    term_start = as_date(body, "term_start")
    term_end = as_date(body, "term_end")
    if term_end < term_start:
        bad_request("term_end must be on or after term_start")
    if gen_id not in db.generators:
        fk_not_found("generator_id does not resolve to a Generator")
    if stream_id not in db.streams:
        fk_not_found("stream_id does not resolve to a ByproductStream")
    rec = new_record()
    rec.update(generator_id=gen_id, stream_id=stream_id,
               committed_monthly_tons=committed,
               revenue_share_pct_to_generator=rev_share,
               freight_share_pct_to_generator=freight_share,
               term_start=term_start, term_end=term_end,
               booked_month_to_date_tons=D0, delivered_month_to_date_tons=D0,
               counter_month=current_month(), fulfillment_status="UNMET",
               status="DRAFT")
    db.agreements[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/supply-agreements")
def list_agreements():
    actor()
    items = sorted_items(db.agreements.values())
    for ag in items:
        rollover_agreement(ag)
    gid = request.args.get("generator_id")
    sid = request.args.get("stream_id")
    st = request.args.get("status")
    if gid is not None:
        items = [r for r in items if r["generator_id"] == gid]
    if sid is not None:
        items = [r for r in items if r["stream_id"] == sid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.get("/api/supply-agreements/<aid>")
def get_agreement(aid):
    actor()
    rec = db.agreements.get(aid)
    if rec is None:
        not_found("Supply agreement not found")
    rollover_agreement(rec)
    return ok(ser(rec))


def _load_agreement(aid):
    rec = db.agreements.get(aid)
    if rec is None:
        not_found("Supply agreement not found")
    return rec


@bp.post("/api/supply-agreements/<aid>/activate")
def activate_agreement(aid):
    actor({"BrokerOps"})
    rec = _load_agreement(aid)
    if rec["status"] != "DRAFT":
        invalid_state()
    stream = db.streams.get(rec["stream_id"])
    if stream is None or stream["status"] not in ("CHARACTERIZED", "ACTIVE"):
        raise ApiError("ERR_STREAM_NOT_CHARACTERIZED", 422,
                       "Stream is not CHARACTERIZED or ACTIVE")
    rec["status"] = "ACTIVE"
    rec["counter_month"] = current_month()
    touch(rec)
    return ok(ser(rec))


@bp.post("/api/supply-agreements/<aid>/suspend")
def suspend_agreement(aid):
    actor({"BrokerOps"})
    rec = _load_agreement(aid)
    if rec["status"] != "ACTIVE":
        invalid_state()
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok(ser(rec))


@bp.post("/api/supply-agreements/<aid>/resume")
def resume_agreement(aid):
    actor({"BrokerOps"})
    rec = _load_agreement(aid)
    if rec["status"] != "SUSPENDED":
        invalid_state()
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(ser(rec))


@bp.post("/api/supply-agreements/<aid>/terminate")
def terminate_agreement(aid):
    actor({"BrokerOps"})
    rec = _load_agreement(aid)
    if rec["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        invalid_state()
    rec["status"] = "TERMINATED"
    touch(rec)
    return ok(ser(rec))


# ---------------------------------------------------------------------------
# Offtake commitments
# ---------------------------------------------------------------------------

@bp.post("/api/offtake-commitments")
def create_commitment():
    uid, _ = actor({"Offtaker"})
    raw = raw_body()
    if isinstance(raw, dict):
        oid = raw.get("offtaker_id")
        if oid is not None and oid != uid:
            ownership_err()
    body = body_dict()
    offtaker_id = as_str(body, "offtaker_id")
    stream_id = as_str(body, "stream_id")
    dest = as_str(body, "destination_state_code")
    committed = as_int(body, "committed_monthly_tons")
    if committed <= 0:
        bad_request("committed_monthly_tons must be positive")
    max_moisture = as_dec(body, "max_moisture_pct")
    max_arsenic = as_dec(body, "max_arsenic_ppm")
    offtaker = db.offtakers.get(offtaker_id)
    if offtaker is None:
        fk_not_found("offtaker_id does not resolve to an Offtaker")
    if stream_id not in db.streams:
        fk_not_found("stream_id does not resolve to a ByproductStream")
    if dest not in offtaker["receiving_state_codes"]:
        raise ApiError("ERR_DESTINATION_NOT_SERVED", 422,
                       "destination_state_code not in receiving_state_codes")
    rec = new_record()
    rec.update(offtaker_id=offtaker_id, stream_id=stream_id,
               destination_state_code=dest,
               committed_monthly_tons=committed,
               max_moisture_pct=max_moisture, max_arsenic_ppm=max_arsenic,
               accepted_month_to_date_tons=D0, cumulative_rejected_tons=D0,
               counter_month=current_month(), status="DRAFT")
    db.commitments[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/offtake-commitments")
def list_commitments():
    actor()
    items = sorted_items(db.commitments.values())
    for cm in items:
        rollover_commitment(cm)
    oid = request.args.get("offtaker_id")
    sid = request.args.get("stream_id")
    st = request.args.get("status")
    if oid is not None:
        items = [r for r in items if r["offtaker_id"] == oid]
    if sid is not None:
        items = [r for r in items if r["stream_id"] == sid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.get("/api/offtake-commitments/<cid>")
def get_commitment(cid):
    actor()
    rec = db.commitments.get(cid)
    if rec is None:
        not_found("Offtake commitment not found")
    rollover_commitment(rec)
    return ok(ser(rec))


def _load_commitment(cid):
    rec = db.commitments.get(cid)
    if rec is None:
        not_found("Offtake commitment not found")
    return rec


@bp.post("/api/offtake-commitments/<cid>/activate")
def activate_commitment(cid):
    actor({"BrokerOps"})
    rec = _load_commitment(cid)
    if rec["status"] != "DRAFT":
        invalid_state()
    stream = db.streams.get(rec["stream_id"])
    if stream is None or stream["status"] not in ("CHARACTERIZED", "ACTIVE"):
        raise ApiError("ERR_STREAM_NOT_CHARACTERIZED", 422,
                       "Stream is not CHARACTERIZED or ACTIVE")
    rec["status"] = "ACTIVE"
    rec["counter_month"] = current_month()
    touch(rec)
    return ok(ser(rec))


@bp.post("/api/offtake-commitments/<cid>/resume")
def resume_commitment(cid):
    actor({"BrokerOps"})
    rec = _load_commitment(cid)
    if rec["status"] != "SUSPENDED":
        invalid_state()
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(ser(rec))


@bp.post("/api/offtake-commitments/<cid>/terminate")
def terminate_commitment(cid):
    actor({"BrokerOps"})
    rec = _load_commitment(cid)
    if rec["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        invalid_state()
    rec["status"] = "TERMINATED"
    touch(rec)
    return ok(ser(rec))
