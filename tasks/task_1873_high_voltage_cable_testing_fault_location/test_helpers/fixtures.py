"""Composite setup helpers for the cable-diagnostics test suite.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
`get_success_data` validator so a broken precondition surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Standard scenario timeline used by the deep fixtures (all against the logical
clock, PRD §2.4):
  - outage window 2026-08-10T08:00Z -> 2026-08-12T12:00Z (APPROVED, then ACTIVE)
  - clock set to 2026-08-10T09:00Z; job started
  - dig window 2026-08-10T09:30Z -> 11:00Z; clock 09:45Z for the dig start
  - curing starts 09:45Z; clock 2026-08-11T10:00Z satisfies the 24h cure gate
  - clock 2026-08-11T10:05Z for the acceptance re-test (strictly after
    the splice's completed_at, PRD §3.8)
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    SAFETY_OFFICER_1_HEADERS,
    SAFETY_OFFICER_2_HEADERS,
    SAFETY_OFFICER_3_HEADERS,
    FIELD_TECHNICIAN_1_HEADERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
SUPERVISOR = TEST_USERS["test_supervisor_headers"]
TECHNICIAN = FIELD_TECHNICIAN_1_HEADERS
CREW_LEAD = TEST_USERS["fault_crew_lead_headers"]
DISPATCH = TEST_USERS["dispatch_coordinator_headers"]
ENGINEER = TEST_USERS["asset_engineer_headers"]


# --------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(_api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_circuit(circuit_ref="CKT-1", voltage_class="KV_15", length_m=1000,
                   installation_year=2015, calibrated_velocity_factor=None) -> dict:
    payload = F.create_circuit_payload(
        circuit_ref=circuit_ref, voltage_class=voltage_class,
        length_m=length_m, installation_year=installation_year,
    )
    if calibrated_velocity_factor is not None:
        payload["calibrated_velocity_factor"] = calibrated_velocity_factor
    return get_success_data(_api.create_circuit(payload, ADMIN), 201)


def create_window(circuit_id, kind="PLANNED_DIAGNOSTIC",
                  window_start=C.WINDOW_START, window_end=C.WINDOW_END) -> dict:
    payload = F.create_window_payload(
        circuit_id, kind=kind, window_start=window_start, window_end=window_end,
    )
    return get_success_data(_api.create_outage_window(payload, PLANNER), 201)


def approve_window(window_id) -> dict:
    return get_success_data(_api.approve_window(window_id, PLANNER))


def activate_window(window_id) -> dict:
    return get_success_data(_api.activate_window(window_id, PLANNER))


def close_window(window_id, restored_at) -> dict:
    return get_success_data(_api.close_window(window_id, {"restored_at": restored_at}, PLANNER))


def create_job(circuit_id, window_id, requested_methods=None,
               approved_budget_cents=800000, use_temperature_correction=None) -> dict:
    overrides = {}
    if requested_methods is not None:
        overrides["requested_methods"] = requested_methods
    overrides["approved_budget_cents"] = approved_budget_cents
    if use_temperature_correction is not None:
        overrides["use_temperature_correction"] = use_temperature_correction
    payload = F.create_job_payload(circuit_id, window_id, **overrides)
    return get_success_data(_api.create_test_job(payload, PLANNER), 201)


def plan_job(job_id) -> dict:
    return get_success_data(_api.plan_job(job_id, PLANNER))


def create_permit(job_id, isolation_points=None, ground_count=2) -> dict:
    payload = F.create_permit_payload(
        job_id,
        isolation_points=isolation_points if isolation_points is not None else ["SW-N", "SW-F"],
        ground_count=ground_count,
    )
    return get_success_data(_api.create_permit(payload, SAFETY_OFFICER_1_HEADERS), 201)


def issue_permit(permit_id) -> dict:
    """Issue as officer so-1 (records issued_by_user_id, PRD §3.4)."""
    return get_success_data(_api.issue_permit(permit_id, SAFETY_OFFICER_1_HEADERS))


def verify_grounding(permit_id) -> dict:
    """Verify grounding as officer so-2, independent of the issuer (PRD §2.9)."""
    return get_success_data(_api.verify_grounding(permit_id, SAFETY_OFFICER_2_HEADERS))


def release_permit(permit_id) -> dict:
    """Release as officer so-3, independent of the verifier (PRD §2.9)."""
    return get_success_data(_api.release_permit(permit_id, SAFETY_OFFICER_3_HEADERS))


def create_unit(unit_code="VAN-1", capabilities=None, max_test_voltage_kv=30.0) -> dict:
    payload = F.create_unit_payload(
        unit_code=unit_code,
        capabilities=capabilities if capabilities is not None else ["VLF", "PD", "TDR"],
        max_test_voltage_kv=max_test_voltage_kv,
    )
    return get_success_data(_api.create_mobile_unit(payload, ADMIN), 201)


def create_assignment(unit_id, job_id, mobilize_at=C.MOBILIZE_AT,
                      demobilize_at=C.DEMOBILIZE_AT) -> dict:
    payload = F.create_assignment_payload(
        unit_id, job_id, mobilize_at=mobilize_at, demobilize_at=demobilize_at,
    )
    return get_success_data(_api.create_assignment(payload, DISPATCH), 201)


def confirm_assignment(assignment_id) -> dict:
    return get_success_data(_api.confirm_assignment(assignment_id, DISPATCH))


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy — circuit + window + job composite states
# --------------------------------------------------------------------------

def setup_approved_window_scenario(circuit_ref="CKT-1", length_m=1000,
                                   installation_year=2015, voltage_class="KV_15",
                                   calibrated_velocity_factor=None, kind="PLANNED_DIAGNOSTIC",
                                   window_start=C.WINDOW_START, window_end=C.WINDOW_END) -> dict:
    """Circuit + window approved (circuit OUTAGE_PENDING)."""
    circuit = create_circuit(circuit_ref, voltage_class, length_m,
                             installation_year, calibrated_velocity_factor)
    window = create_window(circuit["id"], kind, window_start, window_end)
    approve_window(window["id"])
    return {"circuit": circuit, "window": window}


def setup_planned_job(circuit_ref="CKT-1", length_m=1000, installation_year=2015,
                      voltage_class="KV_15", calibrated_velocity_factor=None,
                      requested_methods=None, approved_budget_cents=800000,
                      use_temperature_correction=None) -> dict:
    """Circuit + APPROVED window + job planned (PLANNED, estimate stored)."""
    ctx = setup_approved_window_scenario(
        circuit_ref, length_m, installation_year, voltage_class,
        calibrated_velocity_factor,
    )
    job = create_job(ctx["circuit"]["id"], ctx["window"]["id"],
                     requested_methods, approved_budget_cents, use_temperature_correction)
    job = plan_job(job["id"])
    ctx["job"] = job
    return ctx


def setup_grounded_job(with_equipment=True, **kwargs) -> dict:
    """Planned job + permit driven to GROUNDING_VERIFIED (+ confirmed unit).

    Does NOT touch the clock or activate the window: the circuit sits in
    GROUNDED with the job PLANNED.
    """
    ctx = setup_planned_job(**kwargs)
    permit = create_permit(ctx["job"]["id"])
    permit = issue_permit(permit["id"])
    permit = verify_grounding(permit["id"])
    ctx["permit"] = permit
    if with_equipment:
        unit = create_unit()
        assignment = create_assignment(unit["id"], ctx["job"]["id"])
        assignment = confirm_assignment(assignment["id"])
        ctx["unit"] = unit
        ctx["assignment"] = assignment
    return ctx


def setup_job_in_progress(with_permit=True, with_equipment=True,
                          clock=C.CLOCK_IN_WINDOW, **kwargs) -> dict:
    """Full preamble to job IN_PROGRESS: circuit, APPROVED window, PLANNED job,
    (optionally) permit GROUNDING_VERIFIED, (optionally) unit with CONFIRMED
    assignment; clock moved inside the window; window ACTIVE; job started."""
    ctx = setup_grounded_job(with_equipment=with_equipment, **kwargs) if with_permit \
        else _planned_job_with_optional_equipment(with_equipment, **kwargs)
    set_clock(clock)
    ctx["window"] = activate_window(ctx["window"]["id"])
    ctx["job"] = get_success_data(_api.start_job(ctx["job"]["id"], SUPERVISOR))
    return ctx


def _planned_job_with_optional_equipment(with_equipment, **kwargs) -> dict:
    ctx = setup_planned_job(**kwargs)
    if with_equipment:
        unit = create_unit()
        assignment = create_assignment(unit["id"], ctx["job"]["id"])
        assignment = confirm_assignment(assignment["id"])
        ctx["unit"] = unit
        ctx["assignment"] = assignment
    return ctx


# --------------------------------------------------------------------------
# Tier 3: series lifecycle shortcuts
# --------------------------------------------------------------------------

def create_series(job_id, method="VLF_TAN_DELTA", test_voltage_kv=C.KV15_TEST_VOLTAGE,
                  is_retest=None, retest_of_fault_id=None) -> dict:
    overrides = {}
    if is_retest is not None:
        overrides["is_retest"] = is_retest
    if retest_of_fault_id is not None:
        overrides["retest_of_fault_id"] = retest_of_fault_id
    payload = F.create_series_payload(job_id, method=method,
                                      test_voltage_kv=test_voltage_kv, **overrides)
    return get_success_data(_api.create_test_series(payload, SUPERVISOR), 201)


def energize_series(series_id) -> dict:
    return get_success_data(_api.energize_series(series_id, SUPERVISOR))


def add_reading(series_id, step_index, applied_voltage_kv, tan_delta_e3=None,
                pd_level_pc=None, ambient_temp_c=20.0, pd_location_m=None) -> dict:
    payload = F.create_reading_payload(
        step_index, applied_voltage_kv=applied_voltage_kv, ambient_temp_c=ambient_temp_c,
    )
    if tan_delta_e3 is not None:
        payload["tan_delta_e3"] = tan_delta_e3
    if pd_level_pc is not None:
        payload["pd_level_pc"] = pd_level_pc
    if pd_location_m is not None:
        payload["pd_location_m"] = pd_location_m
    return get_success_data(_api.add_reading(series_id, payload, TECHNICIAN), 201)


def log_vlf_steps(series_id, td_values, ambient_temp_c=20.0,
                  kv_steps=(4.35, 8.7, C.KV15_TEST_VOLTAGE)):
    """Append one tan-delta reading per step of a VLF series."""
    for i, td in enumerate(td_values):
        add_reading(series_id, i, kv_steps[i], tan_delta_e3=td,
                    ambient_temp_c=ambient_temp_c)


def log_vlf_pd_steps(series_id, td, pd, ambient_temp_c=20.0,
                     kv_steps=(4.35, 8.7, C.KV15_TEST_VOLTAGE)):
    """Append tan-delta + PD readings on all three steps of a VLF_WITH_PD series."""
    for i, kv in enumerate(kv_steps):
        add_reading(series_id, i, kv, tan_delta_e3=td, pd_level_pc=pd,
                    ambient_temp_c=ambient_temp_c)


def evaluate_series(series_id) -> dict:
    return get_success_data(_api.evaluate_series(series_id, SUPERVISOR))


def accept_series(series_id) -> dict:
    return get_success_data(_api.accept_series(series_id, PLANNER))


def create_energized_series(job_id, method="VLF_TAN_DELTA",
                            test_voltage_kv=C.KV15_TEST_VOLTAGE) -> dict:
    series = create_series(job_id, method, test_voltage_kv)
    return energize_series(series["id"])


def create_evaluated_vlf_series(job_id, td_values, ambient_temp_c=20.0,
                                test_voltage_kv=C.KV15_TEST_VOLTAGE) -> dict:
    """VLF_TAN_DELTA series energized, fully logged, evaluated."""
    series = create_energized_series(job_id, "VLF_TAN_DELTA", test_voltage_kv)
    log_vlf_steps(series["id"], td_values, ambient_temp_c)
    return evaluate_series(series["id"])


def create_fail_series_with_fault(job_id, td_values=(90.0, 90.0, 90.0)) -> tuple:
    """Evaluated FAIL series and its auto-created SUSPECTED fault.

    Returns (series, fault_id).
    """
    series = create_evaluated_vlf_series(job_id, td_values)
    faults = get_success_data(_api.list_series_faults(series["id"], SUPERVISOR))
    assert len(faults) == 1, f"Setup failed: expected 1 auto-created fault, got {faults}"
    return series, faults[0]["id"]


# --------------------------------------------------------------------------
# Tier 3 (cont.): fault -> excavation -> splice -> retest lifecycle
# --------------------------------------------------------------------------

def pinpoint_fault(fault_id, trace_time_us=20.0, pinpoint_method="PULSE_ECHO",
                   use_calibrated_velocity=None) -> dict:
    payload = F.pinpoint_fault_payload(
        trace_time_us=trace_time_us, pinpoint_method=pinpoint_method,
    )
    if use_calibrated_velocity is not None:
        payload["use_calibrated_velocity"] = use_calibrated_velocity
    return get_success_data(_api.pinpoint_fault(fault_id, payload, CREW_LEAD))


def create_excavation(fault_id, target_location_m=1560.0, dig_start=C.DIG_START,
                      dig_end=C.DIG_END, cost_cents=100040, permit_ref="MX-100") -> dict:
    payload = F.create_excavation_payload(
        fault_id, target_location_m=target_location_m, dig_start=dig_start,
        dig_end=dig_end, cost_cents=cost_cents, permit_ref=permit_ref,
    )
    return get_success_data(_api.create_excavation(payload, CREW_LEAD), 201)


def drive_excavation_in_progress(excavation_id, clock=C.CLOCK_DIG) -> dict:
    """Permit granted, clock moved inside the dig window, digging started
    (fault PINPOINTED -> EXCAVATING)."""
    get_success_data(_api.permit_excavation(excavation_id, CREW_LEAD))
    set_clock(clock)
    return get_success_data(_api.start_excavation(excavation_id, CREW_LEAD))


def create_splice(fault_id, excavation_id, splice_type="HEAT_SHRINK",
                  cost_cents=200040) -> dict:
    payload = F.create_splice_payload(
        fault_id, excavation_id, splice_type=splice_type, cost_cents=cost_cents,
    )
    return get_success_data(_api.create_splice(payload, CREW_LEAD), 201)


def drive_splice_curing(splice_id) -> dict:
    """Start splicing (fault EXCAVATING -> REPAIRING) and begin the cure."""
    get_success_data(_api.start_splice(splice_id, CREW_LEAD))
    return get_success_data(_api.cure_splice(splice_id, CREW_LEAD))


def drive_splice_completed(splice_id, finish_clock=C.CLOCK_AFTER_CURING) -> dict:
    """Splice through curing to COMPLETED (fault REPAIRING -> REPAIRED):
    the clock is moved beyond cure_started_at + 24h before finishing."""
    drive_splice_curing(splice_id)
    set_clock(finish_clock)
    return get_success_data(_api.finish_curing(splice_id, CREW_LEAD))


def create_passing_retest(job_id, fault_id, clock=C.CLOCK_RETEST,
                          td_values=(2.0, 2.1, 2.2)) -> dict:
    """Acceptance re-test created strictly after splice completed_at (PRD §3.8),
    energized, logged with PASS readings, evaluated and customer-accepted.
    Moves the fault REPAIRED -> RETESTING."""
    set_clock(clock)
    retest = create_series(job_id, "VLF_TAN_DELTA", C.KV15_TEST_VOLTAGE,
                           is_retest=True, retest_of_fault_id=fault_id)
    energize_series(retest["id"])
    log_vlf_steps(retest["id"], td_values)
    evaluate_series(retest["id"])
    return accept_series(retest["id"])


def accept_splice(splice_id) -> dict:
    return get_success_data(_api.accept_splice(splice_id, PLANNER))


# --------------------------------------------------------------------------
# Tier 5: terminal-state composites
# --------------------------------------------------------------------------

def setup_retest_accepted(circuit_ref="CKT-RT", length_m=1000,
                          approved_budget_cents=800000,
                          accept_original_series=False) -> dict:
    """Repair cycle stopped just before customer acceptance of the splice:
    FAIL series -> fault -> pinpoint -> excavation IN_PROGRESS -> splice
    COMPLETED -> passing re-test ACCEPTED. The fault sits in RETESTING and
    the splice in COMPLETED, ready for the acceptance trigger (PRD §3.8).

    With accept_original_series=True the original FAIL series is also
    customer-accepted, so the later splice acceptance will satisfy the job's
    evaluation gate (job IN_PROGRESS -> EVALUATION, circuit UNDER_TEST ->
    TEST_COMPLETE). With False the job remains IN_PROGRESS after acceptance.
    """
    ctx = setup_job_in_progress(
        circuit_ref=circuit_ref, length_m=length_m,
        approved_budget_cents=approved_budget_cents,
    )
    series, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
    if accept_original_series:
        accept_series(series["id"])
    pinpoint_fault(fault_id)
    excavation = create_excavation(fault_id)
    drive_excavation_in_progress(excavation["id"])
    splice = create_splice(fault_id, excavation["id"])
    drive_splice_completed(splice["id"])
    retest = create_passing_retest(ctx["job"]["id"], fault_id)
    ctx.update({
        "series": series,
        "fault_id": fault_id,
        "excavation": excavation,
        "splice": splice,
        "retest": retest,
    })
    return ctx


def setup_fault_closed_verified(circuit_ref="CKT-FC", length_m=1000,
                                approved_budget_cents=800000,
                                accept_original_series=False) -> dict:
    """Full repair cycle through splice ACCEPTED, so the fault is
    CLOSED_VERIFIED (PRD §3.7 closure cascade). See setup_retest_accepted for
    the meaning of accept_original_series."""
    ctx = setup_retest_accepted(
        circuit_ref=circuit_ref, length_m=length_m,
        approved_budget_cents=approved_budget_cents,
        accept_original_series=accept_original_series,
    )
    ctx["splice"] = accept_splice(ctx["splice"]["id"])
    return ctx


def setup_job_in_evaluation(circuit_ref="CKT-EV", length_m=1000,
                            approved_budget_cents=800000) -> dict:
    """Full repair cycle with the original series accepted: job EVALUATION,
    circuit TEST_COMPLETE, permit still GROUNDING_VERIFIED."""
    return setup_fault_closed_verified(
        circuit_ref=circuit_ref, length_m=length_m,
        approved_budget_cents=approved_budget_cents,
        accept_original_series=True,
    )


def setup_job_completed(circuit_ref="CKT-DONE") -> dict:
    """Job driven all the way to COMPLETED (permit RELEASED by so-3)."""
    ctx = setup_job_in_evaluation(circuit_ref=circuit_ref)
    release_permit(ctx["permit"]["id"])
    ctx["job"] = get_success_data(_api.complete_job(ctx["job"]["id"], SUPERVISOR))
    return ctx


# --------------------------------------------------------------------------
# Health assessments (OCC-guarded create-with-supersede, PRD §3.9)
# --------------------------------------------------------------------------

def create_health_assessment(circuit_id, basis="FORMAL") -> dict:
    """Create an assessment carrying the circuit's currently observed version
    as expected_circuit_version (the OCC field, PRD §2.6)."""
    circuit = get_success_data(_api.get_circuit(circuit_id, ENGINEER))
    payload = F.create_health_assessment_payload(
        circuit_id, expected_circuit_version=circuit["version"], basis=basis,
    )
    return get_success_data(_api.create_health_assessment(payload, ENGINEER), 201)


def review_assessment(assessment_id) -> dict:
    return get_success_data(_api.review_assessment(assessment_id, ENGINEER))


def adopt_assessment(assessment_id) -> dict:
    return get_success_data(_api.adopt_assessment(assessment_id, PLANNER))


# --------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------

def get_circuit(circuit_id) -> dict:
    return get_success_data(_api.get_circuit(circuit_id, PLANNER))


def get_window(window_id) -> dict:
    return get_success_data(_api.get_outage_window(window_id, PLANNER))


def get_job(job_id) -> dict:
    return get_success_data(_api.get_test_job(job_id, PLANNER))


def get_fault(fault_id) -> dict:
    return get_success_data(_api.get_fault(fault_id, SUPERVISOR))


def get_unit(unit_id) -> dict:
    return get_success_data(_api.get_mobile_unit(unit_id, DISPATCH))


def get_assignment(assignment_id) -> dict:
    return get_success_data(_api.get_assignment(assignment_id, DISPATCH))
