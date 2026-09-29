"""Plate sets and print jobs (PRD §3.7 second half and §3.8)."""

from flask import Blueprint

import config as C
from auth import ANY_ROLE, endpoint
from errors import ApiError
from num import D, floor_int
from response import object_response
from services import calc, cascade, refs
from store import serialize, store
from validation import (
    fetch,
    get_datetime,
    get_int,
    get_num,
    get_str,
    list_endpoint,
    parse_body,
    require_unique,
    resolve_fks,
)

bp = Blueprint("printing", __name__)


def ok(entity):
    return object_response(serialize(entity), 200)


def created(entity):
    return object_response(serialize(entity), 201)


# =============================================================== plate sets ==
@bp.post("/plate-sets")
@endpoint(["PrintOperator", "PlantAdmin"])
def create_plate_set():
    body = parse_body(required=True)
    plate_code = get_str(body, "plate_code")
    product_id = get_str(body, "product_id")
    color_count = get_int(body, "color_count", ge=1)
    wear_limit = get_int(body, "wear_limit_impressions", required=False, default=500000, ge=1)

    resolve_fks({"product_id": product_id})
    require_unique(store.plate_sets, "plate_code", plate_code)

    plate = store.new_common()
    plate.update(
        {
            "plate_code": plate_code,
            "product_id": product_id,
            "color_count": color_count,
            "mounted_press_id": None,
            "wear_limit_impressions": wear_limit,
            "status": "NEW",
            "impressions_count": 0,
            "nonconformance_count": 0,
        }
    )
    store.plate_sets[plate["id"]] = plate
    return created(plate)


@bp.get("/plate-sets/<plate_id>")
@endpoint(ANY_ROLE)
def read_plate_set(plate_id):
    return ok(fetch("plate_set", plate_id))


@bp.get("/plate-sets")
@endpoint(ANY_ROLE)
def list_plate_sets():
    return list_endpoint(store.plate_sets, ("product_id", "mounted_press_id", "status"))


@bp.post("/plate-sets/<plate_id>/mount")
@endpoint(["PrintOperator"])
def mount_plate_set(plate_id):
    body = parse_body(required=True)
    press_id = get_str(body, "press_id")
    plate = fetch("plate_set", plate_id)
    press = resolve_fks({"press_id": press_id})["press_id"]

    if plate["status"] != "NEW":
        raise ApiError("ERR_PLATE_STATE_INVALID", "Only a NEW plate set may be mounted.")
    if int(plate["color_count"]) > int(press["max_colors"]):
        raise ApiError(
            "ERR_PLATE_COLOR_EXCEEDS_PRESS",
            "color_count %s exceeds the press max_colors of %s."
            % (plate["color_count"], press["max_colors"]),
        )

    plate["status"] = "MOUNTED"
    plate["mounted_press_id"] = press["id"]
    store.touch(plate)
    return ok(plate)


# =============================================================== print jobs ==
@bp.post("/print-jobs")
@endpoint(["PrintOperator"])
def create_print_job():
    body = parse_body(required=True)
    job_code = get_str(body, "job_code")
    film_roll_id = get_str(body, "film_roll_id")
    plate_set_id = get_str(body, "plate_set_id")
    press_id = get_str(body, "press_id")
    raw_start, start = get_datetime(body, "window_start")
    raw_end, end = get_datetime(body, "window_end")
    if not end > start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'window_end' must be strictly after 'window_start'."
        )

    resolved = resolve_fks(
        {"film_roll_id": film_roll_id, "plate_set_id": plate_set_id, "press_id": press_id}
    )
    roll = resolved["film_roll_id"]
    plate = resolved["plate_set_id"]
    press = resolved["press_id"]
    require_unique(store.print_jobs, "job_code", job_code)

    if roll["status"] != "RELEASED":
        raise ApiError("ERR_ROLL_STATE_INVALID", "The fed roll must be in RELEASED status.")
    if plate["status"] != "MOUNTED":
        raise ApiError("ERR_PLATE_STATE_INVALID", "The plate set must be MOUNTED.")

    required = int(plate["color_count"])
    occupied = calc.cylinders_occupied(press, start, end)
    if occupied + required > int(press["cylinder_capacity"]):
        raise ApiError(
            "ERR_PRESS_CYLINDER_CAPACITY",
            "Overlapping jobs already occupy %d of the press's %s cylinders."
            % (occupied, press["cylinder_capacity"]),
        )

    job = store.new_common()
    job.update(
        {
            "job_code": job_code,
            "film_roll_id": roll["id"],
            "plate_set_id": plate["id"],
            "press_id": press["id"],
            "window_start": raw_start,
            "window_end": raw_end,
            "_window_start": start,
            "_window_end": end,
            "cylinders_required": required,
            "status": "SETUP",
            "registration_state": "REG_PENDING",
            "color_state": "COLOR_PENDING",
            "registration_drift_micron": None,
            "delta_e_measured": None,
            "setup_attempt_count": 0,
            "printed_kg": None,
            "blocked_reason": None,
        }
    )
    store.print_jobs[job["id"]] = job

    roll["status"] = "CONSUMED"
    store.touch(roll)
    return created(job)


@bp.get("/print-jobs/<job_id>")
@endpoint(ANY_ROLE)
def read_print_job(job_id):
    return ok(fetch("print_job", job_id))


