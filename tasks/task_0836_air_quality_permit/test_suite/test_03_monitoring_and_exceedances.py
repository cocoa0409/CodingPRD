"""Stack testing, CEM data, and exceedance reporting.

Covers the stack-test-failure cascade, the exceedance report deadline fork, the
strict CEM exceedance boundary, and the stack-test buffer overlap rule.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    register_facility, setup_facility_with_source, register_source,
    create_stack_test, create_exceedance,
    make_facility_operator_headers, TEST_USERS,
    create_cem_data_payload,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ENFORCER = TEST_USERS["enforcement_officer_headers"]


# ─── transitive_cascade / stack_test_failed_cascades_to_facility_deviation ───

def test_stack_test_failure_pushes_facility_to_deviation(api):
    """PRD §3.4: "If instead the measured rate is greater than the source's
    max_hourly_rate_lbs, the test moves CONDUCTED → FAILED and the system opens an
    exceedance event of type EXCEEDANCE in OPEN status on that source ... which in
    turn pushes the facility into DEVIATION as described in §3.5." PRD §3.5:
    "Filing an exceedance, like a stack-test failure, starts it in OPEN ...
    increases the facility's open_exceedance_count by one, and moves the facility's
    compliance_status to DEVIATION."

    Design: Difficulty/transitive_cascade/stack_test_failed_cascades_to_facility_deviation
    """
    facility, source = setup_facility_with_source(
        "Foxtrot Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    op = make_facility_operator_headers(facility["id"])
    st = create_stack_test(source["id"], "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    result = validate_success(api.conduct_stack_test(st["id"], {"measured_rate_lbs": 60}, INSPECTOR), 200)
    assert result["status"] == "FAILED"
    fac = validate_success(api.get_facility(facility["id"], op), 200)
    assert fac["compliance_status"] == "DEVIATION"
    assert fac["open_exceedance_count"] == 1


def test_stack_test_failure_opens_exceedance_with_magnitude(api):
    """PRD §3.4: "the system opens an exceedance event of type EXCEEDANCE in OPEN
    status on that source, with its magnitude_pct set to the measured rate minus
    the maximum rate, divided by the maximum rate, multiplied by 100, rounded
    half-up to two decimal places".

    Design: Difficulty/transitive_cascade/stack_test_failed_cascades_to_facility_deviation
    """
    facility, source = setup_facility_with_source(
        "Foxtrot Exc Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    st = create_stack_test(source["id"], "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    validate_success(api.conduct_stack_test(st["id"], {"measured_rate_lbs": 60}, INSPECTOR), 200)
    data, meta = validate_paginated(api.list_source_exceedances(source["id"], INSPECTOR))
    assert meta["total_count"] == 1
    event = data[0]
    assert event["event_type"] == "EXCEEDANCE"
    assert event["status"] == "OPEN"
    assert event["magnitude_pct"] == 20.0


# ─── non_linear_state_machine / exceedance_report_branch_fork_late ───

def test_exceedance_report_after_deadline_is_reported_late(api):
    """PRD §3.5: "If instead the logical clock is later than 72 hours past
    detected_at, the event moves OPEN → REPORTED_LATE, and the system opens an
    enforcement action against the facility with origin LATE_EXCEEDANCE,
    action_type NOTICE_OF_VIOLATION, and status INITIATED, driving the facility's
    compliance_status to ENFORCEMENT."

    Design: Difficulty/non_linear_state_machine/exceedance_report_branch_fork_late
    """
    facility, source = setup_facility_with_source(
        "Echo Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    op = make_facility_operator_headers(facility["id"])
    exc = create_exceedance(source["id"], detected_at="2026-03-01T00:00:00Z",
                            event_type="EXCEEDANCE", magnitude_pct=20)
    validate_success(api.set_clock("2026-03-10T00:00:00Z", INSPECTOR), 200)
    result = validate_success(api.report_exceedance(exc["id"], op), 200)
    assert result["status"] == "REPORTED_LATE"
    fac = validate_success(api.get_facility(facility["id"], op), 200)
    assert fac["compliance_status"] == "ENFORCEMENT"


def test_late_report_spawns_late_exceedance_enforcement(api):
    """PRD §3.5: "the system opens an enforcement action against the facility with
    origin LATE_EXCEEDANCE, action_type NOTICE_OF_VIOLATION, and status INITIATED".

    Design: Difficulty/non_linear_state_machine/exceedance_report_branch_fork_late
    """
    facility, source = setup_facility_with_source(
        "Echo NOV Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    op = make_facility_operator_headers(facility["id"])
    exc = create_exceedance(source["id"], detected_at="2026-03-01T00:00:00Z",
                            event_type="EXCEEDANCE", magnitude_pct=20)
    validate_success(api.set_clock("2026-03-10T00:00:00Z", INSPECTOR), 200)
    validate_success(api.report_exceedance(exc["id"], op), 200)
    data, meta = validate_paginated(api.list_facility_enforcement_actions(facility["id"], ENFORCER))
    assert meta["total_count"] == 1
    action = data[0]
    assert action["origin"] == "LATE_EXCEEDANCE"
    assert action["action_type"] == "NOTICE_OF_VIOLATION"
    assert action["status"] == "INITIATED"


# ─── boundary_precision_check / cem_exceedance_strict_greater_than_boundary ───

def test_cem_equal_to_limit_is_not_exceedance(api):
    """PRD §3.4: "Accepting a block computes is_exceedance as true if and only if
    the block's avg_concentration_ppm is strictly greater than the source's
    permit_limit_ppm — equality is not an exceedance".

    Design: Difficulty/boundary_precision_check/cem_exceedance_strict_greater_than_boundary
    """
    facility, source = setup_facility_with_source(
        "Kilo Co", pollutant="SO2", max_hourly_rate_lbs=50, permit_limit_ppm=100)
    res = api.create_cem_data(source["id"], create_cem_data_payload(
        "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", 100), INSPECTOR)
    block = validate_success(res, 201)
    assert block["is_exceedance"] is False


def test_cem_above_limit_is_exceedance(api):
    """PRD §3.4: "Accepting a block computes is_exceedance as true if and only if
    the block's avg_concentration_ppm is strictly greater than the source's
    permit_limit_ppm — equality is not an exceedance".

    Design: Difficulty/boundary_precision_check/cem_exceedance_strict_greater_than_boundary
    """
    facility, source = setup_facility_with_source(
        "Kilo Over Co", pollutant="SO2", max_hourly_rate_lbs=50, permit_limit_ppm=100)
    res = api.create_cem_data(source["id"], create_cem_data_payload(
        "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", 101), INSPECTOR)
    block = validate_success(res, 201)
    assert block["is_exceedance"] is True


# ─── resource_temporal_overlap / stack_test_within_seven_day_buffer_rejected ───

def test_stack_test_within_buffer_rejected(api):
    """PRD §3.4: "The proposed window must not overlap, and must be at least 7 days
    apart from, any other stack test on the same source, treating the windows as
    closed intervals with a seven-day buffer between them; a conflict is rejected
    with ERR_STACK_TEST_CONFLICT".

    Design: Difficulty/resource_temporal_overlap/stack_test_within_seven_day_buffer_rejected
    """
    facility, source = setup_facility_with_source(
        "November Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    create_stack_test(source["id"], "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    res = api.create_stack_test({
        "source_id": source["id"],
        "scheduled_start": "2026-03-05T00:00:00Z",
        "scheduled_end": "2026-03-06T00:00:00Z",
    }, INSPECTOR)
    validate_error(res, "ERR_STACK_TEST_CONFLICT")


def test_stack_test_well_beyond_buffer_accepted(api):
    """PRD §3.4: "The proposed window must not overlap, and must be at least 7 days
    apart from, any other stack test on the same source, treating the windows as
    closed intervals with a seven-day buffer between them".

    Design: Difficulty/resource_temporal_overlap/stack_test_within_seven_day_buffer_rejected
    """
    facility, source = setup_facility_with_source(
        "November Far Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    create_stack_test(source["id"], "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    res = api.create_stack_test({
        "source_id": source["id"],
        "scheduled_start": "2026-03-20T00:00:00Z",
        "scheduled_end": "2026-03-21T00:00:00Z",
    }, INSPECTOR)
    st2 = validate_success(res, 201)
    assert st2["status"] == "SCHEDULED"


# ─── state_machines corner ───

def test_stack_test_pass_sets_monitoring_stack_tested(api):
    """PRD §3.4: "if the measured rate is less than or equal to the source's
    max_hourly_rate_lbs, the test moves CONDUCTED → PASSED and the source's
    monitoring_status becomes STACK_TESTED."

    Design: Corner/state_machines/stack_test_conduct_passed_sets_monitoring
    """
    facility, source = setup_facility_with_source(
        "Xray Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    st = create_stack_test(source["id"], "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    result = validate_success(api.conduct_stack_test(st["id"], {"measured_rate_lbs": 40}, INSPECTOR), 200)
    assert result["status"] == "PASSED"
    src = validate_success(api.get_source(source["id"], INSPECTOR), 200)
    assert src["monitoring_status"] == "STACK_TESTED"


def test_exceedance_report_on_time_is_reported(api):
    """PRD §3.5: "If the logical clock is at or before 72 hours past detected_at,
    the event moves OPEN → REPORTED, the facility's open_exceedance_count decreases
    by one".

    Design: Corner/state_machines/exceedance_report_on_time_returns_reported
    """
    facility, source = setup_facility_with_source(
        "Whiskey Co", max_hourly_rate_lbs=50, operating_hours_per_year=8760)
    op = make_facility_operator_headers(facility["id"])
    exc = create_exceedance(source["id"], detected_at="2026-03-01T00:00:00Z",
                            event_type="EXCEEDANCE", magnitude_pct=5)
    result = validate_success(api.report_exceedance(exc["id"], op), 200)
    assert result["status"] == "REPORTED"
