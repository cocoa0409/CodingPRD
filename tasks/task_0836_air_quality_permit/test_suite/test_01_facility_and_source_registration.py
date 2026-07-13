"""Facility registration, Title V applicability, and source potential-to-emit.

Covers difficulty instances (dual-variant PTE, Title V boundary, PTE
conservation) and the entity/consistency corner claims for facilities & sources.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    create_facility_payload, create_source_payload,
    register_facility, register_source, setup_facility_with_source,
    current_facility_version, make_facility_operator_headers, TEST_USERS,
    assert_facility, assert_source,
)

REVIEWER = TEST_USERS["permit_reviewer_headers"]


# ─── dual_variant_calc / source_pte_uncontrolled_vs_controlled ───

def test_source_pte_uncontrolled_ignores_control_efficiency(api):
    """PRD §3.1: "the source's uncontrolled potential to emit, uncontrolled_pte_tpy,
    is the maximum hourly rate in pounds multiplied by the annual operating hours,
    divided by 2,000 pounds per ton, rounded half-up to three decimal places."
    PRD §3.1: "The controlled figure, controlled_pte_tpy, is the uncontrolled
    potential multiplied by one minus the control_efficiency, again rounded
    half-up to three decimal places".

    Design: Difficulty/dual_variant_calc/source_pte_uncontrolled_vs_controlled
    """
    facility, source = setup_facility_with_source(
        max_hourly_rate_lbs=50, operating_hours_per_year=8760, control_efficiency=0.90)
    assert source["uncontrolled_pte_tpy"] == 219.0
    assert source["controlled_pte_tpy"] == 21.9


def test_source_pte_controlled_scales_with_efficiency(api):
    """PRD §3.1: "The controlled figure, controlled_pte_tpy, is the uncontrolled
    potential multiplied by one minus the control_efficiency, again rounded
    half-up to three decimal places".

    Design: Difficulty/dual_variant_calc/source_pte_uncontrolled_vs_controlled
    """
    facility, source = setup_facility_with_source(
        max_hourly_rate_lbs=50, operating_hours_per_year=8760, control_efficiency=0.50)
    assert source["uncontrolled_pte_tpy"] == 219.0
    assert source["controlled_pte_tpy"] == 109.5


# ─── boundary_precision_check / title_v_pte_threshold_ge_100_boundary ───

def test_title_v_track_at_exactly_100_tpy(api):
    """PRD §3.1: "it is TITLE_V when the potential-to-emit is at least 100 tons
    per year (a value of exactly 100.000 tons per year is Title V)".

    Design: Difficulty/boundary_precision_check/title_v_pte_threshold_ge_100_boundary
    """
    facility = register_facility(name="Juliet Co")
    register_source(facility["id"], source_type="GENERATOR", pollutant="NOX",
                    max_hourly_rate_lbs=200, operating_hours_per_year=1000, control_efficiency=0)
    fac = validate_success(api.get_facility(
        facility["id"], make_facility_operator_headers(facility["id"])), 200)
    assert fac["potential_to_emit_tpy"] == 100.0
    assert fac["permit_track"] == "TITLE_V"


def test_permit_by_rule_track_just_below_100_tpy(api):
    """PRD §3.1: "PERMIT_BY_RULE when the potential-to-emit is greater than zero
    but below 100 tons per year".

    Design: Difficulty/boundary_precision_check/title_v_pte_threshold_ge_100_boundary
    """
    facility = register_facility(name="Juliet Below Co")
    register_source(facility["id"], source_type="GENERATOR", pollutant="NOX",
                    max_hourly_rate_lbs=200, operating_hours_per_year=999, control_efficiency=0)
    fac = validate_success(api.get_facility(
        facility["id"], make_facility_operator_headers(facility["id"])), 200)
    assert fac["potential_to_emit_tpy"] == 99.9
    assert fac["permit_track"] == "PERMIT_BY_RULE"


# ─── compensating_invariant / pte_register_then_shutdown_nets_to_remaining ───

def test_pte_before_shutdown_sums_both_sources(api):
    """PRD §3.1: "recomputes the facility's potential_to_emit_tpy as the sum of
    uncontrolled_pte_tpy over all of the facility's sources whose lifecycle_status
    is not SHUTDOWN, rounded half-up to three decimal places".

    Design: Difficulty/compensating_invariant/pte_register_then_shutdown_nets_to_remaining
    """
    facility = register_facility(name="Quebec Co")
    register_source(facility["id"], source_type="BOILER", pollutant="NOX",
                    max_hourly_rate_lbs=50, operating_hours_per_year=8760, control_efficiency=0)
    register_source(facility["id"], source_type="GENERATOR", pollutant="NOX",
                    max_hourly_rate_lbs=10, operating_hours_per_year=8760, control_efficiency=0)
    fac = validate_success(api.get_facility(
        facility["id"], make_facility_operator_headers(facility["id"])), 200)
    assert fac["potential_to_emit_tpy"] == 262.8


def test_pte_after_shutdown_nets_to_remaining_source(api):
    """PRD §3.2: "shutting down recomputes the facility's potential_to_emit_tpy
    over the remaining non-SHUTDOWN sources — equivalently reducing it by exactly
    the shut-down source's uncontrolled_pte_tpy — and re-derives permit_track."

    Design: Difficulty/compensating_invariant/pte_register_then_shutdown_nets_to_remaining
    """
    facility = register_facility(name="Quebec Net Co")
    op = make_facility_operator_headers(facility["id"])
    src_a = register_source(facility["id"], source_type="BOILER", pollutant="NOX",
                            max_hourly_rate_lbs=50, operating_hours_per_year=8760, control_efficiency=0)
    register_source(facility["id"], source_type="GENERATOR", pollutant="NOX",
                    max_hourly_rate_lbs=10, operating_hours_per_year=8760, control_efficiency=0)
    validate_success(api.permit_source(src_a["id"], REVIEWER), 200)
    shut = validate_success(api.shutdown_source(src_a["id"], op), 200)
    assert shut["lifecycle_status"] == "SHUTDOWN"
    fac = validate_success(api.get_facility(facility["id"], op), 200)
    assert fac["potential_to_emit_tpy"] == 43.8


# ─── entities corner ───

def test_new_facility_has_computed_defaults(api):
    """PRD §3.1: "A freshly registered facility starts with permit_track equal to
    UNPERMITTED, a potential_to_emit_tpy of 0, a compliance_status of COMPLIANT,
    an open_exceedance_count of 0, and a fee_balance_cents of 0."

    Design: Corner/entities/facility_creation_returns_computed_defaults
    """
    res = api.create_facility(create_facility_payload(name="Romeo Co"),
                              make_facility_operator_headers("boot"))
    fac = validate_success(res, 201)
    assert_facility(fac)
    assert fac["permit_track"] == "UNPERMITTED"
    assert fac["compliance_status"] == "COMPLIANT"
    assert fac["potential_to_emit_tpy"] == 0
    assert fac["fee_balance_cents"] == 0


def test_source_control_efficiency_defaults_to_zero(api):
    """PRD §3.4: "the operator also supplies its control_efficiency — the
    fractional removal efficiency of its control device, defaulting to 0 for an
    uncontrolled unit and constrained to be at least 0 and strictly below 1".

    Design: Corner/entities/source_control_efficiency_default_zero_applied
    """
    facility = register_facility(name="Tango Co")
    op = make_facility_operator_headers(facility["id"])
    payload = create_source_payload(
        facility["id"], current_facility_version(facility["id"]),
        source_type="BOILER", pollutant="NOX", max_hourly_rate_lbs=10,
        operating_hours_per_year=8760, permit_limit_ppm=50)
    del payload["control_efficiency"]
    source = validate_success(api.create_source(payload, op), 201)
    assert source["uncontrolled_pte_tpy"] == 43.8
    assert source["controlled_pte_tpy"] == 43.8


def test_get_nonexistent_facility_returns_not_found(api):
    """PRD §2.5: "the system validates the path identifiers left to right and
    rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier in
    the path that does not resolve to an existing resource".

    Design: Corner/entities/facility_get_nonexistent_returns_not_found
    """
    res = api.get_facility(NON_EXISTENT_UUID, REVIEWER)
    validate_error(res, "ERR_NOT_FOUND")


def test_source_missing_required_pollutant_rejected(api):
    """PRD §2.10: "request-body well-formedness — required fields present, enum
    values valid, numbers within range — else ERR_INVALID_REQUEST (400)."

    Design: Corner/entities/source_missing_required_field_returns_invalid_request
    """
    facility = register_facility(name="Uniform Co")
    op = make_facility_operator_headers(facility["id"])
    payload = create_source_payload(
        facility["id"], current_facility_version(facility["id"]),
        source_type="BOILER", max_hourly_rate_lbs=10, operating_hours_per_year=8760,
        permit_limit_ppm=50, control_efficiency=0)
    del payload["pollutant"]
    res = api.create_source(payload, op)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_source_invalid_pollutant_enum_rejected(api):
    """PRD §2.10: "request-body well-formedness — required fields present, enum
    values valid, numbers within range — else ERR_INVALID_REQUEST (400)."

    Design: Corner/entities/source_invalid_enum_returns_invalid_request
    """
    facility = register_facility(name="Victor Co")
    op = make_facility_operator_headers(facility["id"])
    payload = create_source_payload(
        facility["id"], current_facility_version(facility["id"]),
        source_type="BOILER", pollutant="XENON", max_hourly_rate_lbs=10,
        operating_hours_per_year=8760, permit_limit_ppm=50, control_efficiency=0)
    res = api.create_source(payload, op)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── consistency_model corner ───

def test_source_pte_visible_immediately_in_create_response(api):
    """PRD §3.1: "Upon registration, the source's uncontrolled potential to emit,
    uncontrolled_pte_tpy, is the maximum hourly rate in pounds multiplied by the
    annual operating hours, divided by 2,000 pounds per ton, rounded half-up to
    three decimal places."

    Design: Corner/consistency_model/source_pte_visible_immediately_in_create_response
    """
    facility = register_facility(name="Victor2 Co")
    op = make_facility_operator_headers(facility["id"])
    payload = create_source_payload(
        facility["id"], current_facility_version(facility["id"]),
        source_type="BOILER", pollutant="NOX", max_hourly_rate_lbs=50,
        operating_hours_per_year=8760, control_efficiency=0, permit_limit_ppm=100)
    res = api.create_source(payload, op)
    source = validate_success(res, 201)
    assert_source(source)
    assert source["uncontrolled_pte_tpy"] == 219.0
