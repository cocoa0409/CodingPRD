"""Performance endpoints: schedule, list, get, transitions (PRD 3.1, 3.6)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    cancel_performance_cascade,
    get_or_404,
    rodeo_of_event,
    ser,
    sorted_created,
    stamp,
    touch,
)
from util import (
    as_int_range,
    as_iso_dt,
    as_str,
    body,
    pagination_args,
    parse_dt,
    required,
)

bp = Blueprint("performances", __name__, url_prefix="/api")

_ACTIONS = {"COMPLETE_PERFORMANCE", "CANCEL_PERFORMANCE"}


@bp.post("/performances")
def create_performance():
    auth(["CommitteeAdmin"])
    data = body()
    rodeo_id = data.get("rodeo_id")
    if rodeo_id is not None:
        get_or_404("rodeos", rodeo_id)
    as_str(required(data, "rodeo_id"), "rodeo_id")
    label = as_str(required(data, "label"), "label")
    arena = as_str(required(data, "arena"), "arena")
    starts_at = as_iso_dt(required(data, "starts_at"), "starts_at")
    ends_at = as_iso_dt(required(data, "ends_at"), "ends_at")
    arena_capacity = as_int_range(
        required(data, "arena_capacity"), "arena_capacity", 1, None
    )
    starts_dt = parse_dt(starts_at)
    ends_dt = parse_dt(ends_at)
    if ends_dt <= starts_dt:
        raise ApiError("ERR_VALIDATION", 400, "ends_at must be later than starts_at")
    # Half-open [starts_at, ends_at) overlap within same rodeo + arena while
    # SCHEDULED; touching intervals are permitted.
    for p in DB["performances"].values():
        if (
            p["rodeo_id"] == rodeo_id
            and p["arena"] == arena
            and p["status"] == "SCHEDULED"
            and starts_dt < p["_ends_dt"]
            and p["_starts_dt"] < ends_dt
        ):
            raise ApiError(
                "ERR_PERFORMANCE_OVERLAP",
                409,
                "Performance overlaps an existing SCHEDULED performance in this arena",
            )
    rec = {
        "id": new_id(),
        "rodeo_id": rodeo_id,
        "label": label,
        "arena": arena,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "arena_capacity": arena_capacity,
        "sold_tickets": 0,
        "status": "SCHEDULED",
        "_starts_dt": starts_dt,
        "_ends_dt": ends_dt,
    }
    stamp(rec)
    DB["performances"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/performances")
def list_performances():
    auth(ALL_ROLES)
    rodeo_id = request.args.get("rodeo_id")
    status = request.args.get("status")
    items = DB["performances"].values()
    if rodeo_id is not None:
        items = [p for p in items if p["rodeo_id"] == rodeo_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(p) for p in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/performances/<performance_id>")
def get_performance(performance_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("performances", performance_id)))


@bp.post("/performances/<performance_id>/transition")
def transition_performance(performance_id):
    auth(["CommitteeAdmin"])
    perf = get_or_404("performances", performance_id)
    data = body()
    action = data.get("action")
    if action not in _ACTIONS:
        raise ApiError(
            "ERR_VALIDATION", 400, f"Field action must be one of {sorted(_ACTIONS)}"
        )
    if perf["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Action {action} is not valid from status {perf['status']}",
        )
    if action == "COMPLETE_PERFORMANCE":
        rodeo = DB["rodeos"][perf["rodeo_id"]]
        if rodeo["posture"] != "IN_PROGRESS":
            raise ApiError(
                "ERR_RODEO_NOT_OPEN",
                409,
                "Completing a performance requires the rodeo to be IN_PROGRESS",
            )
        perf["status"] = "COMPLETED"
    else:  # CANCEL_PERFORMANCE
        for a in DB["draw_assignments"].values():
            if a["performance_id"] == perf["id"] and a["status"] in (
                "PENDING",
                "COMPLETED",
            ):
                raise ApiError(
                    "ERR_PERF_HAS_ASSIGNMENTS",
                    409,
                    "Performance still has live draw assignments",
                )
        cancel_performance_cascade(perf)
        perf["status"] = "CANCELLED"
    touch(perf)
    return ok(ser(perf))
