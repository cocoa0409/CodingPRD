"""QualityInspection endpoints (PRD §3.7)."""

from decimal import Decimal
from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_inspection
from services import (
    get_inspection,
    get_order,
    get_resource,
    get_run,
    check_order_completion,
)
from util import (
    BOOTH_TURNOVER,
    GRADE_RANK,
    as_enum,
    as_positive_int,
    as_string,
    body_dict,
    dec,
    is_number,
    opt_present,
    parse_dt,
    q2,
    q3,
    req_present,
)

from routes import bp

INSPECTION_TYPES = {"FIRST_ARTICLE", "FINAL"}
DISPOSITIONS = {"PASS", "REWORK", "SCRAP"}


@bp.route("/quality-inspections", methods=["POST"])
@endpoint({"QualityInspector"})
def create_inspection(user_id, role):
    body = body_dict(request.get_json(silent=True))
    order_id = as_string(req_present(body, "production_order_id"), "production_order_id")
    inspection_type = as_enum(req_present(body, "inspection_type"), "inspection_type", INSPECTION_TYPES)
    # Conditional field: forming_run_id iff FIRST_ARTICLE
    run_id = opt_present(body, "forming_run_id")
    if inspection_type == "FIRST_ARTICLE":
        if run_id is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "forming_run_id is required when inspection_type is FIRST_ARTICLE"
            )
        run_id = as_string(run_id, "forming_run_id")
    else:
        if run_id is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "forming_run_id must be null when inspection_type is FINAL"
            )
    booth_id = as_string(req_present(body, "booth_id"), "booth_id")
    scheduled_start = parse_dt(req_present(body, "scheduled_start"), "scheduled_start")
    scheduled_end = parse_dt(req_present(body, "scheduled_end"), "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be later than scheduled_start")
    measurements = req_present(body, "wall_measurements_mm")
    if (
        not isinstance(measurements, list)
        or len(measurements) == 0
        or any(not is_number(m) or m <= 0 for m in measurements)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "wall_measurements_mm must be a non-empty array of positive numbers",
        )

    # p4 existence (body order: order, run, booth)
    order = get_order(order_id)
    run = get_run(run_id) if run_id is not None else None
    booth = get_resource(booth_id)
    # Referenced booth must be an INSPECTION_BOOTH
    if booth["resource_type"] != "INSPECTION_BOOTH":
        raise ApiError("ERR_INVALID_REQUEST", "booth_id must reference an INSPECTION_BOOTH")
    # p7 cleanliness: booth grade >= order grade
    if GRADE_RANK[booth["cleanliness_grade"]] < GRADE_RANK[order["cleanliness_grade"]]:
        raise ApiError(
            "ERR_GRADE_INCOMPATIBLE", "Booth cleanliness grade is below the order grade"
        )
    # p8 temporal (a): half-open overlap against RECORDED inspections on this booth
    for other in STORE["quality_inspections"].values():
        if other["booth_id"] != booth["id"] or other["status"] != "RECORDED":
            continue
        if not (scheduled_end <= other["scheduled_start"] or scheduled_start >= other["scheduled_end"]):
            raise ApiError(
                "ERR_BOOTH_WINDOW_OVERLAP",
                "The window intersects another RECORDED inspection on this booth",
            )
    # p8 temporal (b): 30-minute turnover buffer after INDUSTRIAL sessions
    # before FOOD/MEDICAL sessions (new session as the later one).
    if order["cleanliness_grade"] in ("FOOD", "MEDICAL"):
        for other in STORE["quality_inspections"].values():
            if other["booth_id"] != booth["id"] or other["status"] != "RECORDED":
                continue
            if other["scheduled_end"] > scheduled_start:
                continue  # overlapping or later sessions are not "the earlier session"
            other_order = get_order(other["production_order_id"])
            if other_order["cleanliness_grade"] != "INDUSTRIAL":
                continue
            if scheduled_start < other["scheduled_end"] + BOOTH_TURNOVER:
                raise ApiError(
                    "ERR_BOOTH_BUFFER_VIOLATION",
                    "A FOOD/MEDICAL session must begin at least 30 minutes after an INDUSTRIAL session",
                )
    # p9 domain: inspection-type gates
    if inspection_type == "FIRST_ARTICLE" and run["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_REQUEST", "FIRST_ARTICLE inspections must reference a COMPLETED run")
    if inspection_type == "FINAL" and order["shots_completed"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "FINAL inspections require order shots_completed > 0")

    # Wall statistics: per-measurement rounding FIRST, then aggregate (pinned order)
    rounded = [q3(dec(m)) for m in measurements]
    min_wall = min(rounded)
    avg_wall = q3(sum(rounded) / Decimal(len(rounded)))
    nominal = order["spec_nominal_wall_mm"]
    deviation = q2((nominal - min_wall) / nominal * Decimal(100))

    rec = new_record()
    rec.update({
        "production_order_id": order["id"],
        "forming_run_id": run["id"] if run else None,
        "booth_id": booth["id"],
        "inspection_type": inspection_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "wall_measurements_mm": measurements,
        "min_wall_mm": min_wall,
        "avg_wall_mm": avg_wall,
        "deviation_pct": deviation,
        "disposition": None,
        "scrapped_qty": None,
        "recorded_by_user_id": user_id,
        "dispositioned_by_user_id": None,
        "status": "RECORDED",
    })
    STORE["quality_inspections"][rec["id"]] = rec
    return ok_object(ser_inspection(rec), 201)


