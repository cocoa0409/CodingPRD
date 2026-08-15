"""ModelRun endpoints: creation, execution, review workflow, finalization."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ADJUSTMENTS_PENDING,
    ERR_EVALUATIONS_OUTSTANDING,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MODEL_NOT_ACTIVE,
    ERR_PERIOD_NOT_FORWARD,
    ERR_SCENARIO_NOT_ACTIVE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WEIGHT_SUM_INVALID,
)
from middleware import ALL_ROLES, require_roles
from response import success_response
from services import (
    BASE_RATE_BY_BAND,
    blended_multiplier,
    compute_qualitative_adjustment,
    compute_quantitative_reserve,
    compute_specific_reserve,
    effective_multiplier,
    get_or_404,
    public,
    recompute_reviewed_count,
    resync_run_totals,
    round_half_up_int,
    scenario_mult_bps,
    stamp_new,
    touch,
)
from validation import (
    get_body,
    opt_int,
    paginate,
    parse_pagination,
    quarter_index,
    req_int,
    req_list,
    req_period,
    req_str,
    sorted_by_creation,
)

bp = Blueprint("model_runs", __name__)


def serialize_run(run):
    return public(run)


@bp.post("/cecl/model-runs")
def create_model_run():
    require_roles(["CreditAnalyst"])
    body = get_body()
    as_of_period = req_period(body, "as_of_period")
    loss_model_id = req_str(body, "loss_model_id")
    weights_raw = req_list(body, "scenario_weights")
    for entry in weights_raw:
        if not isinstance(entry, dict):
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "scenario_weights entries must be objects with scenario_id and weight_bps",
            )
        sid = entry.get("scenario_id")
        w = entry.get("weight_bps")
        if not isinstance(sid, str) or not sid:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "scenario_weights entries must carry a string scenario_id",
            )
        if isinstance(w, bool) or not isinstance(w, int):
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "scenario_weights entries must carry an integer weight_bps",
            )
    model = db.loss_models.get(loss_model_id)
    if model is None:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "loss_model_id does not identify an existing model"
        )
    # Period-forward discipline (rung 8)
    new_idx = quarter_index(as_of_period)
    for run in db.runs.values():
        if run["status"] == "FINALIZED" and new_idx <= quarter_index(run["as_of_period"]):
            raise ApiError(
                ERR_PERIOD_NOT_FORWARD,
                409,
                "as_of_period must be strictly later than every FINALIZED run's as_of_period",
            )
    # Referenced configuration usability (rung 9)
    if model["status"] != "ACTIVE":
        raise ApiError(ERR_MODEL_NOT_ACTIVE, 409, "Referenced LossModel is not ACTIVE")
    for entry in weights_raw:
        scenario = db.scenarios.get(entry["scenario_id"])
        if scenario is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "scenario_weights references an unknown scenario_id",
            )
        if scenario["status"] != "ACTIVE":
            raise ApiError(
                ERR_SCENARIO_NOT_ACTIVE,
                409,
                "Every scenario referenced in scenario_weights must be ACTIVE",
            )
    # Structural rules (rung 10): weight positivity and sum
    total_weight = 0
    for entry in weights_raw:
        if entry["weight_bps"] <= 0:
            raise ApiError(
                ERR_WEIGHT_SUM_INVALID,
                422,
                "scenario weight_bps values must be positive integers",
            )
        total_weight += entry["weight_bps"]
    if total_weight != 10000:
        raise ApiError(
            ERR_WEIGHT_SUM_INVALID,
            422,
            "scenario_weights weight_bps values must sum to exactly 10000",
        )
    scenario_weights = [
        {"scenario_id": e["scenario_id"], "weight_bps": e["weight_bps"]}
        for e in weights_raw
    ]
    run = stamp_new(
        {
            "as_of_period": as_of_period,
            "loss_model_id": loss_model_id,
            "scenario_weights": scenario_weights,
            "status": "DRAFT",
            "executed_by_user_id": None,
            "approved_by_user_id": None,
            "model_version_label": None,
            "needs_segmentation_review": False,
            "individual_evaluation_count": 0,
            "reviewed_evaluation_count": 0,
            "total_exposure_cents": 0,
            "quantitative_reserve_cents": 0,
            "qualitative_adjustment_cents": 0,
            "individual_reserve_cents": 0,
            "management_adjustment_cents": 0,
            "total_allowance_cents": 0,
            "segments_breakdown": [],
            "rework_notes": "",
        }
    )
    db.runs[run["id"]] = run
    return success_response(serialize_run(run), 201)


@bp.get("/cecl/model-runs")
def list_model_runs():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.runs.values())
    loss_model_id = request.args.get("loss_model_id")
    if loss_model_id is not None:
        items = [r for r in items if r["loss_model_id"] == loss_model_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    as_of_period = request.args.get("as_of_period")
    if as_of_period is not None:
        items = [r for r in items if r["as_of_period"] == as_of_period]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([serialize_run(r) for r in page], 200, "array", pagination)


@bp.get("/cecl/model-runs/<runId>")
def get_model_run(runId):
    require_roles(ALL_ROLES)
    run = get_or_404(db.runs, runId, "ModelRun")
    return success_response(serialize_run(run), 200)


@bp.post("/cecl/model-runs/<runId>/execute")
def execute_model_run(runId):
    user_id, _ = require_roles(["CreditAnalyst"])
    get_body()
    run = get_or_404(db.runs, runId, "ModelRun")
    if run["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a DRAFT run can be executed",
        )
    model = db.loss_models[run["loss_model_id"]]
    if model["status"] != "ACTIVE":
        raise ApiError(
            ERR_MODEL_NOT_ACTIVE,
            409,
            "Referenced LossModel must be ACTIVE at execute",
        )
    M = blended_multiplier(run["scenario_weights"])
    E = effective_multiplier(model, M)
    # Snapshot multiplier figures for the breakdown (integers, half-up)
    if len(run["scenario_weights"]) == 1:
        scenario_mult_int = scenario_mult_bps(
            db.scenarios[run["scenario_weights"][0]["scenario_id"]]
        )
    else:
        scenario_mult_int = round_half_up_int(M * Decimal(10000))
    effective_mult_int = round_half_up_int(E * Decimal(10000))

    segments_breakdown = []
    quant_total = 0
    qual_total = 0
    collective_exposure_total = 0
    individual_exposure_total = 0
    evaluations_created = 0

    for segment in db.segments.values():
        collective_exposure = 0
        segment_individual_exposure = 0
        for loan in db.loans.values():
            if loan["segment_id"] != segment["id"] or loan["status"] != "ACTIVE":
                continue
            if loan["individually_evaluated"]:
                segment_individual_exposure += loan["amortized_cost_cents"]
            else:
                collective_exposure += loan["amortized_cost_cents"]
        lifetime_rate, quant_reserve = compute_quantitative_reserve(
            model, segment, collective_exposure, M
        )
        q_bps, q_cents = compute_qualitative_adjustment(
            segment, run["as_of_period"], collective_exposure, quant_reserve
        )
        segments_breakdown.append(
            {
                "segment_id": segment["id"],
                "exposure_cents": collective_exposure,
                "base_loss_rate_bps": BASE_RATE_BY_BAND[segment["risk_rating_band"]],
                "scenario_mult_bps": scenario_mult_int,
                "effective_mult_bps": effective_mult_int,
                "lifetime_loss_rate_bps": lifetime_rate,
                "qualitative_bps": q_bps,
                "quantitative_reserve_cents": quant_reserve,
                "qualitative_adjustment_cents": q_cents,
                "segment_allowance_cents": quant_reserve + q_cents,
            }
        )
        quant_total += quant_reserve
        qual_total += q_cents
        collective_exposure_total += collective_exposure
        individual_exposure_total += segment_individual_exposure

    # Create one DRAFT IndividualEvaluation per individually evaluated ACTIVE loan
    for loan in sorted_by_creation(
        [
            l
            for l in db.loans.values()
            if l["status"] == "ACTIVE" and l["individually_evaluated"]
        ]
    ):
        evaluation = stamp_new(
            {
                "run_id": run["id"],
                "loan_id": loan["id"],
                "method": "COLLATERAL_FAIR_VALUE",
                "collateral_value_cents": loan["collateral_value_cents"],
                "expected_quarterly_cash_flows_cents": [],
                "discount_rate_bps": None,
                "analysis_notes": "",
                "status": "DRAFT",
            }
        )
        evaluation["specific_reserve_cents"] = compute_specific_reserve(
            evaluation, loan["amortized_cost_cents"]
        )
        db.evaluations[evaluation["id"]] = evaluation
        evaluations_created += 1

    run["segments_breakdown"] = segments_breakdown
    run["quantitative_reserve_cents"] = quant_total
    run["qualitative_adjustment_cents"] = qual_total
    run["individual_evaluation_count"] = evaluations_created
    run["model_version_label"] = model["version_label"]
    run["executed_by_user_id"] = user_id
    run["status"] = "EXECUTED"
    run["total_exposure_cents"] = collective_exposure_total + individual_exposure_total
    resync_run_totals(run)
    recompute_reviewed_count(run)
    touch(run)
    return success_response(serialize_run(run), 200)


@bp.post("/cecl/model-runs/<runId>/submit_for_review")
def submit_run_for_review(runId):
    require_roles(["CreditAnalyst"])
    get_body()
    run = get_or_404(db.runs, runId, "ModelRun")
    if run["status"] != "EXECUTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an EXECUTED run can be submitted for review",
        )
    for ev in db.evaluations.values():
        if ev["run_id"] == run["id"] and ev["status"] != "REVIEWED":
            raise ApiError(
                ERR_EVALUATIONS_OUTSTANDING,
                409,
                "Every individual evaluation of the run must be REVIEWED",
            )
    run["status"] = "UNDER_REVIEW"
    touch(run)
    return success_response(serialize_run(run), 200)


@bp.post("/cecl/model-runs/<runId>/approve")
def approve_model_run(runId):
    user_id, _ = require_roles(["ChiefCreditOfficer"])
    get_body()
    run = get_or_404(db.runs, runId, "ModelRun")
    if run["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an UNDER_REVIEW run can be approved",
        )
    if run["executed_by_user_id"] is not None and user_id == run["executed_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            409,
            "The approver must differ from the operator who executed the run",
        )
    run["approved_by_user_id"] = user_id
    run["status"] = "APPROVED"
    touch(run)
    return success_response(serialize_run(run), 200)


@bp.post("/cecl/model-runs/<runId>/request_rework")
def request_rework(runId):
    require_roles(["ChiefCreditOfficer"])
    run = get_or_404(db.runs, runId, "ModelRun")
    body = get_body()
    rework_notes = req_str(body, "rework_notes")
    if run["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an UNDER_REVIEW run can be returned for rework",
        )
    run["rework_notes"] = rework_notes
    run["status"] = "EXECUTED"
    touch(run)
    return success_response(serialize_run(run), 200)


@bp.post("/cecl/model-runs/<runId>/finalize")
def finalize_model_run(runId):
    require_roles(["ChiefCreditOfficer"])
    run = get_or_404(db.runs, runId, "ModelRun")
    body = get_body()
    charge_offs = req_int(body, "period_charge_offs_cents")
    recoveries = req_int(body, "period_recoveries_cents")
    if charge_offs < 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "period_charge_offs_cents must be >= 0"
        )
    if recoveries < 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "period_recoveries_cents must be >= 0"
        )
    if run["status"] != "APPROVED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an APPROVED run can be finalized",
        )
    for adj in db.adjustments.values():
        if adj["run_id"] == run["id"] and adj["status"] == "PENDING":
            raise ApiError(
                ERR_ADJUSTMENTS_PENDING,
                409,
                "No adjustment of the run may remain PENDING at finalize",
            )
    this_idx = quarter_index(run["as_of_period"])
    prior = [
        r
        for r in db.runs.values()
        if r["status"] == "FINALIZED" and quarter_index(r["as_of_period"]) < this_idx
    ]
    if prior:
        prior.sort(key=lambda r: quarter_index(r["as_of_period"]), reverse=True)
        beginning = prior[0]["total_allowance_cents"]
    else:
        beginning = 0
    ending = run["total_allowance_cents"]
    provision = ending - beginning + charge_offs - recoveries
    report = stamp_new(
        {
            "run_id": run["id"],
            "beginning_allowance_cents": beginning,
            "ending_allowance_cents": ending,
            "period_charge_offs_cents": charge_offs,
            "period_recoveries_cents": recoveries,
            "provision_cents": provision,
            "status": "PREPARED",
            "audit_reference": "",
            "revision_notes": "",
        }
    )
    db.reports[report["id"]] = report
    run["status"] = "FINALIZED"
    touch(run)
    return success_response(serialize_run(run), 200)


@bp.get("/cecl/model-runs/<runId>/allowance-summary")
def allowance_summary(runId):
    require_roles(ALL_ROLES)
    run = get_or_404(db.runs, runId, "ModelRun")
    summary = {
        "as_of_period": run["as_of_period"],
        "total_exposure_cents": run["total_exposure_cents"],
        "quantitative_reserve_cents": run["quantitative_reserve_cents"],
        "qualitative_adjustment_cents": run["qualitative_adjustment_cents"],
        "individual_reserve_cents": run["individual_reserve_cents"],
        "management_adjustment_cents": run["management_adjustment_cents"],
        "total_allowance_cents": run["total_allowance_cents"],
        "segments_breakdown": run["segments_breakdown"],
    }
    return success_response(summary, 200)
