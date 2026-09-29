"""Routing product gaps to the roadmap (PRD 3.9)."""
from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from validate import (GAP_STATUS, PRIORITY_BAND, TRIAGE_DECISION, body,
                      fk_from_body, fk_from_query, opt_str_array, paginate,
                      pagination, query_enum, query_str, req_enum, req_str,
                      resolve)

from services import calc, serialize
from services.listing import by_created_at

bp = Blueprint("product_gaps", __name__)


def get_gap(gap_id):
    return resolve(db.product_gaps, gap_id, "ERR_PRODUCT_GAP_NOT_FOUND")


def _resolve_response_ids(payload, field):
    raw = payload.get(field)
    if isinstance(raw, list) and all(isinstance(v, str) for v in raw):
        for response_id in raw:
            resolve(db.interview_responses, response_id,
                    "ERR_INTERVIEW_RESPONSE_NOT_FOUND")


@bp.post("/product-gaps")
@endpoint(("ProductManager",))
def intake_gap():
    payload = body()
    program = fk_from_body(payload, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    source = fk_from_body(payload, "source_response_id", db.interview_responses,
                          "ERR_INTERVIEW_RESPONSE_NOT_FOUND")
    _resolve_response_ids(payload, "additional_response_ids")
    req_str(payload, "program_id")
    req_str(payload, "source_response_id")
    gap_summary = req_str(payload, "gap_summary")
    additional = opt_str_array(payload, "additional_response_ids", default=None)
    if additional is None:
        additional = []
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")
    if source is None:
        fail("ERR_INTERVIEW_RESPONSE_NOT_FOUND")

    # 10. tenancy: every cited verbatim must sit in the named program
    cited = [source] + [db.interview_responses[r] for r in additional
                        if r in db.interview_responses]
    for response in cited:
        if calc.program_id_of_response(response) != program["id"]:
            fail("ERR_CROSS_PROGRAM_REFERENCE",
                 "A cited interview response belongs to a different program.")

    # 37. the seeding verbatim must be a product-gap answer
    for response in cited:
        if response["question_key"] != "PRODUCT_GAP":
            fail("ERR_RESPONSE_NOT_PRODUCT_GAP",
                 "Every cited response must have question_key PRODUCT_GAP.")

    deduped = []
    for response_id in additional:
        if response_id != source["id"] and response_id not in deduped:
            deduped.append(response_id)

    gap = new_row({
        "program_id": program["id"],
        "source_response_id": source["id"],
        "additional_response_ids": deduped,
        "gap_summary": gap_summary,
        "status": "NEW",
        "roadmap_epic_ref": None,
    })
    db.product_gaps[gap["id"]] = gap
    return object_response(serialize.product_gap(gap), 201)


@bp.get("/product-gaps/<gap_id>")
@endpoint(ANY_ROLE)
def read_gap(gap_id):
    return object_response(serialize.product_gap(get_gap(gap_id)))


@bp.get("/product-gaps")
@endpoint(ANY_ROLE)
def list_gaps():
    program_id = fk_from_query("program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    source_response_id = fk_from_query("source_response_id",
                                       db.interview_responses,
                                       "ERR_INTERVIEW_RESPONSE_NOT_FOUND")
    derived_competitor_id = query_str("derived_competitor_id")
    status = query_enum("status", GAP_STATUS)
    band = query_enum("roadmap_priority_band", PRIORITY_BAND)
    limit, offset = pagination()
    rows = list(db.product_gaps.values())
    if program_id:
        rows = [gp for gp in rows if gp["program_id"] == program_id]
    if source_response_id:
        rows = [gp for gp in rows if gp["source_response_id"] == source_response_id]
    if derived_competitor_id:
        rows = [gp for gp in rows
                if calc.gap_derived_competitor_id(gp) == derived_competitor_id]
    if status:
        rows = [gp for gp in rows if gp["status"] == status]
    if band:
        rows = [gp for gp in rows if calc.gap_current_metrics(gp)[4] == band]
    # impact_score DESC, then created_at ASC
    rows = sorted(by_created_at(rows), key=lambda gp: -calc.gap_current_metrics(gp)[3])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.product_gap(r) for r in page],
                         limit, offset, total)


@bp.post("/product-gaps/<gap_id>/triage")
@endpoint(("ProductManager",))
def triage_gap(gap_id):
    gap = get_gap(gap_id)
    payload = body()
    _resolve_response_ids(payload, "additional_response_ids")
    decision = req_enum(payload, "decision", TRIAGE_DECISION)
    additional = opt_str_array(payload, "additional_response_ids", default=None)

    # the evidence set grows before any band gate is evaluated
    if additional:
        existing = list(gap.get("additional_response_ids") or [])
        for response_id in additional:
            if response_id != gap["source_response_id"] and \
                    response_id not in existing:
                existing.append(response_id)
        gap["additional_response_ids"] = existing

    if decision == "NEEDS_EVIDENCE":
        if gap["status"] != "NEW":
            fail("ERR_PRODUCT_GAP_STATE_INVALID",
                 "NEEDS_EVIDENCE is only available from NEW.")
        gap["status"] = "TRIAGED"
    elif decision == "DECLINE":
        if gap["status"] not in ("NEW", "TRIAGED"):
            fail("ERR_PRODUCT_GAP_STATE_INVALID",
                 "Only a NEW or TRIAGED gap can be declined.")
        gap["status"] = "DECLINED"
        calc.freeze_gap_metrics(gap)
    else:
        if gap["status"] not in ("NEW", "TRIAGED"):
            fail("ERR_PRODUCT_GAP_STATE_INVALID",
                 "Only a NEW or TRIAGED gap can be accepted.")
        metrics = calc.gap_metrics(gap)
        if metrics[4] == "P3":
            fail("ERR_PRODUCT_GAP_STATE_INVALID",
                 "A gap scoring P3 cannot be accepted.")
        gap["status"] = "ACCEPTED"
        gap["_metrics"] = metrics
    touch(gap)
    return object_response(serialize.product_gap(gap))


@bp.post("/product-gaps/<gap_id>/promote")
@endpoint(("ProductManager",))
def promote_gap(gap_id):
    gap = get_gap(gap_id)
    payload = body()
    roadmap_epic_ref = req_str(payload, "roadmap_epic_ref")

    if gap["status"] != "ACCEPTED":
        fail("ERR_PRODUCT_GAP_STATE_INVALID", "Only an ACCEPTED gap can be promoted.")
    competitor_id, _, _, _, band = calc.gap_current_metrics(gap)
    if band not in ("P0", "P1"):
        fail("ERR_PRODUCT_GAP_STATE_INVALID",
             "Only a P0 or P1 gap can be promoted.")
    program = db.programs.get(gap["program_id"])
    if program is None or program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_STATE_INVALID", "The owning program must be ACTIVE.")

    # 34. the adoption gate, skipped when there is no published card
    if competitor_id:
        published = [c for c in calc.battlecards_of_competitor(competitor_id)
                     if c["status"] == "PUBLISHED" and c.get("published_at")]
        if published:
            published.sort(key=lambda c: (c["published_at"], c["_seq"]))
            latest = published[-1]
            if calc.adoption_counts(latest)[2] < calc.ADOPTION_GATE:
                fail("ERR_ADOPTION_BELOW_THRESHOLD",
                     "The competitor's latest published card is below the "
                     "adoption gate.")

    gap["roadmap_epic_ref"] = roadmap_epic_ref
    gap["status"] = "PROMOTED"
    touch(gap)
    return object_response(serialize.product_gap(gap))