@bp.route("/quality-inspections", methods=["GET"])
@endpoint(ANY_ROLE)
def list_inspections(user_id, role):
    items = list(STORE["quality_inspections"].values())
    order_id = request.args.get("production_order_id")
    if order_id is not None:
        items = [i for i in items if i["production_order_id"] == order_id]
    run_id = request.args.get("forming_run_id")
    if run_id is not None:
        items = [i for i in items if i["forming_run_id"] == run_id]
    booth_id = request.args.get("booth_id")
    if booth_id is not None:
        items = [i for i in items if i["booth_id"] == booth_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items, ser_inspection)


@bp.route("/quality-inspections/<inspectionId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_inspection(user_id, role, inspectionId):
    return ok_object(ser_inspection(get_inspection(inspectionId)))


@bp.route("/quality-inspections/<inspectionId>/disposition", methods=["POST"])
@endpoint({"QualityInspector"})
def disposition_inspection(user_id, role, inspectionId):
    body = body_dict(request.get_json(silent=True))
    disposition = as_enum(req_present(body, "disposition"), "disposition", DISPOSITIONS)
    # Conditional field: scrapped_qty iff SCRAP
    raw_qty = opt_present(body, "scrapped_qty")
    if disposition == "SCRAP":
        if raw_qty is None:
            raise ApiError("ERR_INVALID_REQUEST", "scrapped_qty is required when disposition is SCRAP")
        scrapped_qty = as_positive_int(raw_qty, "scrapped_qty")
    else:
        if raw_qty is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "scrapped_qty must be null unless disposition is SCRAP"
            )
        scrapped_qty = None

    insp = get_inspection(inspectionId)
    # p6 state
    if insp["status"] != "RECORDED":
        raise ApiError(
            "ERR_INSPECTION_ALREADY_DISPOSITIONED", "Disposition requires status RECORDED"
        )
    # Segregation of duties: dispositioner must differ from recorder
    if user_id == insp["recorded_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The dispositioning inspector must differ from the recording inspector",
        )
    order = get_order(insp["production_order_id"])
    spec_min = order["spec_min_wall_mm"]
    # Measurement-consistency gates
    if disposition == "PASS" and insp["min_wall_mm"] < spec_min:
        raise ApiError(
            "ERR_DISPOSITION_CONTRADICTS_MEASUREMENT",
            "PASS requires min_wall_mm >= spec_min_wall_mm",
        )
    if disposition == "SCRAP":
        if not (insp["min_wall_mm"] < spec_min):
            raise ApiError(
                "ERR_DISPOSITION_CONTRADICTS_MEASUREMENT",
                "SCRAP requires min_wall_mm < spec_min_wall_mm",
            )
        if scrapped_qty > order["shots_completed"]:
            raise ApiError(
                "ERR_INVALID_REQUEST", "scrapped_qty must not exceed the order's shots_completed"
            )

    insp["disposition"] = disposition
    insp["scrapped_qty"] = scrapped_qty
    insp["dispositioned_by_user_id"] = user_id
    insp["status"] = "DISPOSITIONED"
    bump(insp)

    if disposition == "PASS":
        if order["quality_status"] == "PENDING":
            order["quality_status"] = "RELEASED"
        bump(order)
        check_order_completion(order)
    elif disposition == "REWORK":
        if order["quality_status"] == "PENDING":
            order["quality_status"] = "REWORK_HOLD"
        if order["schedule_status"] == "RUNNING":
            order["schedule_status"] = "ON_HOLD"
        bump(order)
    else:  # SCRAP
        order["shots_completed"] -= scrapped_qty
        order["shots_scrapped"] += scrapped_qty
        bump(order)

    return ok_object(ser_inspection(insp))
