"""Program lifecycle, the incentive budget, the interview guide and program reads."""
from decimal import Decimal

from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from util import dec, fmt_dt, money, rhu, ratio
from validate import (COMPETITOR_STATUS, COMPETITOR_TIER, EMPLOYMENT_TYPE,
                      FRAME_STATUS, INDEPENDENCE_MODE, QUESTION_KEYS,
                      REQUIRED_GUIDE_KEYS, SEGMENT, TREND_BASIS,
                      ANALYST_STATUS, body, opt_enum, opt_int, paginate,
                      pagination, query_dt_required, query_enum, req_enum_array,
                      req_int, req_number, req_str, resolve)

from services import calc, cascade, serialize
from services.listing import by_created_at

bp = Blueprint("programs", __name__)


def get_program(program_id):
    return resolve(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")


# ------------------------------------------------------------------ create/read
@bp.post("/programs")
@endpoint(("ProgramAdmin",))
def create_program():
    payload = body()
    name = req_str(payload, "name")
    fiscal_quarter = req_str(payload, "fiscal_quarter")
    budget = req_number(payload, "incentive_budget_usd")
    cap = req_number(payload, "interview_incentive_cap_usd")
    min_deal_value = req_number(payload, "min_deal_value_usd")
    if "required_question_keys" in payload and payload["required_question_keys"] is not None:
        keys = req_enum_array(payload, "required_question_keys", QUESTION_KEYS)
    else:
        keys = list(REQUIRED_GUIDE_KEYS)
    max_open = opt_int(payload, "max_open_interviews_per_analyst", 3)
    mode = opt_enum(payload, "independence_mode", INDEPENDENCE_MODE, "STRICT")

    if budget < 0 or cap < 0 or min_deal_value < 0:
        fail("ERR_VALUE_OUT_OF_RANGE",
             "Monetary program parameters must be at least zero.")
    if max_open < 1:
        fail("ERR_VALUE_OUT_OF_RANGE",
             "max_open_interviews_per_analyst must be at least 1.")

    program = new_row({
        "name": name,
        "fiscal_quarter": fiscal_quarter,
        "status": "DRAFT",
        "incentive_budget_usd": rhu(budget, 2),
        "interview_incentive_cap_usd": rhu(cap, 2),
        "min_deal_value_usd": rhu(min_deal_value, 2),
        "required_question_keys": list(keys),
        "guide_version": 1,
        "max_open_interviews_per_analyst": max_open,
        "independence_mode": mode,
    })
    db.programs[program["id"]] = program
    return object_response(serialize.program(program), 201)


@bp.get("/programs/<program_id>")
@endpoint(ANY_ROLE)
def read_program(program_id):
    return object_response(serialize.program(get_program(program_id)))


# --------------------------------------------------------------------- lifecycle
@bp.post("/programs/<program_id>/activate")
@endpoint(("ProgramAdmin",))
def activate_program(program_id):
    program = get_program(program_id)
    if program["status"] != "DRAFT":
        fail("ERR_PROGRAM_STATE_INVALID", "Only a DRAFT program can be activated.")
    if dec(program["incentive_budget_usd"]) <= 0:
        fail("ERR_PROGRAM_STATE_INVALID",
             "incentive_budget_usd must be greater than zero to activate.")
    if not set(REQUIRED_GUIDE_KEYS).issubset(set(program["required_question_keys"])):
        fail("ERR_PROGRAM_STATE_INVALID",
             "required_question_keys must contain the three mandatory topics.")
    program["status"] = "ACTIVE"
    touch(program)
    cascade.apply_posture_cascade(program)
    return object_response(serialize.program(program))


@bp.post("/programs/<program_id>/begin-closing")
@endpoint(("ProgramAdmin",))
def begin_closing_program(program_id):
    program = get_program(program_id)
    if program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_STATE_INVALID", "Only an ACTIVE program can begin closing.")
    for interview in calc.interviews_of_program(program["id"]):
        if interview["status"] == "SCHEDULED":
            fail("ERR_PROGRAM_STATE_INVALID",
                 "Every interview must be settled before closing begins.")
    program["status"] = "CLOSING"
    touch(program)
    for frame in cascade.frames_of_program(program["id"]):
        if frame["status"] in ("DRAFT", "SEALED", "SUSPENDED"):
            frame["status"] = "CLOSED"
            touch(frame)
    cascade.apply_posture_cascade(program)
    return object_response(serialize.program(program))


@bp.post("/programs/<program_id>/close")
@endpoint(("ProgramAdmin",))
def close_program(program_id):
    program = get_program(program_id)
    if program["status"] != "CLOSING":
        fail("ERR_PROGRAM_STATE_INVALID", "Only a CLOSING program can be closed.")
    program_deal_ids = {d["id"] for d in db.deals.values()
                        if d["program_id"] == program["id"]}
    for attribution in db.loss_attributions.values():
        if attribution["deal_id"] in program_deal_ids and \
                attribution["status"] == "PROVISIONAL":
            fail("ERR_PROGRAM_STATE_INVALID",
                 "Every attribution must be settled before the program closes.")
    program["status"] = "CLOSED"
    touch(program)
    for competitor in db.competitors.values():
        if competitor["program_id"] != program["id"]:
            continue
        for card in calc.battlecards_of_competitor(competitor["id"]):
            if card["status"] in ("DRAFT", "LEGAL_REVIEW", "APPROVED"):
                card["status"] = "WITHDRAWN"
                touch(card)
    cascade.apply_posture_cascade(program)
    return object_response(serialize.program(program))


@bp.put("/programs/<program_id>/incentive-budget")
@endpoint(("ProgramAdmin",))
def replace_incentive_budget(program_id):
    program = get_program(program_id)
    payload = body()
    budget = req_number(payload, "incentive_budget_usd")
    expected = req_int(payload, "expected_program_version")
    if budget < 0:
        fail("ERR_VALUE_OUT_OF_RANGE", "incentive_budget_usd must be at least zero.")
    if expected != program["version"]:
        fail("ERR_STALE_PROGRAM_VERSION",
             "expected_program_version does not match the program's current version.")
    if program["status"] not in ("DRAFT", "ACTIVE", "CLOSING"):
        fail("ERR_PROGRAM_STATE_INVALID",
             "The incentive budget cannot be replaced in this program state.")
    if rhu(budget, 2) < calc.incentive_paid(program):
        fail("ERR_VALUE_OUT_OF_RANGE",
             "The budget cannot fall below money already paid.")
    program["incentive_budget_usd"] = rhu(budget, 2)
    touch(program)
    cascade.apply_posture_cascade(program)
    return object_response(serialize.program(program))


@bp.put("/programs/<program_id>/interview-guide")
@endpoint(("ProgramAdmin",))
def replace_interview_guide(program_id):
    program = get_program(program_id)
    payload = body()
    keys = req_enum_array(payload, "required_question_keys", QUESTION_KEYS,
                          non_empty=True)
    if not set(REQUIRED_GUIDE_KEYS).issubset(set(keys)):
        fail("ERR_INVALID_REQUEST",
             "required_question_keys must contain the three mandatory topics.")
    if program["status"] not in ("DRAFT", "ACTIVE"):
        fail("ERR_PROGRAM_STATE_INVALID",
             "The interview guide can only be replaced while DRAFT or ACTIVE.")
    program["required_question_keys"] = list(keys)
    program["guide_version"] = program["guide_version"] + 1
    touch(program)
    return object_response(serialize.program(program))


# ------------------------------------------------------------- reverse lookups
@bp.get("/programs/<program_id>/competitors")
@endpoint(ANY_ROLE)
def list_program_competitors(program_id):
    program = get_program(program_id)
    status = query_enum("status", COMPETITOR_STATUS)
    tier = query_enum("tier", COMPETITOR_TIER)
    limit, offset = pagination()
    rows = [c for c in db.competitors.values() if c["program_id"] == program["id"]]
    if status:
        rows = [c for c in rows if c["status"] == status]
    if tier:
        rows = [c for c in rows if c["tier"] == tier]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.competitor(r) for r in page],
                         limit, offset, total)


