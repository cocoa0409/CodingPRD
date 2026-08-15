"""FlowTest endpoints: schedule, list, get, results, review, reschedule, cancel."""
from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_FLOW_TEST_NOT_FOUND,
    ERR_FLOW_TEST_NOT_RESCHEDULABLE,
    ERR_FLOW_TEST_NOT_SCHEDULED,
    ERR_FLOW_TEST_NOT_SUBMITTED,
    ERR_FLOW_TEST_WINDOW_EXPIRED,
    ERR_FLOW_TEST_WINDOW_NOT_STARTED,
    ERR_FLOW_TEST_WINDOW_OVERLAP,
    ERR_HYDRANT_NOT_FOUND,
    ERR_PRESSURE_READING_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    invalid_request,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import flow_test_view
from services import (
    classify,
    compute_flow_results,
    recompute_provisional_flow,
    scheduled_window_conflict,
)
from validation import F, paginate, validate_body, validate_empty_body

bp = Blueprint("flow_tests", __name__)


def get_flow_test_or_404(flow_test_id):
    t = db.store.flow_tests.get(flow_test_id)
    if t is None:
        raise not_found(ERR_FLOW_TEST_NOT_FOUND, "FlowTest")
    return t


def _check_window_order(window_start, window_end):
    if window_end <= window_start:
        raise invalid_request("window_end must be strictly after window_start")


