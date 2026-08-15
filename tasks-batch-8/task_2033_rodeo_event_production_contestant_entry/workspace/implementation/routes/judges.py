"""Judge and JudgeAssignment endpoints (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_or_404, ser, sorted_created, stamp
from util import as_enum, as_str, body, pagination_args, required

judges_bp = Blueprint("judges", __name__, url_prefix="/api")
assignments_bp = Blueprint("judge_assignments", __name__, url_prefix="/api")

POSITIONS = {"ARENA_1", "ARENA_2", "BARRIER", "TIMER"}
CERTIFICATIONS = {"PRCA_CARD", "PRCA_GOLD"}
BUFFER = timedelta(minutes=45)


@judges_bp.post("/judges")
def create_judge():
    auth(["CommitteeAdmin"])
    data = body()
    card_number = as_str(required(data, "card_number"), "card_number")
    full_name = as_str(required(data, "full_name"), "full_name")
    certification = as_enum(
        required(data, "certification"), "certification", CERTIFICATIONS
    )
    for j in DB["judges"].values():
        if j["card_number"] == card_number:
            raise ApiError("ERR_DUPLICATE_CARD", 409, "card_number already registered")
    rec = {
        "id": new_id(),
        "card_number": card_number,
        "full_name": full_name,
        "certification": certification,
    }
    stamp(rec)
    DB["judges"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@judges_bp.get("/judges")
def list_judges():
    auth(ALL_ROLES)
    card_number = request.args.get("card_number")
    certification = request.args.get("certification")
    items = DB["judges"].values()
    if card_number is not None:
        items = [j for j in items if j["card_number"] == card_number]
    if certification is not None:
        items = [j for j in items if j["certification"] == certification]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(j) for j in items[offset : offset + limit]], len(items), limit, offset
    )


@judges_bp.get("/judges/<judge_id>")
def get_judge(judge_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("judges", judge_id)))


@assignments_bp.post("/judge-assignments")
def create_assignment():
    auth(["CommitteeAdmin"])
    data = body()
    judge_id = data.get("judge_id")
    performance_id = data.get("performance_id")
    if judge_id is not None:
        get_or_404("judges", judge_id)
    if performance_id is not None:
        get_or_404("performances", performance_id)
    as_str(required(data, "judge_id"), "judge_id")
    as_str(required(data, "performance_id"), "performance_id")
    position = as_enum(required(data, "position"), "position", POSITIONS)
    judge = DB["judges"][judge_id]
    if position == "BARRIER" and judge["certification"] != "PRCA_GOLD":
        raise ApiError(
            "ERR_VALIDATION", 400, "BARRIER assignments require a PRCA_GOLD judge"
        )
    perf = DB["performances"][performance_id]
    # Buffered conflict: [starts_at - 45min, ends_at + 45min) intersection.
    new_start = perf["_starts_dt"] - BUFFER
    new_end = perf["_ends_dt"] + BUFFER
    for a in DB["judge_assignments"].values():
        if a["judge_id"] != judge_id:
            continue
        other = DB["performances"][a["performance_id"]]
        other_start = other["_starts_dt"] - BUFFER
        other_end = other["_ends_dt"] + BUFFER
        if new_start < other_end and other_start < new_end:
            raise ApiError(
                "ERR_JUDGE_CONFLICT",
                409,
                "Judge has a conflicting buffered assignment window",
            )
    rec = {
        "id": new_id(),
        "judge_id": judge_id,
        "performance_id": performance_id,
        "position": position,
    }
    stamp(rec)
    DB["judge_assignments"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@assignments_bp.get("/judge-assignments")
def list_assignments():
    auth(ALL_ROLES)
    judge_id = request.args.get("judge_id")
    performance_id = request.args.get("performance_id")
    items = DB["judge_assignments"].values()
    if judge_id is not None:
        items = [a for a in items if a["judge_id"] == judge_id]
    if performance_id is not None:
        items = [a for a in items if a["performance_id"] == performance_id]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(a) for a in items[offset : offset + limit]], len(items), limit, offset
    )


@assignments_bp.get("/judge-assignments/<assignment_id>")
def get_assignment(assignment_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("judge_assignments", assignment_id)))
