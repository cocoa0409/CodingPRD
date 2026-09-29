"""Worker enrolment, industrial-hygiene sampling and medical clearance."""
import datetime

from flask import Blueprint, g

from authz import (
    DESIGN_ENGINEER,
    JOB_CLASSES,
    JOB_SAFETY,
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    SAFETY_OFFICER,
    endpoint,
    require_job_class,
)
from errors import ApiError
from helpers import apply_filters, lookup, paginated, samples_of_worker
from response import object_response
from store import db
from validation import fail, forbid, present, require
from services.constants import (
    BLL_RETURN_UG_PER_DL,
    EVENT_WINDOW_DAYS,
    REMOVAL_THRESHOLD_INDEX,
)
from services.exposure import air_twa_index, blood_peak_index
from services.plant_service import refresh_plant

bp = Blueprint("workers", __name__)

WORKER_READERS = [
    PLANT_ADMIN,
    SAFETY_OFFICER,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    DESIGN_ENGINEER,
]

CREATE_SPEC = {
    "plant_id": {"type": "id", "required": True},
    "full_name": {"type": "string", "required": True},
    "job_class": {"type": "enum", "required": True, "values": JOB_CLASSES},
    "hire_date": {"type": "datetime", "required": True},
}

SAMPLE_SPEC = {
    "sample_type": {"type": "enum", "required": True, "values": ["AIR", "BLOOD"]},
    "air_lead_ug_per_m3": {"type": "number", "gte": 0},
    "sample_duration_minutes": {"type": "int", "gte": 1, "lte": 960},
    "blood_lead_ug_per_dl": {"type": "number", "gte": 0},
    "sampled_at": {"type": "datetime", "required": True},
}

CLEARANCE_SPEC = {"clearance_note": {"type": "string", "allow_blank": True}}

WORKER_FILTERS = {
    "plant_id": "plant_id",
    "job_class": "job_class",
    "removal_status": "removal_status",
}
DEFAULT_ORDER = [("created_at", "asc"), ("id", "asc")]
SAMPLE_ORDER = [("sampled_at", "desc"), ("created_at", "asc")]


@bp.post("/workers")
@endpoint([PLANT_ADMIN], body=CREATE_SPEC)
def create_worker():
    payload = g.body
    lookup("plants", payload["plant_id"])
    record = {
        "plant_id": payload["plant_id"],
        "full_name": payload["full_name"],
        "job_class": payload["job_class"],
        "hire_date": payload["hire_date"],
        "removal_status": "ACTIVE",
        "exposure_index": 0,
        "exposure_index_variant": "NONE",
        "removal_count": 0,
        "last_sample_at": None,
    }
    db.insert("workers", record)
    return object_response(record, 201)


@bp.get("/workers")
@endpoint(WORKER_READERS, paginated=True)
def list_workers():
    return paginated(apply_filters(db.rows("workers"), WORKER_FILTERS), DEFAULT_ORDER)


@bp.get("/workers/<worker_id>")
@endpoint(WORKER_READERS)
def read_worker(worker_id):
    return object_response(lookup("workers", worker_id))


def _check_sample_discriminator(payload):
    if payload["sample_type"] == "AIR":
        require(payload, "air_lead_ug_per_m3", "for an AIR sample")
        require(payload, "sample_duration_minutes", "for an AIR sample")
        forbid(payload, "blood_lead_ug_per_dl", "for an AIR sample")
    else:
        require(payload, "blood_lead_ug_per_dl", "for a BLOOD sample")
        forbid(payload, "air_lead_ug_per_m3", "for a BLOOD sample")
        forbid(payload, "sample_duration_minutes", "for a BLOOD sample")


