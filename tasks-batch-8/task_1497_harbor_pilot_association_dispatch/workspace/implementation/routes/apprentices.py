"""Apprentice program: enrollment, progress logging, advancement."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, touch
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import apprentice_view, base_entity
from util import (
    body,
    dec,
    pagination_args,
    paginate,
    req_enum,
    req_int,
    req_num,
    req_str,
    round_half_up_2dp,
)

bp = Blueprint("apprentices", __name__)

TRACKS = ("STANDARD", "ACCELERATED")
STANDARD_TRIPS_REQUIRED = 50
ACCEL_TRIPS_REQUIRED = 40
ACCEL_EVAL_AVG_REQUIRED = Decimal("85")


def _get_apprentice(aid):
    a = DB["apprentices"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Apprentice does not exist")
    return a


@bp.post("/pilotage/apprentices")
def create_apprentice():
    auth(["AssociationAdmin"])
    data = body()
    full_name = req_str(data, "full_name")
    track = req_enum(data, "track", TRACKS)
    apprentice = base_entity()
    apprentice.update(
        {
            "full_name": full_name,
            "track": track,
            "trips_completed": 0,
            "evaluations_count": 0,
            "evaluation_avg": Decimal("0"),
            "status": "ENROLLED",
        }
    )
    DB["apprentices"][apprentice["id"]] = apprentice
    return ok(apprentice_view(apprentice), status=201)


@bp.get("/pilotage/apprentices")
def list_apprentices():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    items = list(DB["apprentices"].values())
    track = request.args.get("track")
    status = request.args.get("status")
    if track is not None:
        items = [a for a in items if a["track"] == track]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([apprentice_view(a) for a in page], total, limit, offset)


@bp.post("/pilotage/apprentices/<aid>/record-progress")
def record_progress(aid):
    auth(["AssociationAdmin"])
    apprentice = _get_apprentice(aid)
    data = body()
    trips_delta = req_int(data, "trips_delta")
    score = req_num(data, "evaluation_score")

    apprentice["trips_completed"] += trips_delta
    # Running average: (prior_avg * prior_count + new_score) / new_count,
    # rounded half-up to two decimal places on each recorded score.
    count = apprentice["evaluations_count"]
    new_avg = round_half_up_2dp(
        (apprentice["evaluation_avg"] * count + dec(score)) / Decimal(count + 1)
    )
    apprentice["evaluation_avg"] = new_avg
    apprentice["evaluations_count"] = count + 1
    touch(apprentice)
    return ok(apprentice_view(apprentice))


@bp.post("/pilotage/apprentices/<aid>/advance")
def advance(aid):
    auth(["AssociationAdmin"])
    apprentice = _get_apprentice(aid)
    data = body()

    if apprentice["status"] == "ENROLLED":
        # Track-selected readiness variant: STANDARD is trips-only; the
        # ACCELERATED variant adds an evaluation-average floor.
        if apprentice["track"] == "STANDARD":
            ready = apprentice["trips_completed"] >= STANDARD_TRIPS_REQUIRED
        else:
            ready = (
                apprentice["trips_completed"] >= ACCEL_TRIPS_REQUIRED
                and apprentice["evaluation_avg"] >= ACCEL_EVAL_AVG_REQUIRED
            )
        if not ready:
            raise ApiError(
                "ERR_READINESS_NOT_MET",
                422,
                "Apprentice readiness requirements not met for the track",
            )
        apprentice["status"] = "QUALIFIED"
    elif apprentice["status"] == "QUALIFIED":
        if data.get("exam_result") != "PASS":
            raise ApiError(
                "ERR_EXAM_NOT_PASSED",
                422,
                "exam_result must be PASS to advance to CERTIFIED",
            )
        apprentice["status"] = "CERTIFIED"
    else:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Apprentice cannot advance from {apprentice['status']}",
        )
    touch(apprentice)
    return ok(apprentice_view(apprentice))
