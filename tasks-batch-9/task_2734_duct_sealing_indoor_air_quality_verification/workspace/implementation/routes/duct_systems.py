"""Duct systems: asbestos screening, retrofit exclusion and the test listing."""

from flask import Blueprint

import calc
import cascade
import lookup
import serialize
from envelope import array_response, object_response
from errors import ApiError
from guard import (ALL_ROLES, ROLE_PROGRAM_ADMIN, ROLE_QA_VERIFIER, authenticate, body,
                   pagination, qenum, venum, vstr)
from routes import PREFIX
from store import db, touch

bp = Blueprint("duct_systems", __name__)


@bp.get(PREFIX + "/duct-systems/<duct_system_id>")
def read_duct_system(duct_system_id):
    authenticate(ALL_ROLES)
    row = lookup.duct_system_or_404(duct_system_id)
    return object_response(serialize.duct_system(row))


@bp.post(PREFIX + "/duct-systems/<duct_system_id>/asbestos-screening")
def asbestos_screening(duct_system_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_QA_VERIFIER))
    system = lookup.duct_system_or_404(duct_system_id)
    data = body()
    result = venum(data, "asbestos_screening_result", calc.SCREENING_RESULT)
    lab_reference = vstr(data, "lab_reference")

    # rung 6 - EXCLUDED is terminal on the eligibility dimension
    if system["eligibility_status"] == "EXCLUDED":
        raise ApiError("ERR_DUCT_SYSTEM_INVALID_STATE",
                       "The duct system is already EXCLUDED.")

    system["asbestos_screening_result"] = result
    system["lab_reference"] = lab_reference

    if result == "CONFIRMED":
        # the four-hop retrofit-exclusion cascade; it owns the version bump
        cascade.exclusion_cascade(system, "ASBESTOS_CONFIRMED", "asbestos confirmed")
        return object_response(serialize.duct_system(system))

    if result == "CLEARED":
        if system["condition_grade"] == "FAIL":
            system["eligibility_status"] = "EXCLUDED"
            system["exclusion_reason"] = "STRUCTURAL_DAMAGE"
        elif system["duct_material"] == "ASBESTOS_WRAP":
            system["eligibility_status"] = "EXCLUDED"
            system["exclusion_reason"] = "MATERIAL_NOT_SEALABLE"
        elif system["eligibility_status"] == "PENDING_SCREENING":
            system["eligibility_status"] = "ELIGIBLE"
    # PENDING and SUSPECT stamp the result and leave the eligibility dimension
    # exactly where it stands (PRD section 3.2).
    touch(system)
    return object_response(serialize.duct_system(system))


@bp.post(PREFIX + "/duct-systems/<duct_system_id>/exclude")
def exclude_duct_system(duct_system_id):
    authenticate((ROLE_PROGRAM_ADMIN,))
    system = lookup.duct_system_or_404(duct_system_id)
    data = body()
    # ASBESTOS_CONFIRMED is reserved for the screening path and cannot be supplied
    reason = venum(data, "exclusion_reason", calc.MANUAL_EXCLUSION_REASON)
    if system["eligibility_status"] == "EXCLUDED":
        raise ApiError("ERR_DUCT_SYSTEM_INVALID_STATE",
                       "The duct system is already EXCLUDED.")
    cascade.exclusion_cascade(system, reason, reason)
    return object_response(serialize.duct_system(system))


@bp.get(PREFIX + "/duct-systems/<duct_system_id>/leakage-tests")
def list_leakage_tests(duct_system_id):
    authenticate(ALL_ROLES)
    lookup.duct_system_or_404(duct_system_id)
    phase = qenum("phase", calc.TEST_PHASE)
    status = qenum("status", calc.TEST_STATUS)
    rows = [t for t in lookup.leakage_tests_of_system(duct_system_id)
            if (phase is None or t["phase"] == phase)
            and (status is None or t["status"] == status)]
    limit, offset = pagination()
    window = rows[offset:offset + limit]
    return array_response([serialize.leakage_test(r) for r in window],
                          limit, offset, len(rows))
