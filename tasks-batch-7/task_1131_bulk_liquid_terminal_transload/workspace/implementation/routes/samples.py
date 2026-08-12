"""QualitySample endpoints: collect, list, get, record-result, release-retain."""
from flask import Blueprint

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import sample_view
from services import calc, lifecycle
from services.common import touch, get_movement_or_404
from validation import (get_body, req_enum, req_number, sort_and_page,
                        SAMPLE_TYPES, LAB_RESULTS)

bp = Blueprint("samples", __name__)


@bp.post("/movements/<movementId>/samples")
def collect_sample(movementId):
    user_id, _ = require_roles("QualityInspector")
    body = get_body()
    sample_type = req_enum(body, "sample_type", SAMPLE_TYPES)
    movement = get_movement_or_404(movementId)
    if movement["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise err("ERR_INVALID_STATE",
                  "Samples may be collected only while the movement is IN_PROGRESS or COMPLETED")
    now = CLOCK.now()
    sample = {
        "id": new_id(),
        "movement_id": movement["id"],
        "sample_type": sample_type,
        "collected_by_user_id": user_id,
        "lab_result": "PENDING",
        "specific_gravity": None,
        "result_recorded_by_user_id": None,
        "retain_until": calc.retain_deadline(now),
        "retain_status": "RETAINED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.samples[sample["id"]] = sample
    return success_object(sample_view(sample), status=201)


@bp.get("/movements/<movementId>/samples")
def list_samples(movementId):
    current_user()
    get_movement_or_404(movementId)
    rows = [s for s in STORE.samples.values() if s["movement_id"] == movementId]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([sample_view(s) for s in page], total, limit, offset)


def _get_sample_or_404(sample_id):
    sample = STORE.samples.get(sample_id)
    if sample is None:
        raise err("ERR_SAMPLE_NOT_FOUND", "Sample %s not found" % sample_id)
    return sample


@bp.get("/quality-samples/<sampleId>")
def get_sample(sampleId):
    current_user()
    sample = _get_sample_or_404(sampleId)
    return success_object(sample_view(sample))


@bp.post("/quality-samples/<sampleId>/record-result")
def record_result(sampleId):
    user_id, _ = require_roles("QualityInspector")
    body = get_body()
    lab_result = req_enum(body, "lab_result", LAB_RESULTS)
    specific_gravity = req_number(body, "specific_gravity", gt=0)
    sample = _get_sample_or_404(sampleId)
    # Segregation of duties: recorder must differ from collector.
    if user_id == sample["collected_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The sample collector may not record its laboratory result")
    sample["lab_result"] = lab_result
    sample["specific_gravity"] = specific_gravity
    sample["result_recorded_by_user_id"] = user_id
    touch(sample)
    return success_object(sample_view(sample))


@bp.post("/quality-samples/<sampleId>/release-retain")
def release_retain(sampleId):
    require_roles("QualityInspector")
    sample = _get_sample_or_404(sampleId)
    if sample["retain_status"] != "RETAINED":
        raise err("ERR_INVALID_STATE",
                  "Sample %s retain_status is %s; release requires RETAINED"
                  % (sampleId, sample["retain_status"]))
    ct = lifecycle.custody_for_movement(sample["movement_id"])
    if ct is None or ct["status"] != "CERTIFIED":
        raise err("ERR_CUSTODY_NOT_CERTIFIED",
                  "Retain release requires the movement's custody transfer to be CERTIFIED")
    if CLOCK.now() < sample["retain_until"]:
        raise err("ERR_RETAIN_PERIOD_ACTIVE",
                  "Retain release is blocked until retain_until")
    sample["retain_status"] = "RELEASED"
    touch(sample)
    return success_object(sample_view(sample))
