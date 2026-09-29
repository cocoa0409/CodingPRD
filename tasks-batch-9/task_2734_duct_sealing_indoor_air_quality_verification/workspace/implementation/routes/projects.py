"""Projects, the safety-hold cycle, duct-system intake and combustion tests."""

from flask import Blueprint

import calc
import cascade
import lookup
import serialize
from envelope import array_response, object_response
from guard import (ALL_ROLES, ROLE_FIELD_TECHNICIAN, ROLE_PROGRAM_ADMIN, ROLE_QA_VERIFIER,
                   authenticate, body, fk_candidate, pagination, qenum, qstr, venum,
                   vid, vint, vnum, vstr)
from routes import PREFIX
from store import ZERO2, db, new_record

bp = Blueprint("projects", __name__)


def _page(rows, serializer):
    limit, offset = pagination()
    window = rows[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, len(rows))


# --------------------------------------------------------------------------
# Project intake (PRD section 3.1)
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/projects")
def create_project():
    authenticate((ROLE_PROGRAM_ADMIN,))
    data = body()
    # rung 4 - the only payload FK, resolved before request validity
    program_id = fk_candidate(data, "utility_program_id")
    if program_id is not None:
        lookup.program_or_404(program_id)
    else:
        vid(data, "utility_program_id", required=False)
    address_line = vstr(data, "address_line")
    area = vint(data, "conditioned_floor_area_sqft", minimum=100)
    appliances = vint(data, "gas_appliance_count", minimum=0)
    invoice = vint(data, "invoice_amount_cents", minimum=0)

    row = new_record()
    row.update({
        "utility_program_id": program_id,
        "address_line": address_line,
        "conditioned_floor_area_sqft": area,
        "gas_appliance_count": appliances,
        "invoice_amount_cents": invoice,
        "status": "ACTIVE",
        "safety_hold_reason": None,
        "_hold_seq": None,
    })
    db.projects[row["id"]] = row
    return object_response(serialize.project(row), 201)


@bp.get(PREFIX + "/projects/<project_id>")
def read_project(project_id):
    authenticate(ALL_ROLES)
    row = lookup.project_or_404(project_id)
    return object_response(serialize.project(row))


@bp.get(PREFIX + "/projects")
def list_projects():
    authenticate(ALL_ROLES)
    program_id = qstr("utility_program_id")
    status = qenum("status", calc.PROJECT_STATUS)
    rows = [p for p in db.rows("projects")
            if (program_id is None or p["utility_program_id"] == program_id)
            and (status is None or p["status"] == status)]
    return _page(rows, serialize.project)


# --------------------------------------------------------------------------
# the safety-hold cycle (PRD section 3.4)
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/projects/<project_id>/safety-hold")
def raise_hold(project_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_QA_VERIFIER))
    project = lookup.project_or_404(project_id)
    data = body()
    reason = vstr(data, "safety_hold_reason")
    # No ERR_PROJECT_INVALID_STATE exists in the catalogue, so raising a hold on
    # an already-held project simply re-stamps the reason and bumps the version.
    cascade.raise_safety_hold(project, reason, pause_jobs=True)
    return object_response(serialize.project(project))


@bp.post(PREFIX + "/projects/<project_id>/release-safety-hold")
def release_hold(project_id):
    authenticate((ROLE_PROGRAM_ADMIN,))
    project = lookup.project_or_404(project_id)
    data = body()
    note = vstr(data, "release_note")
    project["release_note"] = note
    cascade.clear_safety_hold(project)
    return object_response(serialize.project(project))


# --------------------------------------------------------------------------
# duct-system intake (PRD section 3.2)
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/projects/<project_id>/duct-systems")
def create_duct_system(project_id):
    authenticate((ROLE_PROGRAM_ADMIN, ROLE_FIELD_TECHNICIAN))
    project = lookup.project_or_404(project_id)
    data = body()
    system_label = vstr(data, "system_label")
    registers = vint(data, "total_register_count", minimum=1)
    design_cfm = vnum(data, "design_cfm", exclusive_minimum=0)
    material = venum(data, "duct_material", calc.DUCT_MATERIAL)
    grade = venum(data, "condition_grade", calc.CONDITION_GRADE)

    row = new_record()
    row.update({
        "project_id": project["id"],
        "system_label": system_label,
        "total_register_count": registers,
        "design_cfm": design_cfm,
        "duct_material": material,
        "condition_grade": grade,
        "asbestos_screening_result": "PENDING",
        "lab_reference": None,
        "eligibility_status": "PENDING_SCREENING",
        "exclusion_reason": None,
        "seal_status": "SEAL_PENDING",
        "baseline_leakage_cfm25": None,
        "working_leakage_cfm25": None,
        "sealed_leakage_reduction_cfm": ZERO2,
    })
    db.duct_systems[row["id"]] = row
    # duct_system_count is derived from the project's duct systems, so the
    # project row itself is not mutated and its version does not move.
    return object_response(serialize.duct_system(row), 201)


