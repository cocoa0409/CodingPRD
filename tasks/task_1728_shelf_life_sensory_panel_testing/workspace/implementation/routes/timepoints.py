"""SamplingTimePoint schedule and pulls (PRD §3.2/§3.3)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STUDY_STATE,
    ERR_DUPLICATE_TIME_POINT_DAY, ERR_INVALID_TIME_POINT_STATE,
    ERR_PULL_WINDOW_VIOLATION, ERR_CHAMBER_TEMP_MISMATCH,
    ERR_CHAMBER_CAPACITY_EXCEEDED, ERR_ARM_STUDY_MISMATCH,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    ser_tp, chamber_reserved, study_day, discard_unit, UNIT_PURPOSES,
)
from util import (
    body, paginate, req_enum, req_field, req_int, req_str, sort_created, touch,
)

bp = Blueprint("timepoints", __name__)


def get_tp(tp_id):
    t = db.store["time_points"].get(tp_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, f"SamplingTimePoint {tp_id} not found")
    return t


@bp.route("/sampling-time-points", methods=["POST"])
@require_roles("SensoryScientist")
def create_tp():
    b = body()
    study_id = req_str(b, "study_id")
    day_index = req_int(b, "day_index", min_value=0)
    study = db.store["studies"].get(study_id)
    if study is None:
        raise_err(ERR_NOT_FOUND, f"Study {study_id} not found")
    # PRD §3.2: allowed in DRAFT; after reopen, in IN_PROGRESS only when the
    # new day_index is strictly greater than the current study day.
    allowed = False
    if study["status"] == "DRAFT":
        allowed = True
    elif study["status"] == "IN_PROGRESS" and study.get("_reopened"):
        d = study_day(study)
        if d is not None and day_index > d:
            allowed = True
    if not allowed:
        raise_err(ERR_INVALID_STUDY_STATE,
                  "time points may be added in DRAFT, or in IN_PROGRESS "
                  "after a reopen with day_index beyond the current study "
                  "day")
    for t in db.store["time_points"].values():
        if t["study_id"] == study_id and t["day_index"] == day_index:
            raise_err(ERR_DUPLICATE_TIME_POINT_DAY,
                      f"day_index {day_index} already scheduled in this "
                      f"study")
    now = clock.now()
    tp = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "study_id": study_id,
        "day_index": day_index,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["time_points"][tp["id"]] = tp
    return respond(ser_tp(tp), 201)


@bp.route("/sampling-time-points", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_tps():
    items = sort_created(db.store["time_points"].values())
    study_id = request.args.get("study_id")
    status = request.args.get("status")
    if study_id is not None:
        items = [t for t in items if t["study_id"] == study_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pagination = paginate(items)
    return respond_list([ser_tp(t) for t in page], pagination)


@bp.route("/sampling-time-points/<tp_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_tp(tp_id):
    return respond(ser_tp(get_tp(tp_id)), 200)


@bp.route("/sampling-time-points/<tp_id>/pull", methods=["POST"])
@require_roles("SensoryScientist")
def pull_tp(tp_id):
    tp = get_tp(tp_id)
    b = body()
    chamber_id = req_str(b, "chamber_id")
    arm_id = req_str(b, "arm_id")
    quantity = req_field(b, "quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "quantity must be a number")
    if isinstance(quantity, float) and not quantity.is_integer():
        raise_err(ERR_INVALID_REQUEST, "quantity must be a whole number")
    quantity = int(quantity)
    if quantity <= 0:
        raise_err(ERR_INVALID_REQUEST, "quantity must be a positive number")
    unit_purpose = req_enum(b, "unit_purpose", UNIT_PURPOSES)
    chamber = db.store["chambers"].get(chamber_id)
    if chamber is None:
        raise_err(ERR_NOT_FOUND, f"StorageChamber {chamber_id} not found")
    arm = db.store["arms"].get(arm_id)
    if arm is None:
        raise_err(ERR_NOT_FOUND, f"StudyArm {arm_id} not found")
    study = db.store["studies"][tp["study_id"]]
    # Guard order pinned by PRD §3.3.
    if tp["status"] not in ("PENDING", "PULLED"):
        raise_err(ERR_INVALID_TIME_POINT_STATE,
                  "pull requires the time point to be PENDING or PULLED")
    if study["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "pull requires the study to be IN_PROGRESS")
    d = study_day(study)
    if d is None or not (tp["day_index"] <= d <= tp["day_index"] + 2):
        raise_err(ERR_PULL_WINDOW_VIOLATION,
                  "current study day is outside [day_index, day_index + 2]")
    if chamber["temp_c"] != study["storage_temp_c"]:
        raise_err(ERR_CHAMBER_TEMP_MISMATCH,
                  "chamber temp_c does not equal the study storage_temp_c")
    if chamber_reserved(chamber_id) + quantity > chamber["capacity_units"]:
        raise_err(ERR_CHAMBER_CAPACITY_EXCEEDED,
                  "chamber capacity would be exceeded by this pull")
    if arm["study_id"] != study["id"]:
        raise_err(ERR_ARM_STUDY_MISMATCH,
                  "arm_id does not belong to the time point's study")
    now = clock.now()
    for _ in range(quantity):
        unit = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "study_id": study["id"],
            "arm_id": arm_id,
            "chamber_id": chamber_id,
            "time_point_id": tp["id"],
            "unit_purpose": unit_purpose,
            "session_id": None,
            "retention_until_utc": None,
            "status": "STORED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.store["sample_units"][unit["id"]] = unit
    touch(chamber)  # occupancy increased by quantity
    if tp["status"] != "PULLED":
        tp["status"] = "PULLED"
        touch(tp)
    return respond(ser_tp(tp), 201)


@bp.route("/sampling-time-points/<tp_id>/close", methods=["POST"])
@require_roles("SensoryScientist")
def close_tp(tp_id):
    tp = get_tp(tp_id)
    if tp["status"] != "EVALUATED":
        raise_err(ERR_INVALID_TIME_POINT_STATE,
                  "close requires status EVALUATED")
    tp["status"] = "CLOSED"
    touch(tp)
    return respond(ser_tp(tp), 200)


@bp.route("/sampling-time-points/<tp_id>/skip", methods=["POST"])
@require_roles("SensoryScientist")
def skip_tp(tp_id):
    tp = get_tp(tp_id)
    if tp["status"] not in ("PENDING", "PULLED"):
        raise_err(ERR_INVALID_TIME_POINT_STATE,
                  "skip requires the time point to be PENDING or PULLED")
    study = db.store["studies"][tp["study_id"]]
    if study["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "skip requires the study to be IN_PROGRESS")
    was_pulled = tp["status"] == "PULLED"
    tp["status"] = "SKIPPED"
    touch(tp)
    if was_pulled:
        # EVALUATION units in STORED/CHECKED_OUT are discarded; RETAIN
        # units are preserved for the retention window (PRD §3.3).
        for unit in db.store["sample_units"].values():
            if (unit["time_point_id"] == tp_id
                    and unit["unit_purpose"] == "EVALUATION"
                    and unit["status"] in ("STORED", "CHECKED_OUT")):
                discard_unit(unit)
    return respond(ser_tp(tp), 200)
