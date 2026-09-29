"""Single-file review of a drawn sample (PRD §3.5)."""

from flask import Blueprint

import validation as v
from errors import ApiError
from middleware import ROLE_EXAMINER_IN_CHARGE, authorize
from response import success
from routes.data_calls import parse_review_fields
from routes.examinations import EXAM_RECORD_READ_ROLES
from services import derive, serialize, transitions
from services.guards import ensure_exam_subject, ensure_exam_writable, get_sample

bp = Blueprint("file_samples", __name__)


@bp.get("/file-samples/<sample_id>")
@authorize(*EXAM_RECORD_READ_ROLES)
def read_file_sample(sample_id):
    sample = get_sample(sample_id)
    ensure_exam_subject(derive.exam_of_sample(sample))
    return success(serialize.file_sample(sample))


@bp.post("/file-samples/<sample_id>/review")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def review_file_sample(sample_id):
    sample = get_sample(sample_id)
    call = derive.call_of_sample(sample)
    area = derive.area_of_call(call) if call is not None else None
    exam = derive.exam_of_sample(sample)
    payload = v.body()
    severity, underpaid, days_to_pay = parse_review_fields(payload)

    ensure_exam_writable(exam)
    if sample["review_status"] != "UNREVIEWED":
        raise ApiError(
            "ERR_SAMPLE_ALREADY_REVIEWED",
            "The sampled file has already been reviewed as %s." % sample["review_status"],
        )

    transitions.apply_sample_review(sample, severity, underpaid, days_to_pay)
    if area is not None:
        transitions.area_after_review(area)
    return success(serialize.file_sample(sample))
