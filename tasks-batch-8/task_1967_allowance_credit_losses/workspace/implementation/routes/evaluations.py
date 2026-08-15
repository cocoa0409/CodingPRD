"""IndividualEvaluation endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ANALYSIS_DOCUMENTATION_REQUIRED,
    ERR_EVALUATION_STALE_VERSION,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import ALL_ROLES, require_roles
from response import success_response
from services import (
    EVAL_METHODS,
    compute_specific_reserve,
    get_or_404,
    public,
    recompute_reviewed_count,
    resync_run_totals,
    touch,
)
from validation import (
    get_body,
    opt_enum,
    opt_int,
    opt_int_list,
    opt_str,
    paginate,
    parse_pagination,
    req_int,
    sorted_by_creation,
)

bp = Blueprint("evaluations", __name__)

_WORKABLE_RUN_STATUSES = ("EXECUTED", "UNDER_REVIEW")


def _parent_run(evaluation):
    return db.runs.get(evaluation["run_id"])


def _require_workable_parent(evaluation):
    run = _parent_run(evaluation)
    if run is None or run["status"] not in _WORKABLE_RUN_STATUSES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "The parent run must be EXECUTED or UNDER_REVIEW for evaluation changes",
        )
    return run


def _check_dcf_requirements(evaluation):
    if evaluation["method"] == "DISCOUNTED_CASH_FLOW":
        flows = evaluation["expected_quarterly_cash_flows_cents"]
        rate = evaluation["discount_rate_bps"]
        if not flows or rate is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "DISCOUNTED_CASH_FLOW requires a non-empty expected_quarterly_cash_flows_cents list and a discount_rate_bps",
            )


@bp.get("/cecl/individual-evaluations")
def list_evaluations():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.evaluations.values())
    run_id = request.args.get("run_id")
    if run_id is not None:
        items = [e for e in items if e["run_id"] == run_id]
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        items = [e for e in items if e["loan_id"] == loan_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([public(e) for e in page], 200, "array", pagination)


@bp.get("/cecl/individual-evaluations/<evaluationId>")
def get_evaluation(evaluationId):
    require_roles(ALL_ROLES)
    evaluation = get_or_404(db.evaluations, evaluationId, "IndividualEvaluation")
    return success_response(public(evaluation), 200)


@bp.patch("/cecl/individual-evaluations/<evaluationId>")
def patch_evaluation(evaluationId):
    require_roles(["CreditAnalyst"])
    evaluation = get_or_404(db.evaluations, evaluationId, "IndividualEvaluation")
    body = get_body()
    expected_version = req_int(body, "expected_evaluation_version")
    method = opt_enum(body, "method", EVAL_METHODS, None)
    collateral = opt_int(body, "collateral_value_cents", None)
    flows = opt_int_list(body, "expected_quarterly_cash_flows_cents", None)
    discount_rate = opt_int(body, "discount_rate_bps", None)
    notes = opt_str(body, "analysis_notes", None)
    if collateral is not None and collateral < 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "collateral_value_cents may not be negative"
        )
    if discount_rate is not None and discount_rate < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "discount_rate_bps may not be negative")
    if flows is not None:
        for cf in flows:
            if cf < 0:
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    400,
                    "expected_quarterly_cash_flows_cents entries may not be negative",
                )
    # Method switch with no usable DCF inputs anywhere -> body-shape error (rung 4)
    if method == "DISCOUNTED_CASH_FLOW":
        merged_flows = flows if flows is not None else evaluation["expected_quarterly_cash_flows_cents"]
        merged_rate = (
            discount_rate if discount_rate is not None else evaluation["discount_rate_bps"]
        )
        if not merged_flows or merged_rate is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "DISCOUNTED_CASH_FLOW requires a non-empty expected_quarterly_cash_flows_cents list and a discount_rate_bps",
            )
    if evaluation["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Evaluations can only be updated while DRAFT or SUBMITTED",
        )
    run = _require_workable_parent(evaluation)
    if expected_version != evaluation["version"]:
        raise ApiError(
            ERR_EVALUATION_STALE_VERSION,
            412,
            "expected_evaluation_version does not equal the evaluation's current version",
        )
    if method is not None:
        evaluation["method"] = method
    if collateral is not None:
        evaluation["collateral_value_cents"] = collateral
    if flows is not None:
        evaluation["expected_quarterly_cash_flows_cents"] = flows
    if discount_rate is not None:
        evaluation["discount_rate_bps"] = discount_rate
    if notes is not None:
        evaluation["analysis_notes"] = notes
    _check_dcf_requirements(evaluation)
    loan = db.loans[evaluation["loan_id"]]
    evaluation["specific_reserve_cents"] = compute_specific_reserve(
        evaluation, loan["amortized_cost_cents"]
    )
    touch(evaluation)
    resync_run_totals(run)
    touch(run)
    return success_response(public(evaluation), 200)


@bp.post("/cecl/individual-evaluations/<evaluationId>/submit")
def submit_evaluation(evaluationId):
    require_roles(["CreditAnalyst"])
    get_body()
    evaluation = get_or_404(db.evaluations, evaluationId, "IndividualEvaluation")
    if evaluation["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a DRAFT evaluation can be submitted",
        )
    run = _require_workable_parent(evaluation)
    if not evaluation["analysis_notes"] or not evaluation["analysis_notes"].strip():
        raise ApiError(
            ERR_ANALYSIS_DOCUMENTATION_REQUIRED,
            422,
            "analysis_notes must be non-empty before submit",
        )
    evaluation["status"] = "SUBMITTED"
    touch(evaluation)
    resync_run_totals(run)
    touch(run)
    return success_response(public(evaluation), 200)


@bp.post("/cecl/individual-evaluations/<evaluationId>/review")
def review_evaluation(evaluationId):
    require_roles(["ChiefCreditOfficer"])
    get_body()
    evaluation = get_or_404(db.evaluations, evaluationId, "IndividualEvaluation")
    if evaluation["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a SUBMITTED evaluation can be reviewed",
        )
    run = _require_workable_parent(evaluation)
    evaluation["status"] = "REVIEWED"
    touch(evaluation)
    recompute_reviewed_count(run)
    resync_run_totals(run)
    touch(run)
    return success_response(public(evaluation), 200)


@bp.post("/cecl/individual-evaluations/<evaluationId>/reopen")
def reopen_evaluation(evaluationId):
    require_roles(["ChiefCreditOfficer"])
    evaluation = get_or_404(db.evaluations, evaluationId, "IndividualEvaluation")
    body = get_body()
    reopen_reason = body.get("reopen_reason")
    if not isinstance(reopen_reason, str) or not reopen_reason.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "reopen_reason must be a non-empty string"
        )
    if evaluation["status"] != "REVIEWED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a REVIEWED evaluation can be reopened",
        )
    run = _require_workable_parent(evaluation)
    evaluation["status"] = "SUBMITTED"
    touch(evaluation)
    recompute_reviewed_count(run)
    touch(run)
    return success_response(public(evaluation), 200)
