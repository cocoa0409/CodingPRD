"""Test evaluations: scheduling exclusive windows and recording results."""
from flask import Blueprint

import clock
import constants
import db
import errors
import response
import validators as v
from errors import ApiError
from middleware import authorize
from services import calc, guards, queries

bp = Blueprint("evaluations", __name__)


# --- 26. POST /test-evaluations ----------------------------------------
@bp.post("/test-evaluations")
@authorize(constants.SECURITY_REVIEWER, constants.GOVERNANCE_OFFICER)
def schedule_evaluation():
    body = v.get_body()
    use_case = guards.resolve_use_case_fk(body)                      # step 7
    binding = guards.resolve_binding_fk(body)
    use_case_id = v.as_str(body, "use_case_id", required=True)        # step 8
    model_binding_id = v.as_str(body, "model_binding_id", required=True)
    eval_type = v.as_enum(body, "eval_type", constants.EVAL_TYPES, required=True)
    window_start_at = v.as_datetime(body, "window_start_at", required=True)
    window_end_at = v.as_datetime(body, "window_end_at", required=True)
    if window_end_at <= window_start_at:
        raise errors.bad_request("window_end_at must be strictly after window_start_at")
    guards.check_not_terminal(use_case)                              # step 10

    # step 36: half-open exclusivity across every binding of the same asset
    asset_id = binding["model_asset_id"]
    sibling_binding_ids = {
        b["id"] for b in queries.bindings_of_asset(asset_id)
    }
    for existing in db.all_of(db.test_evaluations):
        if existing["model_binding_id"] not in sibling_binding_ids:
            continue
        if existing["status"] not in constants.EVAL_WINDOW_BLOCKING_STATUSES:
            continue
        if (
            window_start_at < existing["window_end_at"]
            and existing["window_start_at"] < window_end_at
        ):
            raise ApiError(
                errors.ERR_EVALUATION_WINDOW_CONFLICT,
                "the requested window overlaps evaluation %s on the same asset"
                % existing["id"],
            )

    metric_name, threshold, required_sample_size = calc.evaluation_profile(
        eval_type, use_case["risk_tier"]
    )
    record = {
        "use_case_id": use_case_id,
        "model_binding_id": model_binding_id,
        "eval_type": eval_type,
        "status": "PLANNED",
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "worst_group_parity_ratio": None,
        "adversarial_pass_rate": None,
        "grounded_accuracy": None,
        "sample_size": None,
        "evidence_uri": None,
        "required_metric_name": metric_name,
        "required_metric_threshold": threshold,
        "required_sample_size": required_sample_size,
        "observed_metric_value": None,
        "completed_at": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    db.insert(db.test_evaluations, record)
    return response.object_response(record, 201)


# --- 27. GET /test-evaluations ----------------------------------------
@bp.get("/test-evaluations")
@authorize(*constants.ALL_ROLES)
def list_evaluations():
    use_case_id = v.query_str("use_case_id")
    model_binding_id = v.query_str("model_binding_id")
    eval_type = v.query_str("eval_type")
    status = v.query_str("status")
    limit, offset = v.pagination_params()
    records = db.all_of(db.test_evaluations)
    if use_case_id is not None:
        records = [r for r in records if r["use_case_id"] == use_case_id]
    if model_binding_id is not None:
        records = [r for r in records if r["model_binding_id"] == model_binding_id]
    if eval_type is not None:
        records = [r for r in records if r["eval_type"] == eval_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 28. GET /test-evaluations/{id} -----------------------------------
@bp.get("/test-evaluations/<evaluation_id>")
@authorize(*constants.ALL_ROLES)
def read_evaluation(evaluation_id):
    return response.object_response(
        guards.get_record(db.test_evaluations, evaluation_id, "test evaluation")
    )


# --- 29. POST /test-evaluations/{id}/complete ------------------------
@bp.post("/test-evaluations/<evaluation_id>/complete")
@authorize(constants.SECURITY_REVIEWER, constants.GOVERNANCE_OFFICER)
def complete_evaluation(evaluation_id):
    evaluation = guards.get_record(                                  # step 6
        db.test_evaluations, evaluation_id, "test evaluation"
    )
    body = v.get_body()                                              # step 8
    sample_size = v.as_int(body, "sample_size", required=True, minimum=0)
    evidence_uri = v.as_str(body, "evidence_uri")
    metrics = {}
    for field in constants.METRIC_FIELDS:
        metrics[field] = v.as_number(body, field)
    required_metric = evaluation["required_metric_name"]
    if metrics.get(required_metric) is None:
        raise errors.bad_request(
            "%s is required to complete this evaluation" % required_metric
        )
    use_case = db.use_cases.get(evaluation["use_case_id"])
    guards.check_not_terminal(use_case)                              # step 10
    if evaluation["status"] != "PLANNED":                             # step 16
        raise ApiError(
            errors.ERR_EVALUATION_NOT_PLANNED,
            "evaluation %s is %s and cannot be completed"
            % (evaluation_id, evaluation["status"]),
        )

    for field, value in metrics.items():
        if value is not None:
            evaluation[field] = value
    observed = metrics[required_metric]
    evaluation["observed_metric_value"] = observed
    evaluation["sample_size"] = sample_size
    if evidence_uri is not None:
        evaluation["evidence_uri"] = evidence_uri
    evaluation["completed_at"] = clock.now()
    passed = calc.evaluation_passed(
        observed,
        evaluation["required_metric_threshold"],
        sample_size,
        evaluation["required_sample_size"],
    )
    evaluation["status"] = "PASSED" if passed else "FAILED"
    db.touch(evaluation)

    if use_case is not None:
        if evaluation["eval_type"] == "BIAS":
            use_case["safety_flag"] = not passed
        if not passed and use_case["status"] in ("UNDER_REVIEW", "READY_FOR_APPROVAL"):
            use_case["status"] = "CHANGES_REQUESTED"
    return response.object_response(evaluation)
