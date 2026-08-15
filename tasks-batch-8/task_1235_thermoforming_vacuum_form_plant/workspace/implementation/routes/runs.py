"""FormingRun endpoints (PRD §3.6)."""

from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_run
from services import (
    get_order,
    get_resource,
    get_run,
    get_tool,
    check_order_completion,
)
from util import (
    GRADE_RANK,
    PROTO_SHOT_LIMIT,
    as_nonnegative_decimal,
    as_nonnegative_int,
    as_positive_decimal,
    as_positive_int,
    as_string,
    body_dict,
    dec,
    parse_dt,
    req_present,
)

from routes import bp


@bp.route("/forming-runs", methods=["POST"])
@endpoint({"ProductionScheduler"})
def create_run(user_id, role):
    body = body_dict(request.get_json(silent=True))
    order_id = as_string(req_present(body, "production_order_id"), "production_order_id")
    station_id = as_string(req_present(body, "station_id"), "station_id")
    planned_start = parse_dt(req_present(body, "planned_start"), "planned_start")
    planned_end = parse_dt(req_present(body, "planned_end"), "planned_end")
    if planned_end <= planned_start:
        raise ApiError("ERR_INVALID_REQUEST", "planned_end must be later than planned_start")
    oven_temp = as_positive_decimal(req_present(body, "oven_temp_c"), "oven_temp_c")
    cycle_time = as_positive_int(req_present(body, "cycle_time_s"), "cycle_time_s")
    shots_planned = as_positive_int(req_present(body, "shots_planned"), "shots_planned")

    # p4 existence (body order: order, then station)
    order = get_order(order_id)
    station = get_resource(station_id)
    # Referenced station must be a FORMING_STATION
    if station["resource_type"] != "FORMING_STATION":
        raise ApiError("ERR_INVALID_REQUEST", "station_id must reference a FORMING_STATION")
    # p6 state: order must be STAGED or RUNNING
    if order["schedule_status"] not in ("STAGED", "RUNNING"):
        raise ApiError(
            "ERR_ORDER_NOT_RUNNING", "Run create requires order schedule_status STAGED or RUNNING"
        )
    # p7 cleanliness: tool grade and station grade must each be >= order grade
    tool = get_tool(order["tool_id"])
    need = GRADE_RANK[order["cleanliness_grade"]]
    if GRADE_RANK[tool["cleanliness_grade"]] < need or GRADE_RANK[station["cleanliness_grade"]] < need:
        raise ApiError(
            "ERR_GRADE_INCOMPATIBLE", "Tool or station cleanliness grade is below the order grade"
        )
    # p8 temporal: station half-open window overlap against SCHEDULED runs only.
    # Back-to-back (new.start == existing.end) is allowed.
    for other in STORE["forming_runs"].values():
        if other["station_id"] != station["id"] or other["status"] != "SCHEDULED":
            continue
        if not (planned_end <= other["planned_start"] or planned_start >= other["planned_end"]):
            raise ApiError(
                "ERR_STATION_WINDOW_OVERLAP",
                "The window intersects another SCHEDULED run on this station",
            )
    # p9 domain: prototype cumulative planned shots
    if tool["status"] == "PROTOTYPE":
        cumulative = shots_planned
        for other in STORE["forming_runs"].values():
            if other["production_order_id"] == order["id"]:
                cumulative += other["shots_planned"]
        limit = tool["proto_shot_limit"] if tool["proto_shot_limit"] is not None else PROTO_SHOT_LIMIT
        if cumulative > limit:
            raise ApiError(
                "ERR_PROTOTYPE_SHOT_LIMIT_EXCEEDED",
                "Cumulative planned shots exceed the prototype shot limit",
            )

    rec = new_record()
    rec.update({
        "production_order_id": order["id"],
        "station_id": station["id"],
        "planned_start": planned_start,
        "planned_end": planned_end,
        "oven_temp_c": oven_temp,
        "cycle_time_s": cycle_time,
        "shots_planned": shots_planned,
        "shots_completed": None,
        "scrap_weight_kg": None,
        "actual_end": None,
        "status": "SCHEDULED",
    })
    STORE["forming_runs"][rec["id"]] = rec
    # The order's first run flips STAGED -> RUNNING
    if order["schedule_status"] == "STAGED":
        order["schedule_status"] = "RUNNING"
        bump(order)
    return ok_object(ser_run(rec), 201)


@bp.route("/forming-runs", methods=["GET"])
@endpoint(ANY_ROLE)
def list_runs(user_id, role):
    items = list(STORE["forming_runs"].values())
    order_id = request.args.get("production_order_id")
    if order_id is not None:
        items = [r for r in items if r["production_order_id"] == order_id]
    station_id = request.args.get("station_id")
    if station_id is not None:
        items = [r for r in items if r["station_id"] == station_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, ser_run)


@bp.route("/forming-runs/<runId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_run(user_id, role, runId):
    return ok_object(ser_run(get_run(runId)))


@bp.route("/forming-runs/<runId>/complete", methods=["POST"])
@endpoint({"ProductionScheduler"})
def complete_run(user_id, role, runId):
    body = body_dict(request.get_json(silent=True))
    shots_completed = as_nonnegative_int(req_present(body, "shots_completed"), "shots_completed")
    scrap_weight = as_nonnegative_decimal(req_present(body, "scrap_weight_kg"), "scrap_weight_kg")
    actual_end = parse_dt(req_present(body, "actual_end"), "actual_end")

    run = get_run(runId)
    # p6 state
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_RUN_STATE", "Run complete requires status SCHEDULED")
    # actual_end must be later than planned_start
    if actual_end <= run["planned_start"]:
        raise ApiError("ERR_INVALID_REQUEST", "actual_end must be later than planned_start")

    run["shots_completed"] = shots_completed
    run["scrap_weight_kg"] = scrap_weight
    run["actual_end"] = actual_end
    run["status"] = "COMPLETED"
    bump(run)

    order = get_order(run["production_order_id"])
    order["shots_completed"] += shots_completed
    bump(order)

    tool = get_tool(order["tool_id"])
    tool["shots_used"] += shots_completed
    bump(tool)

    if scrap_weight > 0:
        # Intake point of the regrind loop: PENDING scrap record
        scrap = new_record(common=False)
        scrap.update({
            "forming_run_id": run["id"],
            "regrind_batch_id": None,
            "resin_type": order["resin_type"],
            "weight_kg": scrap_weight,
            "status": "PENDING",
        })
        STORE["scrap_records"][scrap["id"]] = scrap

    check_order_completion(order)
    return ok_object(ser_run(run))