@bp.get("/programs/<program_id>/analysts")
@endpoint(ANY_ROLE)
def list_program_analysts(program_id):
    program = get_program(program_id)
    status = query_enum("status", ANALYST_STATUS)
    employment_type = query_enum("employment_type", EMPLOYMENT_TYPE)
    limit, offset = pagination()
    rows = [a for a in db.analysts.values() if a["program_id"] == program["id"]]
    if status:
        rows = [a for a in rows if a["status"] == status]
    if employment_type:
        rows = [a for a in rows if a["employment_type"] == employment_type]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.analyst(r) for r in page], limit, offset, total)


@bp.get("/programs/<program_id>/sampling-frames")
@endpoint(ANY_ROLE)
def list_program_frames(program_id):
    program = get_program(program_id)
    status = query_enum("status", FRAME_STATUS)
    limit, offset = pagination()
    rows = [f for f in db.sampling_frames.values() if f["program_id"] == program["id"]]
    if status:
        rows = [f for f in rows if f["status"] == status]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.sampling_frame(r) for r in page],
                         limit, offset, total)


# ------------------------------------------------------------------ loss trends
@bp.get("/programs/<program_id>/loss-trends")
@endpoint(ANY_ROLE)
def loss_trends(program_id):
    program = get_program(program_id)
    window_start = query_dt_required("window_start")
    window_end = query_dt_required("window_end")
    basis = query_enum("basis", TREND_BASIS) or "RATIFIED_ONLY"
    segment_filter = query_enum("segment", SEGMENT)
    if not window_start < window_end:
        fail("ERR_INVALID_TIME_WINDOW",
             "window_start must be strictly before window_end.")

    allowed_statuses = ("RATIFIED",) if basis == "RATIFIED_ONLY" \
        else ("RATIFIED", "PROVISIONAL")

    participating = []
    for attribution in db.loss_attributions.values():
        if attribution["status"] not in allowed_statuses:
            continue
        deal = db.deals.get(attribution["deal_id"])
        if deal is None or deal["program_id"] != program["id"]:
            continue
        if deal["outcome"] not in ("LOST", "NO_DECISION"):
            continue
        if not (deal["close_date"] >= window_start and deal["close_date"] < window_end):
            continue
        if segment_filter and deal["segment"] != segment_filter:
            continue
        participating.append((attribution, deal))

    buckets = {}
    for attribution, deal in participating:
        segment = deal["segment"]
        bucket = buckets.setdefault(segment, {})
        primary = db.loss_reasons.get(attribution["primary_reason_id"])
        if primary is not None:
            root = calc.root_reason(primary)
            if root is not None:
                bucket[root["id"]] = bucket.get(root["id"], Decimal("0")) \
                    + dec(attribution["weight_primary"])
        secondary_id = attribution.get("secondary_reason_id")
        if secondary_id:
            secondary = db.loss_reasons.get(secondary_id)
            if secondary is not None:
                root = calc.root_reason(secondary)
                if root is not None:
                    bucket[root["id"]] = bucket.get(root["id"], Decimal("0")) \
                        + dec(attribution["weight_secondary"])

    segments = []
    for segment in ("ENTERPRISE", "MIDMARKET", "SMB"):
        bucket = buckets.get(segment)
        if not bucket:
            continue
        segment_total = sum(bucket.values(), Decimal("0"))
        if segment_total == 0:
            continue
        rows = []
        for reason_id, weight in bucket.items():
            reason = db.loss_reasons.get(reason_id)
            rows.append({
                "root_reason_id": reason_id,
                "root_reason_code": reason["code"] if reason else None,
                "weighted_total": money(weight),
                "share": ratio(weight / segment_total),
                "_weight": weight,
                "_code": reason["code"] if reason else "",
            })
        rows.sort(key=lambda r: (-Decimal(str(r["share"])), -r["_weight"], r["_code"]))
        for row in rows:
            row.pop("_weight")
            row.pop("_code")
        segments.append({
            "segment": segment,
            "segment_total": money(segment_total),
            "rows": rows,
        })

    return object_response({
        "basis": basis,
        "window_start": fmt_dt(window_start),
        "window_end": fmt_dt(window_end),
        "attribution_count": len(participating),
        "segments": segments,
    })


# -------------------------------------------------------------- enablement sweep
@bp.post("/programs/<program_id>/enablement-sweep")
@endpoint(("EnablementManager",))
def enablement_sweep(program_id):
    program = get_program(program_id)
    expired_ids = []
    recomputed_ids = []
    assignments = sorted(db.enablement_assignments.values(), key=lambda a: a["_seq"])
    for assignment in assignments:
        card = db.battlecards.get(assignment["battlecard_id"])
        if card is None:
            continue
        if calc.program_id_of_battlecard(card) != program["id"]:
            continue
        if assignment["status"] not in ("ASSIGNED", "FAILED"):
            continue
        if not assignment["due_at"] < db.clock:
            continue
        assignment["status"] = "EXPIRED"
        touch(assignment)
        expired_ids.append(assignment["id"])
        if card["id"] not in recomputed_ids:
            recomputed_ids.append(card["id"])
    for card_id in recomputed_ids:
        touch(db.battlecards[card_id])
    return object_response({
        "expired_count": len(expired_ids),
        "expired_assignment_ids": expired_ids,
        "recomputed_battlecard_ids": recomputed_ids,
    })
