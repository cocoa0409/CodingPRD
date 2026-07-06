"""Fluoroscopy suite scheduling: cleanup-buffered interval overlap, half-open adjacency,
and optimistic-concurrency on the clinic version.

Queue A: resource_temporal_overlap.
Queue B: cross_cutting_complexity_layers (OCC).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_active_procedure_patient,
    create_approved_procedure_pa,
    request_procedure,
    schedule_procedure_with_current_version,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def test_buffered_overlap_within_cleanup_conflicts(api):
    """PRD 3.7: "the interval begins at the procedure's `start_utc` and ends at `start_utc`
    plus `duration_minutes` plus the suite's `cleanup_buffer_minutes`, with the end excluded.
    The requested procedure conflicts with an existing `SCHEDULED` procedure in the same suite
    when the requested start falls strictly before the existing procedure's buffered end and
    the existing procedure's start falls strictly before the requested procedure's buffered
    end. Any such overlap is rejected with `ERR_SUITE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/suite_buffered_overlap_within_cleanup_conflicts
    """
    ctx = setup_active_procedure_patient(modality="INJECTION")
    clinic_id, patient_id, plan_id, suite_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["plan"]["id"], ctx["suite"]["id"],
    )
    pa1 = create_approved_procedure_pa(clinic_id, patient_id)
    pa2 = create_approved_procedure_pa(clinic_id, patient_id)

    # Proc A 10:00-10:30 + 15 cleanup -> buffered [10:00, 10:45)
    proc1 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa1["id"],
                              start_utc="2026-06-10T10:00:00Z", duration_minutes=30)
    schedule_procedure_with_current_version(clinic_id, patient_id, proc1["id"])

    # Proc B starts 10:40 (< 10:45) -> conflict
    proc2 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa2["id"],
                              start_utc="2026-06-10T10:40:00Z", duration_minutes=30)
    clinic = validate_success(api.get_clinic(clinic_id, ADMIN), 200)
    resp = api.schedule_procedure(
        clinic_id, patient_id, proc2["id"], {"expected_clinic_version": clinic["version"]}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_SUITE_TIME_CONFLICT.value)

    procs = validate_success(api.list_procedures(clinic_id, patient_id, INTAKE), 200)
    assert [p for p in procs if p["id"] == proc2["id"]][0]["status"] == "REQUESTED"
    suites = validate_success(api.list_fluoroscopy_suites(clinic_id, INTAKE), 200)
    assert [s for s in suites if s["id"] == suite_id][0]["booked_minutes"] == 30


def test_back_to_back_at_buffer_end_no_conflict(api):
    """PRD 3.7: "with the end excluded. The requested procedure conflicts with an existing
    `SCHEDULED` procedure in the same suite when the requested start falls strictly before the
    existing procedure's buffered end."
    PRD 3.7: "the suite's `booked_minutes` is increased by the procedure's `duration_minutes`."

    Design: Difficulty/resource_temporal_overlap/suite_back_to_back_after_buffer_no_conflict
    """
    ctx = setup_active_procedure_patient(modality="INJECTION")
    clinic_id, patient_id, plan_id, suite_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["plan"]["id"], ctx["suite"]["id"],
    )
    pa1 = create_approved_procedure_pa(clinic_id, patient_id)
    pa2 = create_approved_procedure_pa(clinic_id, patient_id)

    proc1 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa1["id"],
                              start_utc="2026-06-10T10:00:00Z", duration_minutes=30)
    schedule_procedure_with_current_version(clinic_id, patient_id, proc1["id"])

    # Proc B starts exactly at 10:45 (== buffered end) -> half-open, no conflict
    proc2 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa2["id"],
                              start_utc="2026-06-10T10:45:00Z", duration_minutes=30)
    scheduled = schedule_procedure_with_current_version(clinic_id, patient_id, proc2["id"])
    assert scheduled["status"] == "SCHEDULED"

    suites = validate_success(api.list_fluoroscopy_suites(clinic_id, INTAKE), 200)
    assert [s for s in suites if s["id"] == suite_id][0]["booked_minutes"] == 60


def test_stale_clinic_version_rejected(api):
    """PRD 2.11: "If `expected_clinic_version` does not match the clinic's current `version` ...
    the scheduling request is rejected with `ERR_STALE_CLINIC_VERSION` (HTTP 412), before any
    business logic runs."
    PRD 2.11: "every successful suite scheduling increments the enclosing `Clinic`'s `version`
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_clinic_version_rejected
    """
    ctx = setup_active_procedure_patient(modality="INJECTION")
    clinic_id, patient_id, plan_id, suite_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["plan"]["id"], ctx["suite"]["id"],
    )
    pa1 = create_approved_procedure_pa(clinic_id, patient_id)
    pa2 = create_approved_procedure_pa(clinic_id, patient_id)

    # Two non-overlapping requested procedures.
    proc1 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa1["id"],
                              start_utc="2026-06-10T10:00:00Z", duration_minutes=30)
    proc2 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa2["id"],
                              start_utc="2026-06-10T13:00:00Z", duration_minutes=30)

    clinic = validate_success(api.get_clinic(clinic_id, ADMIN), 200)
    stale_version = clinic["version"]

    # First schedule succeeds and bumps the clinic version.
    validate_success(
        api.schedule_procedure(
            clinic_id, patient_id, proc1["id"], {"expected_clinic_version": stale_version}, INTAKE
        ), 200,
    )

    # Second schedule still carries the pre-bump version -> 412.
    resp = api.schedule_procedure(
        clinic_id, patient_id, proc2["id"], {"expected_clinic_version": stale_version}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLINIC_VERSION.value, expected_status=412)

    procs = validate_success(api.list_procedures(clinic_id, patient_id, INTAKE), 200)
    assert [p for p in procs if p["id"] == proc2["id"]][0]["status"] == "REQUESTED"
