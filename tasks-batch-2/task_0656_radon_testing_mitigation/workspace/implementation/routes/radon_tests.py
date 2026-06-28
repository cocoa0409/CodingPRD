"""RadonTest endpoints: place, retrieve, record-result, void (PRD §3.2, §3.3)."""

from flask import Blueprint

from db import store, format_iso8601_millis
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body, parse_pagination
from response import object_response, array_response
from services import validate
from services import calc
from services.domain import (
    _common_create_fields,
    public,
    touch,
    now_clock,
    recompute_property_derived,
)
from services.listing import paginate
from services.jobs_cascade import clear_job_from_retest, job_to_rework_from_retest

bp = Blueprint("radon_tests", __name__)

TEST_KINDS = {"SHORT_TERM_48HR", "CONTINUOUS_MONITOR"}
PURPOSES = {"INITIAL", "POST_MITIGATION", "RECURRING"}

GET_ROLES = {
    "PlatformAdmin",
    "Inspector",
    "MitigationDesigner",
    "ClientContact",
    "ComplianceOfficer",
}


@bp.route("/radon-tests", methods=["POST"])
def place_test():
    _, role = get_user_context()
    require_role(role, {"Inspector"})
    body = get_json_body()

    # --- existence of body FKs (priority 4) comes before state/business checks ---
    property_id = validate.require_string(body, "property_id")
    inspector_id = validate.require_string(body, "inspector_id")
    test_kind = validate.require_enum(body, "test_kind", TEST_KINDS)
    purpose = validate.optional_enum(body, "purpose", PURPOSES, "INITIAL")
    mitigation_job_id = body.get("mitigation_job_id")
    placement_window_hours = validate.optional_int(body, "placement_window_hours", 48, minimum=48)
    warmup_hours_dropped = validate.optional_int(body, "warmup_hours_dropped", 4, minimum=0)

    prop = store.properties.get(property_id)
    if prop is None:
        raise ApiError(errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "property_id not found.")
    inspector = store.inspectors.get(inspector_id)
    if inspector is None:
        raise ApiError(errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "inspector_id not found.")

    job = None
    if mitigation_job_id is not None:
        job = store.mitigation_jobs.get(mitigation_job_id)
        if job is None:
            raise ApiError(
                errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "mitigation_job_id not found."
            )

    # --- business referential: POST_MITIGATION linkage (priority 10) ---
    if purpose == "POST_MITIGATION":
        if mitigation_job_id is None:
            raise ApiError(
                errors.ERR_RETEST_NOT_ALLOWED,
                409,
                "POST_MITIGATION test requires a mitigation_job_id.",
            )
        if job["status"] != "INSTALLED":
            raise ApiError(
                errors.ERR_RETEST_NOT_ALLOWED,
                409,
                "POST_MITIGATION test requires an INSTALLED job.",
            )
    else:
        # INITIAL / RECURRING must omit mitigation_job_id.
        if mitigation_job_id is not None:
            raise ApiError(
                errors.ERR_RETEST_NOT_ALLOWED,
                409,
                "mitigation_job_id is only allowed for POST_MITIGATION tests.",
            )

    # --- inspector must be ACTIVE at placement (priority 8) ---
    if inspector["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INSPECTOR_SUSPENDED, 409, "Assigned inspector is SUSPENDED.")

    ts = now_clock()
    entity = _common_create_fields()
    entity.update(
        {
            "property_id": property_id,
            "inspector_id": inspector_id,
            "test_kind": test_kind,
            "purpose": purpose,
            "mitigation_job_id": mitigation_job_id,
            "placement_start_utc": format_iso8601_millis(ts),
            "_placement_dt": ts,
            "placement_window_hours": placement_window_hours,
            "hourly_readings": None,
            "lab_integrated_pci_l": None,
            "result_pci_l": None,
            "action_outcome": None,
            "warmup_hours_dropped": warmup_hours_dropped,
            "status": "PLACED",
        }
    )
    store.radon_tests[entity["id"]] = entity

    # Increment open_test_count; OPEN->TESTING on first placement (PRD §3.2).
    recompute_property_derived(prop)

    # POST_MITIGATION placement drives the linked job INSTALLED -> RETEST_PENDING.
    if purpose == "POST_MITIGATION":
        job["status"] = "RETEST_PENDING"
        touch(job)
        recompute_property_derived(prop)

    return object_response(public(entity), 201)


@bp.route("/radon-tests/<test_id>", methods=["GET"])
def get_test(test_id):
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    test = store.radon_tests.get(test_id)
    if test is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Radon test not found.")
    return object_response(public(test), 200)


@bp.route("/radon-tests", methods=["GET"])
def list_tests():
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    limit, offset = parse_pagination()
    from flask import request

    filters = {
        "property_id": request.args.get("property_id"),
        "inspector_id": request.args.get("inspector_id"),
        "mitigation_job_id": request.args.get("mitigation_job_id"),
        "purpose": request.args.get("purpose"),
        "status": request.args.get("status"),
    }
    items, total = paginate(store.radon_tests, filters, limit, offset)
    return array_response(items, limit, offset, total, 200)


@bp.route("/radon-tests/<test_id>/retrieve", methods=["POST"])
def retrieve_test(test_id):
    _, role = get_user_context()
    require_role(role, {"Inspector"})
    test = store.radon_tests.get(test_id)
    if test is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Radon test not found.")
    body = get_json_body()

    # --- state (priority 5) ---
    if test["status"] != "PLACED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Test is not in PLACED state.")

    # --- placement window elapsed (priority 7) ---
    elapsed = now_clock() - test["_placement_dt"]
    required = test["placement_window_hours"] * 3600
    if elapsed.total_seconds() < required:
        raise ApiError(
            errors.ERR_PLACEMENT_WINDOW_NOT_ELAPSED,
            409,
            "Placement window has not elapsed.",
        )

    # --- assigned inspector ACTIVE (priority 8) ---
    # A RECURRING test created by a fire-due has no assigned inspector_id, so the
    # suspended check is vacuously satisfied; it only applies when one is assigned.
    if test.get("inspector_id") is not None:
        inspector = store.inspectors.get(test["inspector_id"])
        if inspector is None or inspector["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INSPECTOR_SUSPENDED, 409, "Assigned inspector is SUSPENDED.")

    # --- payload by kind (mutually exclusive); ERR_INSUFFICIENT_READINGS is 409 ---
    if test["test_kind"] == "CONTINUOUS_MONITOR":
        readings = body.get("hourly_readings")
        if readings is None:
            validate.bad_request("CONTINUOUS_MONITOR retrieval requires hourly_readings.")
        if body.get("lab_integrated_pci_l") is not None:
            validate.bad_request("lab_integrated_pci_l must be null for CONTINUOUS_MONITOR.")
        if not isinstance(readings, list) or len(readings) == 0:
            validate.bad_request("hourly_readings must be a non-empty array.")
        for r in readings:
            if isinstance(r, bool) or not isinstance(r, (int, float)):
                validate.bad_request("hourly_readings must be numbers.")
            if r < 0:
                validate.bad_request("hourly_readings must be non-negative.")
        # length strictly greater than warmup_hours_dropped, else ERR_INSUFFICIENT_READINGS.
        if len(readings) <= test["warmup_hours_dropped"]:
            raise ApiError(
                errors.ERR_INSUFFICIENT_READINGS,
                409,
                "hourly_readings length must exceed warmup_hours_dropped.",
            )
        test["hourly_readings"] = readings
        test["lab_integrated_pci_l"] = None
    else:  # SHORT_TERM_48HR
        lab = body.get("lab_integrated_pci_l")
        if lab is None:
            validate.bad_request("SHORT_TERM_48HR retrieval requires lab_integrated_pci_l.")
        if body.get("hourly_readings") is not None:
            validate.bad_request("hourly_readings must be null for SHORT_TERM_48HR.")
        if isinstance(lab, bool) or not isinstance(lab, (int, float)):
            validate.bad_request("lab_integrated_pci_l must be a number.")
        if lab < 0:
            validate.bad_request("lab_integrated_pci_l must be >= 0.")
        test["lab_integrated_pci_l"] = lab
        test["hourly_readings"] = None

    test["status"] = "RETRIEVED"
    touch(test)
    # open_test_count unchanged (still open until RESULT_READY).
    return object_response(public(test), 200)


@bp.route("/radon-tests/<test_id>/record-result", methods=["POST"])
def record_result(test_id):
    _, role = get_user_context()
    require_role(role, {"Inspector"})
    test = store.radon_tests.get(test_id)
    if test is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Radon test not found.")

    # --- state (priority 5) ---
    if test["status"] != "RETRIEVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Test is not in RETRIEVED state.")

    # For a POST_MITIGATION test whose result will be NO_ACTION, the job clear is
    # gated on balance (ERR_BALANCE_NOT_SATISFIED). We must check this gate BEFORE
    # committing any state change so the record-result is atomic (PRD §3.5).
    result = calc.radon_result_average(
        test["test_kind"],
        test.get("hourly_readings"),
        test.get("lab_integrated_pci_l"),
        test["warmup_hours_dropped"],
    )
    outcome = calc.action_level_classification(result)

    job = None
    if test["purpose"] == "POST_MITIGATION" and test.get("mitigation_job_id"):
        job = store.mitigation_jobs.get(test["mitigation_job_id"])

    if (
        job is not None
        and outcome == "NO_ACTION"
        and job["status"] == "RETEST_PENDING"
    ):
        outstanding = job["quote_total_cents"] - job["deposit_required_cents"]
        if job["balance_paid_cents"] < outstanding:
            raise ApiError(
                errors.ERR_BALANCE_NOT_SATISFIED,
                409,
                "Final balance has not been satisfied; cannot clear the job.",
            )

    # --- commit: set the result, decrement open count, recompute property ---
    test["result_pci_l"] = result
    test["action_outcome"] = outcome
    test["status"] = "RESULT_READY"
    touch(test)

    prop = store.properties.get(test["property_id"])
    recompute_property_derived(prop)

    # --- cascade by purpose (PRD §3.3) ---
    if test["purpose"] == "POST_MITIGATION" and job is not None and job["status"] == "RETEST_PENDING":
        if outcome == "NO_ACTION":
            clear_job_from_retest(job, prop)
        else:  # ACTION_RECOMMENDED
            job_to_rework_from_retest(job, prop)

    return object_response(public(test), 200)


@bp.route("/radon-tests/<test_id>/void", methods=["POST"])
def void_test(test_id):
    _, role = get_user_context()
    require_role(role, {"Inspector", "PlatformAdmin"})
    test = store.radon_tests.get(test_id)
    if test is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Radon test not found.")
    if test["status"] != "PLACED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a PLACED test can be voided.")
    test["status"] = "VOIDED"
    touch(test)
    prop = store.properties.get(test["property_id"])
    recompute_property_derived(prop)
    return object_response(public(test), 200)
