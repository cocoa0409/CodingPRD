"""TestRun, TestResultLine, Correction routes (PRD §3.6-3.7)."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_CORRECTION_AMOUNT_INVALID, ERR_FK_INTEGRITY,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
)
from middleware import (
    READ_ROLES, ROLE_COMPLIANCE_ANALYST, ROLE_PLAN_ADMINISTRATOR,
    ROLE_PLATFORM_ADMIN, require_roles,
)
from response import success_list, success_object
from services import correction as correction_svc
from services import engine as engine_svc
from services.common import (
    bump, get_body, get_correction, get_employee, get_plan_year, get_test_run,
    new_entity, opt_filter, page_slice, pagination_params, plan_year_of_employee,
    req_enum, req_int, req_string, opt_string, supersede_terminal_test_runs,
)

bp = Blueprint("testing", __name__)

TEST_SCOPES = {
    "COVERAGE_410B", "ADP_401K", "ACP_401M", "TOP_HEAVY_416",
    "CAFETERIA_125", "DEPENDENT_CARE_129", "FULL_SUITE",
}
RUN_MODES = {"PROVISIONAL", "FINAL"}
CORRECTION_TYPES = {
    "CORRECTIVE_DISTRIBUTION", "QNEC_CONTRIBUTION", "QMAC_REALLOCATION",
    "RECHARACTERIZATION", "PLAN_AMENDMENT_RETRO",
}
TEST_RUN_QUEUE_STATES = {"CENSUS_LOCKED", "TESTING", "RESULTS_REVIEW"}
CORRECTION_PROPOSE_STATES = {"RESULTS_REVIEW", "CORRECTING"}


def test_run_out(run):
    return {
        "id": run["id"], "plan_year_id": run["plan_year_id"],
        "test_scope": run["test_scope"], "run_mode": run["run_mode"],
        "engine_input_hash": run["engine_input_hash"],
        "status": run["status"], "overall_result": run["overall_result"],
        "created_at": run["created_at"], "updated_at": run["updated_at"],
        "version": run["version"],
    }


def test_result_line_out(line):
    return {
        "id": line["id"], "test_run_id": line["test_run_id"],
        "metric": line["metric"], "value_pct": line["value_pct"],
        "threshold_pct": line["threshold_pct"], "outcome": line["outcome"],
        "detail": line["detail"], "created_at": line["created_at"],
        "updated_at": line["updated_at"], "version": line["version"],
    }


def correction_out(c):
    return {
        "id": c["id"], "plan_year_id": c["plan_year_id"],
        "test_run_id": c["test_run_id"],
        "correction_type": c["correction_type"],
        "target_census_employee_id": c["target_census_employee_id"],
        "amount_cents": c["amount_cents"],
        "gap_period_income_cents": c["gap_period_income_cents"],
        "excise_tax_cents": c["excise_tax_cents"],
        "excise_status": c["excise_status"],
        "status": c["status"],
        "deadline_date": c["deadline_date"],
        "executed_at": c["executed_at"],
        "proposer_user_id": c["proposer_user_id"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ---------------------------------------------------------------------------
# Test runs
# ---------------------------------------------------------------------------

@bp.route("/ndt/plan-years/<pyid>/test-runs", methods=["GET"])
def list_test_runs(pyid):
    require_roles(READ_ROLES)
    get_plan_year(pyid)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    test_scope = opt_filter(request.args, "test_scope")
    run_mode = opt_filter(request.args, "run_mode")
    items = [r for r in store.test_runs.values() if r["plan_year_id"] == pyid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if test_scope is not None:
        items = [r for r in items if r["test_scope"] == test_scope]
    if run_mode is not None:
        items = [r for r in items if r["run_mode"] == run_mode]
    page, total = page_slice(items, limit, offset)
    return success_list([test_run_out(r) for r in page], limit, offset, total)


@bp.route("/ndt/plan-years/<pyid>/test-runs", methods=["POST"])
def create_test_run(pyid):
    require_roles({ROLE_COMPLIANCE_ANALYST})
    py = get_plan_year(pyid)
    if py["status"] not in TEST_RUN_QUEUE_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Test runs may be queued only while the plan year is "
                       "CENSUS_LOCKED, TESTING, or RESULTS_REVIEW")
    body = get_body()
    test_scope = req_enum(body, "test_scope", TEST_SCOPES)
    run_mode = req_enum(body, "run_mode", RUN_MODES)
    run = new_entity({
        "plan_year_id": pyid, "test_scope": test_scope, "run_mode": run_mode,
        "engine_input_hash": engine_svc.engine_input_hash(py),
        "status": "QUEUED", "overall_result": "NOT_EVALUATED",
    })
    store.test_runs[run["id"]] = run
    if py["status"] in ("CENSUS_LOCKED", "RESULTS_REVIEW"):
        py["status"] = "TESTING"
    bump(py)
    return success_object(test_run_out(run), status=201)


@bp.route("/ndt/test-runs/<tid>", methods=["GET"])
def fetch_test_run(tid):
    require_roles(READ_ROLES)
    return success_object(test_run_out(get_test_run(tid)))


@bp.route("/ndt/test-runs/<tid>/result-lines", methods=["GET"])
def list_result_lines(tid):
    require_roles(READ_ROLES)
    get_test_run(tid)
    limit, offset = pagination_params()
    metric = opt_filter(request.args, "metric")
    outcome = opt_filter(request.args, "outcome")
    items = [l for l in store.test_result_lines.values() if l["test_run_id"] == tid]
    if metric is not None:
        items = [l for l in items if l["metric"] == metric]
    if outcome is not None:
        items = [l for l in items if l["outcome"] == outcome]
    page, total = page_slice(items, limit, offset)
    return success_list([test_result_line_out(l) for l in page], limit, offset, total)


@bp.route("/ndt/test-runs/<tid>/finalize", methods=["POST"])
def finalize_test_run(tid):
    require_roles({ROLE_COMPLIANCE_ANALYST})
    run = get_test_run(tid)
    if run["status"] not in ("PASSED", "FAILED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a completed (PASSED or FAILED) run can be finalized")
    if run["run_mode"] != "FINAL":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a FINAL run can be finalized")
    py = store.plan_years[run["plan_year_id"]]
    if py["status"] == "TESTING":
        py["status"] = "RESULTS_REVIEW"
        bump(py)
    else:
        bump(py)
    bump(run)
    return success_object(test_run_out(run))


@bp.route("/ndt/test-runs/<tid>/void", methods=["POST"])
def void_test_run(tid):
    require_roles({ROLE_COMPLIANCE_ANALYST})
    run = get_test_run(tid)
    if run["status"] != "QUEUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a QUEUED run can be voided")
    run["status"] = "VOID"
    bump(run)
    return success_object(test_run_out(run))


@bp.route("/ndt/test-runs/<tid>/execute-synchronously", methods=["POST"])
def execute_test_run_synchronously(tid):
    require_roles({ROLE_PLATFORM_ADMIN, ROLE_COMPLIANCE_ANALYST})
    run = get_test_run(tid)
    if run["status"] != "QUEUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a QUEUED run can be executed")
    for sibling in store.test_runs.values():
        if (sibling["plan_year_id"] == run["plan_year_id"]
                and sibling["id"] != run["id"]
                and sibling["status"] == "QUEUED"
                and (sibling["created_at"], sibling["id"]) < (run["created_at"], run["id"])):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "An earlier queued run for this plan year must execute first")
    engine_svc.execute_run(run)
    return success_object(test_run_out(run))


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------

@bp.route("/ndt/plan-years/<pyid>/corrections", methods=["GET"])
def list_corrections_of_year(pyid):
    require_roles(READ_ROLES)
    get_plan_year(pyid)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    correction_type = opt_filter(request.args, "correction_type")
    items = [c for c in store.corrections.values() if c["plan_year_id"] == pyid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if correction_type is not None:
        items = [c for c in items if c["correction_type"] == correction_type]
    page, total = page_slice(items, limit, offset)
    return success_list([correction_out(c) for c in page], limit, offset, total)


@bp.route("/ndt/plan-years/<pyid>/corrections", methods=["POST"])
def propose_correction(pyid):
    user_id = require_roles({ROLE_COMPLIANCE_ANALYST})
    py = get_plan_year(pyid)
    if py["status"] not in CORRECTION_PROPOSE_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Corrections may be proposed only while the plan year is "
                       "RESULTS_REVIEW or CORRECTING")
    body = get_body()
    test_run_id = req_string(body, "test_run_id")
    correction_type = req_enum(body, "correction_type", CORRECTION_TYPES)
    target_census_employee_id = opt_string(body, "target_census_employee_id")
    amount_cents = req_int(body, "amount_cents")

    run = store.test_runs.get(test_run_id)
    if run is None or run["plan_year_id"] != pyid:
        raise ApiError(ERR_FK_INTEGRITY, 422,
                       "test_run_id must reference a TestRun of this plan year")
    if target_census_employee_id is not None:
        target = store.census_employees.get(target_census_employee_id)
        if target is None or target["plan_year_id"] != pyid:
            raise ApiError(ERR_FK_INTEGRITY, 422,
                           "target_census_employee_id must reference a "
                           "CensusEmployee of this plan year")
    elif correction_type != "QNEC_CONTRIBUTION":
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "target_census_employee_id is required except for a "
                       "plan-wide QNEC")

    has_failed_final = any(
        r["plan_year_id"] == pyid and r["run_mode"] == "FINAL"
        and r["overall_result"] == "FAIL"
        and r["status"] in ("FAILED",)
        for r in store.test_runs.values())
    if not has_failed_final:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "At least one FINAL TestRun with overall_result FAIL must "
                       "exist for this plan year")

    if amount_cents <= 0:
        raise ApiError(ERR_CORRECTION_AMOUNT_INVALID, 422,
                       "Correction amount_cents must be strictly positive")
    if correction_type == "CORRECTIVE_DISTRIBUTION":
        distributable = correction_svc.distributable_balance_cents(
            target_census_employee_id)
        if amount_cents > distributable:
            raise ApiError(ERR_CORRECTION_AMOUNT_INVALID, 422,
                           "Correction amount exceeds the target employee's "
                           "distributable POSTED elective deferral balance")

    correction = new_entity({
        "plan_year_id": pyid, "test_run_id": test_run_id,
        "correction_type": correction_type,
        "target_census_employee_id": target_census_employee_id,
        "amount_cents": amount_cents,
        "gap_period_income_cents": 0,
        "excise_tax_cents": 0,
        "excise_status": "NOT_ASSESSED",
        "status": "PROPOSED",
        "deadline_date": correction_svc.compute_deadline_date(py).isoformat(),
        "executed_at": None,
        "proposer_user_id": user_id,
    })
    store.corrections[correction["id"]] = correction
    if py["status"] == "RESULTS_REVIEW":
        py["status"] = "CORRECTING"
    bump(py)
    return success_object(correction_out(correction), status=201)


@bp.route("/ndt/corrections", methods=["GET"])
def list_corrections():
    require_roles(READ_ROLES)
    limit, offset = pagination_params()
    plan_year_id = opt_filter(request.args, "plan_year_id")
    test_run_id = opt_filter(request.args, "test_run_id")
    target_census_employee_id = opt_filter(request.args, "target_census_employee_id")
    status = opt_filter(request.args, "status")
    correction_type = opt_filter(request.args, "correction_type")
    excise_status = opt_filter(request.args, "excise_status")
    items = list(store.corrections.values())
    if plan_year_id is not None:
        items = [c for c in items if c["plan_year_id"] == plan_year_id]
    if test_run_id is not None:
        items = [c for c in items if c["test_run_id"] == test_run_id]
    if target_census_employee_id is not None:
        items = [c for c in items
                 if c["target_census_employee_id"] == target_census_employee_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if correction_type is not None:
        items = [c for c in items if c["correction_type"] == correction_type]
    if excise_status is not None:
        items = [c for c in items if c["excise_status"] == excise_status]
    page, total = page_slice(items, limit, offset)
    return success_list([correction_out(c) for c in page], limit, offset, total)


@bp.route("/ndt/corrections/<cid>", methods=["GET"])
def fetch_correction(cid):
    require_roles(READ_ROLES)
    return success_object(correction_out(get_correction(cid)))


@bp.route("/ndt/corrections/<cid>/approve", methods=["POST"])
def approve_correction(cid):
    user_id = require_roles({ROLE_PLAN_ADMINISTRATOR})
    correction = get_correction(cid)
    if correction["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PROPOSED correction can be approved")
    py = store.plan_years[correction["plan_year_id"]]
    if py["status"] != "CORRECTING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Correction approval requires the plan year to be CORRECTING")
    if user_id == correction.get("proposer_user_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The approver must differ from the proposing analyst")
    body = get_body() if request.data else {}
    expected = body.get("expected_correction_version") if isinstance(body, dict) else None
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "expected_correction_version must be an integer")
        if expected != correction["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           "Correction version has advanced since the caller's view")
    correction["status"] = "APPROVED"
    bump(correction)
    return success_object(correction_out(correction))


@bp.route("/ndt/corrections/<cid>/execute", methods=["POST"])
def execute_correction(cid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    correction = get_correction(cid)
    if correction["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an APPROVED correction can be executed")
    py = store.plan_years[correction["plan_year_id"]]
    if correction["amount_cents"] <= 0:
        raise ApiError(ERR_CORRECTION_AMOUNT_INVALID, 422,
                       "Correction amount_cents must be strictly positive")
    if correction["correction_type"] == "CORRECTIVE_DISTRIBUTION":
        distributable = correction_svc.distributable_balance_cents(
            correction["target_census_employee_id"])
        if correction["amount_cents"] > distributable:
            raise ApiError(ERR_CORRECTION_AMOUNT_INVALID, 422,
                           "Correction amount exceeds the target employee's "
                           "distributable POSTED elective deferral balance")
    # §3.7: execution supersedes every PASSED/FAILED run created later than the
    # failed run this correction remedies — those runs measured the balances the
    # correction is now changing. The remedied run itself stays as the FAILED
    # record the correction references.
    remedied = store.test_runs.get(correction["test_run_id"])
    marker = remedied["created_at"] if remedied is not None else correction["created_at"]
    correction_svc.apply_execute_side_effects(correction)
    supersede_terminal_test_runs(py["id"], later_than_created_at=marker)
    bump(py)
    return success_object(correction_out(correction))


@bp.route("/ndt/corrections/<cid>/void", methods=["POST"])
def void_correction(cid):
    user_id = require_roles({ROLE_PLAN_ADMINISTRATOR, ROLE_COMPLIANCE_ANALYST})
    role = request.headers.get("X-User-Role", "").strip()
    correction = get_correction(cid)
    if correction["status"] == "PROPOSED":
        if role != ROLE_COMPLIANCE_ANALYST:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "A PROPOSED correction is voided by the proposing analyst")
    elif correction["status"] == "APPROVED":
        if role != ROLE_PLAN_ADMINISTRATOR:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "An APPROVED correction is voided by a PlanAdministrator")
        py = store.plan_years[correction["plan_year_id"]]
        if py["status"] != "CORRECTING":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Voiding an APPROVED correction requires the plan year "
                           "to be CORRECTING")
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PROPOSED or APPROVED correction can be voided")
    correction["status"] = "VOIDED"
    bump(correction)
    return success_object(correction_out(correction))
