"""ColorMeasurement endpoints: Delta-E recording and judgment (PRD 3.6)."""
from flask import Blueprint

from calc import DELTA_E_PASS_MAX
from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_job, get_measurement, sorted_created, touch
from util import as_enum, as_int, as_num, body, pagination_args, reject_unknown, required

bp = Blueprint("measurements", __name__)


@bp.post("/label-jobs/jobs/<job_id>/color-measurements")
def record_measurement(job_id):
    auth(["PressOperator"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, {"station_no", "delta_e"})
    station_no = as_int(required(data, "station_no"), "station_no")
    delta_e = as_num(required(data, "delta_e"), "delta_e")
    if job["status"] != "ON_PRESS":
        raise ApiError(
            "ERR_JOB_NOT_ON_PRESS",
            409,
            "recording a measurement requires job in ON_PRESS",
        )
    press = DB["presses"][job["press_id"]]
    if station_no < 1 or station_no > press["station_count"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "station_no must be between 1 and the press's station_count",
        )
    ts = now_iso()
    measurement = {
        "id": new_id(),
        "job_id": job_id,
        "station_no": station_no,
        "delta_e": delta_e,
        "verdict": "PENDING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["measurements"][measurement["id"]] = measurement
    return ok(measurement, 201)


@bp.get("/label-jobs/jobs/<job_id>/color-measurements")
def list_measurements(job_id):
    auth(ALL_ROLES)
    get_job(job_id)
    limit, offset = pagination_args()
    items = sorted_created(
        m for m in DB["measurements"].values() if m["job_id"] == job_id
    )
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.post("/label-jobs/jobs/<job_id>/color-measurements/<measurement_id>/judge")
def judge_measurement(job_id, measurement_id):
    auth(["QualityManager"])
    job = get_job(job_id)
    measurement = get_measurement(job_id, measurement_id)
    data = body()
    reject_unknown(data, {"verdict"})
    verdict = as_enum(required(data, "verdict"), "verdict", {"PASS", "FAIL"})
    if measurement["verdict"] != "PENDING":
        raise ApiError(
            "ERR_MEASUREMENT_ALREADY_JUDGED",
            409,
            "judge requires measurement verdict PENDING",
        )
    if job["status"] != "ON_PRESS":
        raise ApiError(
            "ERR_JOB_NOT_ON_PRESS",
            409,
            "judging a measurement requires job in ON_PRESS",
        )
    if verdict == "PASS" and measurement["delta_e"] > DELTA_E_PASS_MAX:
        raise ApiError(
            "ERR_DELTA_E_EXCEEDS_LIMIT",
            422,
            "judging PASS requires delta_e <= 2.0",
        )
    measurement["verdict"] = verdict
    touch(measurement)
    return ok(measurement)
