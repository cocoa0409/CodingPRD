"""The deal universe: import, correction, reads and selection decline."""
from flask import Blueprint

from db import db, new_row, touch, DerivedWatch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from util import rhu
from validate import (ATTRIBUTION_STATUS, OUTCOME, RESEARCH_STATUS, SEGMENT,
                      body, fk_from_body, fk_from_query, opt_str, paginate,
                      pagination, present, query_enum, req_dt, req_enum,
                      req_number, req_str, resolve)

from services import calc, cascade, serialize
from services.listing import by_created_at

bp = Blueprint("deals", __name__)


def get_deal(deal_id):
    return resolve(db.deals, deal_id, "ERR_DEAL_NOT_FOUND")


@bp.post("/deals")
@endpoint(("ProgramAdmin",))
def import_deal():
    payload = body()
    program = fk_from_body(payload, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    competitor = fk_from_body(payload, "primary_competitor_id", db.competitors,
                              "ERR_COMPETITOR_NOT_FOUND")
    program_id = req_str(payload, "program_id")
    crm_deal_ref = req_str(payload, "crm_deal_ref")
    outcome = req_enum(payload, "outcome", OUTCOME)
    acr_usd = req_number(payload, "acr_usd")
    close_date = req_dt(payload, "close_date")
    segment = req_enum(payload, "segment", SEGMENT)
    sales_rep_user_ref = req_str(payload, "sales_rep_user_ref")
    competitor_id = opt_str(payload, "primary_competitor_id")
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")

    if acr_usd <= 0:
        fail("ERR_VALUE_OUT_OF_RANGE", "acr_usd must be greater than zero.")

    for existing in db.deals.values():
        if existing["program_id"] == program_id and \
                existing["crm_deal_ref"] == crm_deal_ref:
            fail("ERR_DUPLICATE_RESOURCE_KEY",
                 "That crm_deal_ref already exists in the program.")

    watch = DerivedWatch()
    if competitor is not None:
        watch.watch(competitor, calc.competitor_derived)

    deal = new_row({
        "program_id": program_id,
        "crm_deal_ref": crm_deal_ref,
        "outcome": outcome,
        "acr_usd": rhu(acr_usd, 2),
        "close_date": close_date,
        "segment": segment,
        "sales_rep_user_ref": sales_rep_user_ref,
        "primary_competitor_id": competitor_id,
        "sampling_frame_id": None,
        "stratum": None,
        "selection_rank_score": None,
        "research_status": "NOT_SELECTED",
        "attribution_status": "UNATTRIBUTED",
    })
    db.deals[deal["id"]] = deal
    watch.commit()
    return object_response(serialize.deal(deal), 201)


@bp.get("/deals/<deal_id>")
@endpoint(ANY_ROLE)
def read_deal(deal_id):
    return object_response(serialize.deal(get_deal(deal_id)))


@bp.get("/deals")
@endpoint(ANY_ROLE)
def list_deals():
    program_id = fk_from_query("program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    competitor_id = fk_from_query("primary_competitor_id", db.competitors,
                                  "ERR_COMPETITOR_NOT_FOUND")
    frame_id = fk_from_query("sampling_frame_id", db.sampling_frames,
                             "ERR_SAMPLING_FRAME_NOT_FOUND")
    outcome = query_enum("outcome", OUTCOME)
    segment = query_enum("segment", SEGMENT)
    research_status = query_enum("research_status", RESEARCH_STATUS)
    attribution_status = query_enum("attribution_status", ATTRIBUTION_STATUS)
    limit, offset = pagination()

    rows = list(db.deals.values())
    if program_id:
        rows = [d for d in rows if d["program_id"] == program_id]
    if competitor_id:
        rows = [d for d in rows if d.get("primary_competitor_id") == competitor_id]
    if frame_id:
        rows = [d for d in rows if d.get("sampling_frame_id") == frame_id]
    if outcome:
        rows = [d for d in rows if d["outcome"] == outcome]
    if segment:
        rows = [d for d in rows if d["segment"] == segment]
    if research_status:
        rows = [d for d in rows if d["research_status"] == research_status]
    if attribution_status:
        rows = [d for d in rows if d["attribution_status"] == attribution_status]

    # close_date DESC, then created_at ASC
    rows = sorted(by_created_at(rows), key=lambda d: -d["close_date"].timestamp())
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.deal(r) for r in page], limit, offset, total)


@bp.patch("/deals/<deal_id>")
@endpoint(("ProgramAdmin",))
def correct_deal(deal_id):
    deal = get_deal(deal_id)
    payload = body()
    competitor = fk_from_body(payload, "primary_competitor_id", db.competitors,
                              "ERR_COMPETITOR_NOT_FOUND")
    acr_usd = None
    if present(payload, "acr_usd"):
        acr_usd = req_number(payload, "acr_usd")
    segment = None
    if present(payload, "segment"):
        segment = req_enum(payload, "segment", SEGMENT)
    competitor_supplied = "primary_competitor_id" in payload
    competitor_id = None
    if competitor_supplied and payload["primary_competitor_id"] is not None:
        competitor_id = req_str(payload, "primary_competitor_id")

    if acr_usd is not None and acr_usd <= 0:
        fail("ERR_VALUE_OUT_OF_RANGE", "acr_usd must be greater than zero.")

    if deal["research_status"] == "SYNTHESIZED":
        fail("ERR_DEAL_STATE_INVALID", "A synthesized deal can no longer be corrected.")

    watch = DerivedWatch()
    old_competitor = db.competitors.get(deal.get("primary_competitor_id"))
    watch.watch(old_competitor, calc.competitor_derived)
    watch.watch(competitor, calc.competitor_derived)
    cascade.rescore_gaps_watch(watch, deal["id"])

    if acr_usd is not None:
        deal["acr_usd"] = rhu(acr_usd, 2)
    if segment is not None:
        deal["segment"] = segment
    if competitor_supplied:
        deal["primary_competitor_id"] = competitor_id
    touch(deal)
    watch.commit()
    return object_response(serialize.deal(deal))


@bp.post("/deals/<deal_id>/decline-selection")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def decline_selection(deal_id):
    deal = get_deal(deal_id)
    payload = body()
    opt_str(payload, "decline_note", allow_empty=True)

    if deal["research_status"] != "SELECTED":
        fail("ERR_DEAL_STATE_INVALID", "Only a SELECTED deal can be declined.")
    for interview in calc.interviews_of_deal(deal["id"]):
        if interview["status"] in ("SCHEDULED", "COMPLETED"):
            fail("ERR_DEAL_STATE_INVALID",
                 "A deal with a scheduled or completed interview cannot be declined.")
    frame = db.sampling_frames.get(deal.get("sampling_frame_id"))
    if frame is None or frame["status"] not in ("SEALED", "SUSPENDED"):
        fail("ERR_FRAME_STATE_INVALID",
             "The owning frame must be SEALED or SUSPENDED.")

    deal["research_status"] = "DECLINED"
    deal["selection_rank_score"] = None
    touch(deal)
    touch(frame)
    return object_response(serialize.deal(deal))