@bp.post("/flow-tests")
def create_flow_test():
    user_id, role = auth()
    body = validate_body([
        F("hydrant_id", "str"),
        F("window_start", "datetime"),
        F("window_end", "datetime"),
    ])
    _check_window_order(body["window_start"], body["window_end"])
    require_role(role, {"FieldOperator"})
    hydrant = db.store.hydrants.get(body["hydrant_id"])
    if hydrant is None:
        raise not_found(ERR_HYDRANT_NOT_FOUND, "Hydrant")
    if scheduled_window_conflict(hydrant["id"], body["window_start"], body["window_end"]):
        raise ApiError(
            ERR_FLOW_TEST_WINDOW_OVERLAP,
            "Window overlaps another SCHEDULED flow test on this hydrant",
            409,
        )
    test = new_base()
    test.update({
        "hydrant_id": hydrant["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "SCHEDULED",
        "static_psi": None,
        "residual_psi": None,
        "pitot_psi": None,
        "pitot_flow_gpm": None,
        "flow_at_20psi_gpm": None,
        "classification": "NONE",
        "recorded_by_user_id": None,
        "reviewed_by_user_id": None,
        "cancel_reason": None,
        # internal bookkeeping (never serialized)
        "recorded_at": None,
        "reviewed_at": None,
    })
    db.store.flow_tests[test["id"]] = test
    return success_object(flow_test_view(test), code=201)


@bp.get("/flow-tests")
def list_flow_tests():
    auth_any()
    items = list(db.store.flow_tests.values())
    hydrant_id = request.args.get("hydrant_id")
    if hydrant_id is not None:
        items = [t for t in items if t["hydrant_id"] == hydrant_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items)
    return success_list([flow_test_view(t) for t in page], meta)


@bp.get("/flow-tests/<flow_test_id>")
def get_flow_test(flow_test_id):
    auth_any()
    return success_object(flow_test_view(get_flow_test_or_404(flow_test_id)))


@bp.post("/flow-tests/<flow_test_id>/results")
def submit_results(flow_test_id):
    user_id, role = auth()
    body = validate_body([
        F("static_psi", "number"),
        F("residual_psi", "number"),
        F("pitot_psi", "number"),
    ])
    require_role(role, {"FieldOperator"})
    test = get_flow_test_or_404(flow_test_id)
    if test["status"] != "SCHEDULED":
        raise ApiError(ERR_FLOW_TEST_NOT_SCHEDULED, "Flow test must be SCHEDULED", 409)
    # Temporal gate precedes the pressure gate (PRD section 2.11 example)
    now = db.now()
    if now < test["window_start"]:
        raise ApiError(
            ERR_FLOW_TEST_WINDOW_NOT_STARTED,
            "Results submitted before window_start",
            409,
        )
    if now > test["window_end"]:
        raise ApiError(
            ERR_FLOW_TEST_WINDOW_EXPIRED,
            "Results submitted after window_end",
            409,
        )
    # Physical validity gate, evaluated before any arithmetic
    static_psi = float(body["static_psi"])
    residual_psi = float(body["residual_psi"])
    pitot_psi = float(body["pitot_psi"])
    if not (static_psi > residual_psi and residual_psi > 20):
        raise ApiError(
            ERR_PRESSURE_READING_INVALID,
            "static_psi must exceed residual_psi and residual_psi must exceed 20",
            422,
        )
    hydrant = db.store.hydrants[test["hydrant_id"]]
    pitot_stored, flow20 = compute_flow_results(hydrant, static_psi, residual_psi, pitot_psi)
    test["static_psi"] = body["static_psi"]
    test["residual_psi"] = body["residual_psi"]
    test["pitot_psi"] = body["pitot_psi"]
    test["pitot_flow_gpm"] = pitot_stored
    test["flow_at_20psi_gpm"] = flow20
    test["classification"] = classify(flow20, hydrant)
    test["recorded_by_user_id"] = user_id
    test["recorded_at"] = now
    test["status"] = "RESULTS_SUBMITTED"
    touch(test)
    hydrant["provisional_fire_flow_gpm"] = flow20
    touch(hydrant)
    return success_object(flow_test_view(test))


@bp.post("/flow-tests/<flow_test_id>/review")
def review_flow_test(flow_test_id):
    user_id, role = auth()
    body = validate_body([F("decision", "enum", arg={"APPROVE", "REJECT"})])
    require_role(role, {"UtilitySupervisor"})
    test = get_flow_test_or_404(flow_test_id)
    # Segregation of duties (priority 6) precedes the state precondition (8)
    if test["recorded_by_user_id"] is not None and user_id == test["recorded_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Reviewer must differ from the recorder",
            403,
        )
    if test["status"] != "RESULTS_SUBMITTED":
        raise ApiError(ERR_FLOW_TEST_NOT_SUBMITTED, "Flow test must be RESULTS_SUBMITTED", 409)
    hydrant = db.store.hydrants[test["hydrant_id"]]
    test["reviewed_by_user_id"] = user_id
    test["reviewed_at"] = db.now()
    if body["decision"] == "APPROVE":
        test["status"] = "APPROVED"
        touch(test)
        hydrant["approved_fire_flow_gpm"] = test["flow_at_20psi_gpm"]
        touch(hydrant)
    else:
        test["status"] = "REJECTED"
        touch(test)
        # provisional recomputed from remaining RESULTS_SUBMITTED or APPROVED tests
        recompute_provisional_flow(hydrant)
        touch(hydrant)
    return success_object(flow_test_view(test))


@bp.post("/flow-tests/<flow_test_id>/reschedule")
def reschedule_flow_test(flow_test_id):
    user_id, role = auth()
    body = validate_body([
        F("window_start", "datetime"),
        F("window_end", "datetime"),
    ])
    _check_window_order(body["window_start"], body["window_end"])
    require_role(role, {"FieldOperator"})
    test = get_flow_test_or_404(flow_test_id)
    if test["status"] not in ("REJECTED", "MISSED"):
        raise ApiError(
            ERR_FLOW_TEST_NOT_RESCHEDULABLE,
            "Flow test must be REJECTED or MISSED to reschedule",
            409,
        )
    if scheduled_window_conflict(
        test["hydrant_id"], body["window_start"], body["window_end"], exclude_id=test["id"]
    ):
        raise ApiError(
            ERR_FLOW_TEST_WINDOW_OVERLAP,
            "Window overlaps another SCHEDULED flow test on this hydrant",
            409,
        )
    test["window_start"] = body["window_start"]
    test["window_end"] = body["window_end"]
    test["status"] = "SCHEDULED"
    touch(test)
    return success_object(flow_test_view(test))


@bp.post("/flow-tests/<flow_test_id>/cancel")
def cancel_flow_test(flow_test_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"FieldOperator"})
    test = get_flow_test_or_404(flow_test_id)
    if test["status"] != "SCHEDULED":
        raise ApiError(ERR_FLOW_TEST_NOT_SCHEDULED, "Flow test must be SCHEDULED", 409)
    test["status"] = "CANCELLED"
    test["cancel_reason"] = "OPERATOR_CANCEL"
    touch(test)
    return success_object(flow_test_view(test))