@bp.get(PREFIX + "/projects/<project_id>/duct-systems")
def list_duct_systems(project_id):
    authenticate(ALL_ROLES)
    lookup.project_or_404(project_id)
    eligibility = qenum("eligibility_status", calc.ELIGIBILITY_STATUS)
    seal_status = qenum("seal_status", calc.SEAL_STATUS)
    rows = [d for d in lookup.duct_systems_of_project(project_id)
            if (eligibility is None or d["eligibility_status"] == eligibility)
            and (seal_status is None or d["seal_status"] == seal_status)]
    return _page(rows, serialize.duct_system)


# --------------------------------------------------------------------------
# combustion spillage testing (PRD section 3.4)
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/projects/<project_id>/combustion-tests")
def create_combustion_test(project_id):
    user_id, _role = authenticate((ROLE_FIELD_TECHNICIAN,))
    project = lookup.project_or_404(project_id)
    data = body()
    appliance_label = vstr(data, "appliance_label")
    appliance_type = venum(data, "appliance_type", calc.APPLIANCE_TYPE)
    phase = venum(data, "phase", calc.TEST_PHASE)
    spillage = vint(data, "spillage_seconds", minimum=0)
    co_ppm = vnum(data, "co_ppm_air_free", minimum=0)
    draft = vnum(data, "draft_pressure_pa")
    wcd = vnum(data, "worst_case_depressurization_pa")

    verdict = calc.combustion_safety_verdict(appliance_type, spillage, co_ppm, draft, wcd)
    row = new_record()
    row.update({
        "project_id": project["id"],
        "appliance_label": appliance_label,
        "appliance_type": appliance_type,
        "phase": phase,
        "spillage_seconds": spillage,
        "co_ppm_air_free": co_ppm,
        "draft_pressure_pa": draft,
        "worst_case_depressurization_pa": wcd,
        "verdict": verdict,
        "performed_by_user_id": user_id,
    })
    db.combustion_tests[row["id"]] = row

    if verdict == "FAIL":
        reason = "combustion spillage failure on " + appliance_label
        if phase == "POST":
            # The POST-phase failure aborts the live runs itself, so the hold
            # must not additionally drive INJECTING runs to PAUSED.
            cascade.raise_safety_hold(project, reason, pause_jobs=False)
            cascade.abort_runs_for_post_combustion_fail(project)
        else:
            cascade.raise_safety_hold(project, reason, pause_jobs=True)
    elif phase == "POST" and verdict == "PASS":
        cascade.maybe_clear_hold_after_post_pass(project)

    return object_response(serialize.combustion_test(row), 201)


@bp.get(PREFIX + "/projects/<project_id>/combustion-tests")
def list_combustion_tests(project_id):
    authenticate(ALL_ROLES)
    lookup.project_or_404(project_id)
    phase = qenum("phase", calc.TEST_PHASE)
    verdict = qenum("verdict", calc.COMBUSTION_VERDICT)
    rows = [c for c in lookup.combustion_tests_of_project(project_id)
            if (phase is None or c["phase"] == phase)
            and (verdict is None or c["verdict"] == verdict)]
    return _page(rows, serialize.combustion_test)


# --------------------------------------------------------------------------
# comfort complaints of a project (PRD section 3.9)
# --------------------------------------------------------------------------
@bp.get(PREFIX + "/projects/<project_id>/comfort-complaints")
def list_project_complaints(project_id):
    authenticate(ALL_ROLES)
    lookup.project_or_404(project_id)
    status = qenum("status", calc.COMPLAINT_STATUS)
    rows = [c for c in lookup.complaints_of_project(project_id)
            if status is None or c["status"] == status]
    return _page(rows, serialize.comfort_complaint)
