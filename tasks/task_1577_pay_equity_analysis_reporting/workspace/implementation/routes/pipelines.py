"""PipelineAnalysis endpoints (PRD §3.6)."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_PIPELINE_RECORD,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import compute_pipeline_analytics
from services.core import new_record
from util import parse_date
from validate import get_body, req_enum, req_date, require_fk

bp = Blueprint("pipelines", __name__)

STAGES = {"APPLICATION", "SCREEN", "INTERVIEW", "OFFER", "HIRE", "PROMOTION"}


def _validate_records(body):
    records = body.get("records")
    if not isinstance(records, list) or len(records) == 0:
        raise_error(ERR_INVALID_PIPELINE_RECORD, "records must be a non-empty array")
    for rec in records:
        if not isinstance(rec, dict):
            raise_error(ERR_INVALID_PIPELINE_RECORD, "each record must be an object")
        label = rec.get("class_label")
        if label is None or not isinstance(label, str) or label.strip() == "":
            raise_error(ERR_INVALID_PIPELINE_RECORD, "record class_label must be a string")
        count_in = rec.get("count_in")
        count_passed = rec.get("count_passed")
        for name, v in (("count_in", count_in), ("count_passed", count_passed)):
            if v is None or isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise_error(ERR_INVALID_PIPELINE_RECORD,
                            f"record {name} must be an integer >= 0")
        if count_passed > count_in:
            raise_error(ERR_INVALID_PIPELINE_RECORD,
                        "record count_passed must be <= count_in")
    return records


@bp.post("/pipeline-analyses")
def create_pipeline():
    authorized(["CompAnalyst"])
    body = get_body()
    study_id = body.get("study_id")
    if study_id is None or not isinstance(study_id, str) or study_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: study_id")
    # Priority 3: body FK existence
    require_fk("pay_equity_studies", study_id, "study_id")
    # Priority 3.7: shape
    stage = req_enum(body, "stage", STAGES)
    start = req_date(body, "cohort_period_start")
    end = req_date(body, "cohort_period_end")
    if parse_date(end) < parse_date(start):
        raise_error(ERR_INVALID_REQUEST,
                    "cohort_period_end must be >= cohort_period_start")
    records = _validate_records(body)

    analytics = compute_pipeline_analytics(records)
    rec = new_record("pipeline_analyses", {
        "study_id": study_id,
        "stage": stage,
        "cohort_period_start": start,
        "cohort_period_end": end,
        "records": records,
        "pass_rates": analytics["pass_rates"],
        "adverse_impact_ratio": analytics["adverse_impact_ratio"],
        "adverse_impact_flag": analytics["adverse_impact_flag"],
        "highest_rate_class": analytics["highest_rate_class"],
    })
    return success_object(public(rec), status=201)


@bp.get("/pipeline-analyses")
def list_pipelines():
    return list_response("pipeline_analyses", {
        "study_id": request.args.get("study_id"),
        "stage": request.args.get("stage"),
    })


@bp.get("/pipeline-analyses/<rid>")
def get_pipeline(rid):
    return get_one("pipeline_analyses", rid)
