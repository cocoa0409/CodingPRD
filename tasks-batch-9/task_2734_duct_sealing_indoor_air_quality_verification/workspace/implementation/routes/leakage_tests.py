"""Leakage measurements: reservation, pressurization, recording and QA review."""

from datetime import timedelta

from flask import Blueprint

import calc
import lookup
import serialize
from envelope import object_response
from errors import ApiError
from guard import (ALL_ROLES, ROLE_FIELD_TECHNICIAN, ROLE_QA_VERIFIER, authenticate, body,
                   fk_candidate, venum, vid, vint, vnum, vstr, vdt)
from routes import PREFIX
from store import ZERO2, db, new_record, touch

bp = Blueprint("leakage_tests", __name__)

BUFFER = timedelta(minutes=calc.STABILIZATION_BUFFER_MINUTES)


@bp.post(PREFIX + "/leakage-tests")
def create_leakage_test():
    authenticate((ROLE_FIELD_TECHNICIAN, ROLE_QA_VERIFIER))
    data = body()
    # rung 4
    system_id = fk_candidate(data, "duct_system_id")
    if system_id is None:
        vid(data, "duct_system_id")
    system = lookup.duct_system_or_404(system_id)
    # rung 5
    phase = venum(data, "phase", calc.TEST_PHASE)
    method = venum(data, "method", calc.TEST_METHOD)
    start_at = vdt(data, "window_start_at")
    end_at = vdt(data, "window_end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'window_end_at' must be strictly after 'window_start_at'.")
    # rung 11 - the CLOSED buffered interval of PRD section 3.3
    low = start_at - BUFFER
    high = end_at + BUFFER
    for other in lookup.leakage_tests_of_system(system["id"]):
        if other["status"] == "REJECTED":
            continue
        other_low = other["window_start_at"] - BUFFER
        other_high = other["window_end_at"] + BUFFER
        if low <= other_high and other_low <= high:
            raise ApiError("ERR_TEST_WINDOW_CONFLICT",
                           "The buffered test window intersects another reservation "
                           "on this duct system.")

    row = new_record()
    row.update({
        "duct_system_id": system["id"],
        "phase": phase,
        "method": method,
        "window_start_at": start_at,
        "window_end_at": end_at,
        "status": "DRAFT",
        "test_pressure_pa": None,
        "fan_ring_config": None,
        "masked_register_count": None,
        "measured_leakage_cfm": None,
        "ambient_temp_f": None,
        "normalized_leakage_cfm25": None,
        "leakage_per_100_sqft": None,
        "performed_by_user_id": None,
        "reviewed_by_user_id": None,
        "review_note": None,
    })
    db.leakage_tests[row["id"]] = row
    return object_response(serialize.leakage_test(row), 201)


@bp.get(PREFIX + "/leakage-tests/<test_id>")
def read_leakage_test(test_id):
    authenticate(ALL_ROLES)
    row = lookup.leakage_test_or_404(test_id)
    return object_response(serialize.leakage_test(row))


@bp.post(PREFIX + "/leakage-tests/<test_id>/pressurize")
def pressurize(test_id):
    authenticate((ROLE_FIELD_TECHNICIAN,))
    test = lookup.leakage_test_or_404(test_id)
    data = body()
    pressure = vnum(data, "test_pressure_pa", minimum=10, maximum=100)
    ring = venum(data, "fan_ring_config", calc.FAN_RING_CONFIG)
    masked = vint(data, "masked_register_count", minimum=0)
    system = db.duct_systems.get(test["duct_system_id"])
    # The masked-count equality of PRD section 3.3 has no dedicated error id -
    # ERR_MASKING_INCOMPLETE is scoped to start-injection - so the mismatch is a
    # rung-5 malformed request.
    if system is not None and masked != system["total_register_count"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'masked_register_count' must equal the duct system's "
                       "total_register_count.")
    # rung 6
    if test["status"] != "DRAFT":
        raise ApiError("ERR_LEAKAGE_TEST_INVALID_STATE",
                       "Pressurization requires status DRAFT.")
    # a system excluded from the retrofit cannot be pressurized at all
    if system is not None and system["eligibility_status"] == "EXCLUDED":
        raise ApiError("ERR_DUCT_SYSTEM_EXCLUDED",
                       "The duct system is excluded from the retrofit.")

    test["test_pressure_pa"] = pressure
    test["fan_ring_config"] = ring
    test["masked_register_count"] = masked
    test["status"] = "PRESSURIZED"
    touch(test)
    return object_response(serialize.leakage_test(test))


@bp.post(PREFIX + "/leakage-tests/<test_id>/record")
def record(test_id):
    user_id, _role = authenticate((ROLE_FIELD_TECHNICIAN,))
    test = lookup.leakage_test_or_404(test_id)
    data = body()
    measured = vnum(data, "measured_leakage_cfm", minimum=0)
    ambient = vnum(data, "ambient_temp_f")
    if test["status"] != "PRESSURIZED":
        raise ApiError("ERR_LEAKAGE_TEST_INVALID_STATE",
                       "Recording requires status PRESSURIZED.")

    system = db.duct_systems.get(test["duct_system_id"])
    project = lookup.project_of_system(system) if system is not None else None
    area = project["conditioned_floor_area_sqft"] if project is not None else 100
    normalized, per_area = calc.normalized_duct_leakage(measured, test["test_pressure_pa"], area)

    test["measured_leakage_cfm"] = measured
    test["ambient_temp_f"] = ambient
    test["normalized_leakage_cfm25"] = normalized
    test["leakage_per_100_sqft"] = per_area
    test["performed_by_user_id"] = user_id
    test["status"] = "RECORDED"
    touch(test)
    return object_response(serialize.leakage_test(test))


@bp.post(PREFIX + "/leakage-tests/<test_id>/review")
def review(test_id):
    user_id, _role = authenticate((ROLE_QA_VERIFIER,))
    test = lookup.leakage_test_or_404(test_id)
    # rung 3 - the measurer may not review their own measurement
    if test.get("performed_by_user_id") is not None \
            and user_id == test["performed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The technician who recorded a measurement cannot review it.")
    data = body()
    decision = venum(data, "decision", calc.REVIEW_DECISION)
    note = vstr(data, "review_note", required=False, allow_empty=True)
    if test["status"] != "RECORDED":
        raise ApiError("ERR_LEAKAGE_TEST_INVALID_STATE",
                       "Review requires status RECORDED.")

    test["reviewed_by_user_id"] = user_id
    test["review_note"] = note
    test["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    touch(test)

    if decision == "ACCEPT" and test["phase"] == "PRE":
        system = db.duct_systems.get(test["duct_system_id"])
        if system is not None:
            system["baseline_leakage_cfm25"] = test["normalized_leakage_cfm25"]
            system["working_leakage_cfm25"] = test["normalized_leakage_cfm25"]
            system["sealed_leakage_reduction_cfm"] = ZERO2
            touch(system)
    return object_response(serialize.leakage_test(test))