@bp.get("/print-jobs")
@endpoint(ANY_ROLE)
def list_print_jobs():
    return list_endpoint(
        store.print_jobs,
        ("film_roll_id", "plate_set_id", "press_id", "status", "registration_state", "color_state"),
    )


def _exhaust_setup_attempts(job):
    if int(job["setup_attempt_count"]) > C.MAX_SETUP_ATTEMPTS:
        job["status"] = "BLOCKED"
        job["blocked_reason"] = (
            "Setup attempts exceeded the limit of %d; the press cylinder window was released."
            % C.MAX_SETUP_ATTEMPTS
        )


@bp.post("/print-jobs/<job_id>/registration-check")
@endpoint(["PrintOperator"])
def registration_check(job_id):
    body = parse_body(required=True)
    drift = get_num(body, "registration_drift_micron")
    job = fetch("print_job", job_id)
    if job["status"] != "SETUP":
        raise ApiError(
            "ERR_PRINT_JOB_STATE_INVALID", "Registration may only be measured on a SETUP job."
        )
    press = refs.press_of_job(job)
    job["registration_drift_micron"] = drift
    job["setup_attempt_count"] = int(job["setup_attempt_count"]) + 1
    job["registration_state"] = (
        "REG_PASS" if D(drift) <= D(press["registration_tolerance_micron"]) else "REG_FAIL"
    )
    _exhaust_setup_attempts(job)
    store.touch(job)
    return ok(job)


@bp.post("/print-jobs/<job_id>/color-proof")
@endpoint(["PrintOperator"])
def color_proof(job_id):
    body = parse_body(required=True)
    delta_e = get_num(body, "delta_e_measured")
    job = fetch("print_job", job_id)
    if job["status"] != "SETUP":
        raise ApiError(
            "ERR_PRINT_JOB_STATE_INVALID", "A color proof may only be recorded on a SETUP job."
        )
    press = refs.press_of_job(job)
    job["delta_e_measured"] = delta_e
    job["setup_attempt_count"] = int(job["setup_attempt_count"]) + 1
    job["color_state"] = (
        "COLOR_PASS" if D(delta_e) <= D(press["max_delta_e"]) else "COLOR_FAIL"
    )
    _exhaust_setup_attempts(job)
    store.touch(job)
    return ok(job)


@bp.post("/print-jobs/<job_id>/start-print")
@endpoint(["PrintOperator"])
def start_print(job_id):
    parse_body(required=False)
    job = fetch("print_job", job_id)
    if job["status"] != "SETUP":
        raise ApiError("ERR_PRINT_JOB_STATE_INVALID", "Only a SETUP job may start printing.")
    if job["registration_state"] != "REG_PASS" or job["color_state"] != "COLOR_PASS":
        raise ApiError(
            "ERR_PRINT_JOB_STATE_INVALID",
            "Both registration_state and color_state must have passed before printing.",
        )

    plate = refs.plate_of_job(job)
    roll = refs.roll_of_job(job)
    if plate is None or plate["status"] != "MOUNTED" or plate["mounted_press_id"] != job["press_id"]:
        raise ApiError(
            "ERR_PLATE_STATE_INVALID",
            "The plate set must still be MOUNTED on this job's press.",
        )
    if roll is None or roll["status"] != "CONSUMED":
        raise ApiError("ERR_ROLL_STATE_INVALID", "The fed roll must be in CONSUMED status.")
    if store.clock < job["_window_start"]:
        raise ApiError(
            "ERR_PRINT_WINDOW_NOT_OPEN",
            "The logical clock has not yet reached this job's window_start.",
        )

    job["status"] = "PRINTING"
    store.touch(job)
    return ok(job)


@bp.post("/print-jobs/<job_id>/complete")
@endpoint(["PrintOperator"])
def complete_print_job(job_id):
    body = parse_body(required=True)
    printed_kg = get_num(body, "printed_kg")
    job = fetch("print_job", job_id)
    if job["status"] != "PRINTING":
        raise ApiError("ERR_PRINT_JOB_STATE_INVALID", "Only a PRINTING job may be completed.")

    roll = refs.roll_of_job(job)
    if D(printed_kg) <= 0 or (roll is not None and D(printed_kg) > D(roll["net_kg"])):
        raise ApiError(
            "ERR_PRINTED_KG_EXCEEDS_ROLL",
            "printed_kg must be strictly positive and no greater than the roll's net_kg.",
        )

    job["printed_kg"] = printed_kg
    job["status"] = "COMPLETED"
    store.touch(job)

    plate = refs.plate_of_job(job)
    if plate is not None:
        plate["impressions_count"] = int(plate["impressions_count"]) + floor_int(D(printed_kg))
        worn = (
            plate["status"] == "MOUNTED"
            and plate["impressions_count"] >= int(plate["wear_limit_impressions"])
        )
        if worn:
            plate["status"] = "WORN"
            plate["mounted_press_id"] = None
        store.touch(plate)
        if worn:
            cascade.block_plate_setup_jobs(
                plate,
                "Plate set %s reached its wear limit of %s impressions."
                % (plate["plate_code"], plate["wear_limit_impressions"]),
            )
    return ok(job)
