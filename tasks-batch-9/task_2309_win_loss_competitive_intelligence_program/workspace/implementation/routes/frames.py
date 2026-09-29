"""Sampling frames, quotas and the selector (PRD 3.3)."""
from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import array_response, list_response, object_response
from util import dec, rhu
from validate import (FRAME_STATUS, OUTCOME, SELECTION_BASIS, body, fk_from_body,
                      fk_from_query, opt_int, opt_str, paginate, pagination,
                      query_enum, req_dt, req_enum, req_int, req_str, resolve)

from services import calc, serialize
from services.listing import by_created_at

bp = Blueprint("frames", __name__)


def get_frame(frame_id):
    return resolve(db.sampling_frames, frame_id, "ERR_SAMPLING_FRAME_NOT_FOUND")


@bp.post("/sampling-frames")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def define_frame():
    payload = body()
    program = fk_from_body(payload, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    program_id = req_str(payload, "program_id")
    label = req_str(payload, "label")
    window_start = req_dt(payload, "window_start")
    window_end = req_dt(payload, "window_end")
    quota_won = req_int(payload, "quota_won")
    quota_lost = req_int(payload, "quota_lost")
    quota_no_decision = req_int(payload, "quota_no_decision")
    selection_basis = req_enum(payload, "selection_basis", SELECTION_BASIS)
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")

    if quota_won < 0 or quota_lost < 0 or quota_no_decision < 0:
        fail("ERR_VALUE_OUT_OF_RANGE", "Every quota must be at least zero.")
    if not window_start < window_end:
        fail("ERR_INVALID_TIME_WINDOW",
             "window_start must be strictly before window_end.")

    frame = new_row({
        "program_id": program_id,
        "label": label,
        "window_start": window_start,
        "window_end": window_end,
        "quota_won": quota_won,
        "quota_lost": quota_lost,
        "quota_no_decision": quota_no_decision,
        "selection_basis": selection_basis,
        "status": "DRAFT",
    })
    db.sampling_frames[frame["id"]] = frame
    return object_response(serialize.sampling_frame(frame), 201)


@bp.get("/sampling-frames/<frame_id>")
@endpoint(ANY_ROLE)
def read_frame(frame_id):
    return object_response(serialize.sampling_frame(get_frame(frame_id)))


@bp.post("/sampling-frames/<frame_id>/seal")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def seal_frame(frame_id):
    frame = get_frame(frame_id)
    if frame["status"] != "DRAFT":
        fail("ERR_FRAME_STATE_INVALID", "Only a DRAFT frame can be sealed.")
    program = db.programs.get(frame["program_id"])
    if program is None or program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_STATE_INVALID", "The owning program must be ACTIVE.")
    if calc.total_quota(frame) < 1:
        fail("ERR_FRAME_STATE_INVALID", "The three quotas must sum to at least 1.")
    frame["status"] = "SEALED"
    touch(frame)
    return object_response(serialize.sampling_frame(frame))


@bp.post("/sampling-frames/<frame_id>/close")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def close_frame(frame_id):
    frame = get_frame(frame_id)
    if frame["status"] not in ("SEALED", "SUSPENDED"):
        fail("ERR_FRAME_STATE_INVALID",
             "Only a SEALED or SUSPENDED frame can be closed.")
    frame["status"] = "CLOSED"
    touch(frame)
    return object_response(serialize.sampling_frame(frame))


def _contacts_of_deal(deal_id):
    return [c for c in db.buyer_contacts.values() if c["deal_id"] == deal_id]


def _is_eligible(deal, frame, program, stratum):
    if deal["program_id"] != frame["program_id"]:
        return False
    if deal["research_status"] != "NOT_SELECTED":
        return False
    if deal["outcome"] != stratum:
        return False
    if dec(deal["acr_usd"]) < dec(program["min_deal_value_usd"]):
        return False
    if not (deal["close_date"] >= frame["window_start"]
            and deal["close_date"] < frame["window_end"]):
        return False
    for contact in _contacts_of_deal(deal["id"]):
        if contact["consent_status"] in ("REQUESTED", "GRANTED"):
            return True
    return False


@bp.post("/sampling-frames/<frame_id>/draw")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def draw_frame(frame_id):
    frame = get_frame(frame_id)
    payload = body()
    pinned = fk_from_body(payload, "deal_id", db.deals, "ERR_DEAL_NOT_FOUND")
    stratum = req_enum(payload, "stratum", OUTCOME)
    requested_count = opt_int(payload, "requested_count", 1)
    opt_str(payload, "deal_id")
    if requested_count < 1:
        fail("ERR_INVALID_REQUEST", "requested_count must be at least 1.")

    program = db.programs.get(frame["program_id"])
    if pinned is not None and pinned["program_id"] != frame["program_id"]:
        fail("ERR_CROSS_PROGRAM_REFERENCE",
             "The pinned deal belongs to a different program.")
    if frame["status"] != "SEALED":
        fail("ERR_FRAME_STATE_INVALID", "Only a SEALED frame can be drawn from.")
    if program is None or calc.posture(program) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN", "The program's posture is FROZEN.")
    if pinned is not None:
        if not (pinned["close_date"] >= frame["window_start"]
                and pinned["close_date"] < frame["window_end"]):
            fail("ERR_DEAL_OUTSIDE_FRAME_WINDOW",
                 "The pinned deal's close_date lies outside the frame window.")

    available = calc.open_slots(frame, stratum)
    if available < requested_count:
        fail("ERR_STRATUM_QUOTA_EXHAUSTED",
             "The requested stratum has fewer open slots than requested.")

    candidates = [pinned] if pinned is not None else list(db.deals.values())
    pool = [d for d in candidates if _is_eligible(d, frame, program, stratum)]
    if not pool:
        fail("ERR_NO_ELIGIBLE_DEALS", "No deal satisfies the eligibility filter.")

    scored = []
    for deal in pool:
        score = calc.selection_rank_score(deal, frame, db.clock)
        scored.append((calc.selector_sort_key(deal, frame, score), deal, score))
    scored.sort(key=lambda item: item[0])

    take = min(available, requested_count)
    drawn = []
    for _, deal, score in scored[:take]:
        deal["sampling_frame_id"] = frame["id"]
        deal["stratum"] = deal["outcome"]
        deal["selection_rank_score"] = score
        deal["research_status"] = "SELECTED"
        touch(deal)
        drawn.append(deal)
    if drawn:
        touch(frame)
    return array_response([serialize.deal(d) for d in drawn], 201)


@bp.get("/sampling-frames")
@endpoint(ANY_ROLE)
def list_frames():
    program_id = fk_from_query("program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    status = query_enum("status", FRAME_STATUS)
    selection_basis = query_enum("selection_basis", SELECTION_BASIS)
    limit, offset = pagination()
    rows = list(db.sampling_frames.values())
    if program_id:
        rows = [f for f in rows if f["program_id"] == program_id]
    if status:
        rows = [f for f in rows if f["status"] == status]
    if selection_basis:
        rows = [f for f in rows if f["selection_basis"] == selection_basis]
    rows = sorted(by_created_at(rows), key=lambda f: f["window_start"].timestamp())
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.sampling_frame(r) for r in page],
                         limit, offset, total)