@bp.post("/workers/<worker_id>/exposure-samples")
@endpoint([SAFETY_OFFICER], body=SAMPLE_SPEC, schema_check=_check_sample_discriminator)
def create_exposure_sample(worker_id):
    payload = g.body
    require_job_class(JOB_SAFETY)
    worker = lookup("workers", worker_id)
    now = db.now()
    sampled_at = payload["sampled_at"]
    if sampled_at > now or sampled_at < worker["hire_date"]:
        raise ApiError(
            "ERR_EVENT_TIME_OUT_OF_RANGE",
            "sampled_at must not be in the logical future or precede the hire date",
        )
    sample = {
        "worker_id": worker["id"],
        "sample_type": payload["sample_type"],
        "air_lead_ug_per_m3": payload.get("air_lead_ug_per_m3"),
        "sample_duration_minutes": payload.get("sample_duration_minutes"),
        "blood_lead_ug_per_dl": payload.get("blood_lead_ug_per_dl"),
        "sampled_at": sampled_at,
        "resulting_worker_index": None,
        "resulting_variant": None,
        "triggered_removal": False,
    }
    db.insert("exposure_samples", sample, versioned=False)
    if payload["sample_type"] == "AIR":
        index, _ = air_twa_index(worker["id"], now)
        variant = "AIR_TWA_90D"
    else:
        index, _ = blood_peak_index(worker["id"], now)
        variant = "BLOOD_PEAK_180D"
    worker["exposure_index"] = index
    worker["exposure_index_variant"] = variant
    worker["last_sample_at"] = max(
        (s["sampled_at"] for s in samples_of_worker(worker["id"])), default=sampled_at
    )
    triggered = False
    if index >= REMOVAL_THRESHOLD_INDEX and worker["removal_status"] == "ACTIVE":
        worker["removal_status"] = "MEDICAL_REMOVAL"
        worker["removal_count"] = worker.get("removal_count", 0) + 1
        triggered = True
    db.touch(worker)
    sample["resulting_worker_index"] = index
    sample["resulting_variant"] = variant
    sample["triggered_removal"] = triggered
    if triggered:
        plant = db.plants.get(worker["plant_id"])
        if plant is not None:
            refresh_plant(plant)
    return object_response(sample, 201)


@bp.get("/workers/<worker_id>/exposure-samples")
@endpoint([PLANT_ADMIN, SAFETY_OFFICER], paginated=True)
def list_exposure_samples(worker_id):
    worker = lookup("workers", worker_id)
    rows = apply_filters(samples_of_worker(worker["id"]), {"sample_type": "sample_type"})
    return paginated(rows, SAMPLE_ORDER)


@bp.get("/workers/<worker_id>/exposure-index")
@endpoint([PLANT_ADMIN, SAFETY_OFFICER])
def read_exposure_index(worker_id):
    worker = lookup("workers", worker_id)
    now = db.now()
    air_index, air_count = air_twa_index(worker["id"], now)
    blood_index, blood_count = blood_peak_index(worker["id"], now)
    governing = max(air_index, blood_index)
    if air_count == 0 and blood_count == 0:
        variant = "NONE"
    elif air_count == 0:
        variant = "BLOOD_PEAK_180D"
    elif blood_count == 0:
        variant = "AIR_TWA_90D"
    else:
        variant = "AIR_TWA_90D" if air_index >= blood_index else "BLOOD_PEAK_180D"
    return object_response(
        {
            "worker_id": worker["id"],
            "air_twa_90d_index": air_index,
            "blood_peak_180d_index": blood_index,
            "governing_index": governing,
            "governing_variant": variant,
            "removal_eligible": governing >= REMOVAL_THRESHOLD_INDEX,
            "sample_counts": {
                "air": air_count,
                "blood": blood_count,
                "air_90d": air_count,
                "blood_180d": blood_count,
                "air_samples_in_window": air_count,
                "blood_samples_in_window": blood_count,
            },
        }
    )


@bp.post("/workers/<worker_id>/medical-clearance")
@endpoint([SAFETY_OFFICER], body=CLEARANCE_SPEC)
def medical_clearance(worker_id):
    worker = lookup("workers", worker_id)
    if worker.get("removal_status") != "MEDICAL_REMOVAL":
        raise ApiError("ERR_WORKER_NOT_REMOVED", "Worker is not medically removed")
    now = db.now()
    floor_at = now - datetime.timedelta(days=EVENT_WINDOW_DAYS)
    evidence = [
        s
        for s in samples_of_worker(worker["id"])
        if s.get("sample_type") == "BLOOD"
        and s.get("sampled_at") is not None
        and s["sampled_at"] >= floor_at
        and s["blood_lead_ug_per_dl"] < BLL_RETURN_UG_PER_DL
    ]
    if not evidence:
        raise ApiError(
            "ERR_CLEARANCE_EVIDENCE_MISSING",
            "No qualifying BLOOD sample below the return threshold in the last 30 days",
        )
    worker["removal_status"] = "ACTIVE"
    index, _ = blood_peak_index(worker["id"], now)
    worker["exposure_index"] = index
    worker["exposure_index_variant"] = "BLOOD_PEAK_180D"
    db.touch(worker)
    plant = db.plants.get(worker["plant_id"])
    if plant is not None:
        refresh_plant(plant)
    return object_response(worker)
