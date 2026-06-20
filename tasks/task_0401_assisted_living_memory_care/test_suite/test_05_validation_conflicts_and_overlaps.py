"""Validation-priority conflicts and capacity-1 / period-bucket resource overlaps.

The admit state-vs-license conflict is pinned by the §3.11 priority ladder (state check
precedes business constraints). The bed-vs-wing conflict sits at the same intra-tier level
with no PRD precedence between the two business errors, so it is asserted with
validate_error_is_one_of per the error-precedence rule.

Citations are verbatim from PRD.md §3.5, §3.8, §3.11.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of, get_success_data,
    create_facility, create_unit, create_resident,
    create_resident_with_finalized_assessment, setup_active_agreement,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
CLINICAL = TEST_USERS["clinical_director_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
STAFF = TEST_USERS["staff_headers"]


class TestAdmitStateVsLicenseConflict:
    """A PROSPECT resident at a SUSPENDED facility violates both the state precondition and
    the license constraint; the §3.11 ladder places the state check first."""

    def test_prospect_at_suspended_facility_reports_invalid_state(self, api):
        """PRD §3.11: "fifth, that the target resource is in a state from which the requested
        transition is defined (`ERR_INVALID_STATE`)"
        PRD §3.11: "and only then the operation-specific business constraints described above"
        PRD §3.5: "an attempt from any other resident state is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/admit_state_vs_license_safety_conflict
        """
        fac = create_facility(care_point_rate_cents=2000, creator=COMPLIANCE)
        validate_success(
            api.license_action(fac["id"], {"action": "SUSPEND", "expected_facility_version": fac["version"]}, COMPLIANCE), 200,
        )
        # Resident never assessed -> still PROSPECT; facility SUSPENDED. Both apply on admit.
        res = create_resident(fac["id"], full_name="Pat Prospect", date_of_birth="1944-10-10")
        resp = api.admit_resident(res["id"], REGISTRAR)
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_suspension_itself_succeeds_first(self, api):
        """PRD §2.9: "suspending it advances either `ACTIVE` or `CONDITIONAL` to `SUSPENDED`"

        Design: Difficulty/priority_pair_validation_conflict/admit_state_vs_license_safety_conflict
        """
        fac = create_facility(care_point_rate_cents=2000, creator=COMPLIANCE)
        suspended = validate_success(
            api.license_action(fac["id"], {"action": "SUSPEND", "expected_facility_version": fac["version"]}, COMPLIANCE), 200,
        )
        assert suspended["license_status"] == "SUSPENDED"


class TestActivateBedVsWingConflict:
    """A MEMORY_CARE resident bound to an already-RESERVED ASSISTED_LIVING unit violates both
    the bed-availability and the wing-match rules; PRD does not pin which error wins."""

    def test_unavailable_and_wing_mismatch_reports_one_of_two(self, api):
        """PRD §3.5: "The bound unit must be `AVAILABLE` at activation time; if it is not, the
        activation is rejected with `ERR_BED_NOT_AVAILABLE`. The bed's wing must match the
        resident's care wing: a resident whose `current_care_level` is `MEMORY_CARE` may only be
        bound to a unit whose `wing` is `MEMORY_CARE`, and a violation is rejected with
        `ERR_WING_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/activate_bed_temporal_vs_wing_safety_conflict
        """
        fac = create_facility(care_point_rate_cents=2000)
        unit = create_unit(fac["id"], wing="ASSISTED_LIVING", monthly_base_rent_cents=400000)
        # Resident A reserves the only unit.
        resa = create_resident(fac["id"], full_name="Res A", date_of_birth="1936-01-01")
        agra = get_success_data(api.create_move_in_agreement(
            {"resident_id": resa["id"], "unit_id": unit["id"], "move_in_date": "2026-05-01", "community_fee_cents": 0},
            REGISTRAR))
        validate_success(
            api.activate_move_in_agreement(agra["id"], {"expected_unit_version": unit["version"]}, REGISTRAR), 200,
        )
        # Resident B is MEMORY_CARE (cognition 8) and bound to the same ASSISTED_LIVING unit.
        resb = create_resident(fac["id"], full_name="Res B Memory", date_of_birth="1935-02-02")
        asmtb = get_success_data(api.create_assessment(
            {"resident_id": resb["id"], "adl_bathing": 1, "adl_dressing": 1, "adl_toileting": 1,
             "adl_transferring": 1, "adl_eating": 1, "cognition_score": 8, "behavior_flags": 0}, CLINICAL))
        validate_success(
            api.finalize_assessment(asmtb["id"], {"expected_resident_version": resb["version"]}, CLINICAL), 200,
        )
        agrb = get_success_data(api.create_move_in_agreement(
            {"resident_id": resb["id"], "unit_id": unit["id"], "move_in_date": "2026-05-01", "community_fee_cents": 0},
            REGISTRAR))
        unit_now = validate_success(api.get_unit(unit["id"], STAFF), 200)
        resp = api.activate_move_in_agreement(agrb["id"], {"expected_unit_version": unit_now["version"]}, REGISTRAR)
        # Both business errors are valid; PRD pins no precedence between them.
        validate_error_is_one_of(resp, ["ERR_BED_NOT_AVAILABLE", "ERR_WING_MISMATCH"])

    def test_memory_care_resident_into_available_assisted_living_wing_mismatch(self, api):
        """PRD §3.5: "The bed's wing must match the resident's care wing: a resident whose
        `current_care_level` is `MEMORY_CARE` may only be bound to a unit whose `wing` is
        `MEMORY_CARE`, and a violation is rejected with `ERR_WING_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/activate_bed_temporal_vs_wing_safety_conflict
        """
        # Wing rule in isolation: the unit IS AVAILABLE, so only the wing-match leg can fail.
        fac = create_facility(care_point_rate_cents=2000)
        unit = create_unit(fac["id"], wing="ASSISTED_LIVING", monthly_base_rent_cents=400000)
        res = create_resident(fac["id"], full_name="Memory Mae", date_of_birth="1934-03-03")
        asmt = get_success_data(api.create_assessment(
            {"resident_id": res["id"], "adl_bathing": 1, "adl_dressing": 1, "adl_toileting": 1,
             "adl_transferring": 1, "adl_eating": 1, "cognition_score": 8, "behavior_flags": 0}, CLINICAL))
        validate_success(
            api.finalize_assessment(asmt["id"], {"expected_resident_version": res["version"]}, CLINICAL), 200,
        )
        res_now = validate_success(api.get_resident(res["id"], STAFF), 200)
        assert res_now["current_care_level"] == "MEMORY_CARE"
        agr = get_success_data(api.create_move_in_agreement(
            {"resident_id": res["id"], "unit_id": unit["id"], "move_in_date": "2026-05-01", "community_fee_cents": 0},
            REGISTRAR))
        resp = api.activate_move_in_agreement(agr["id"], {"expected_unit_version": unit["version"]}, REGISTRAR)
        validate_error(resp, "ERR_WING_MISMATCH", expected_status=409)


class TestBedSingleOccupancyOverlap:
    """A unit is a capacity-1 hold: once RESERVED it cannot be reserved again."""

    def test_second_activate_on_reserved_unit_rejected(self, api):
        """PRD §3.5: "The bound unit must be `AVAILABLE` at activation time; if it is not, the
        activation is rejected with `ERR_BED_NOT_AVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/bed_single_occupancy_overlap_capacity_one
        """
        fac = create_facility(care_point_rate_cents=2000)
        unit = create_unit(fac["id"], wing="ASSISTED_LIVING", monthly_base_rent_cents=400000)
        resa = create_resident(fac["id"], full_name="Bed A", date_of_birth="1936-05-05")
        resb = create_resident(fac["id"], full_name="Bed B", date_of_birth="1937-06-06")
        agra = get_success_data(api.create_move_in_agreement(
            {"resident_id": resa["id"], "unit_id": unit["id"], "move_in_date": "2026-07-01", "community_fee_cents": 0},
            REGISTRAR))
        validate_success(
            api.activate_move_in_agreement(agra["id"], {"expected_unit_version": unit["version"]}, REGISTRAR), 200,
        )
        agrb = get_success_data(api.create_move_in_agreement(
            {"resident_id": resb["id"], "unit_id": unit["id"], "move_in_date": "2026-07-01", "community_fee_cents": 0},
            REGISTRAR))
        unit_now = validate_success(api.get_unit(unit["id"], STAFF), 200)
        resp = api.activate_move_in_agreement(agrb["id"], {"expected_unit_version": unit_now["version"]}, REGISTRAR)
        validate_error(resp, "ERR_BED_NOT_AVAILABLE", expected_status=409)

    def test_reserved_unit_still_held_for_first_resident(self, api):
        """PRD §3.1: "The system reserves a unit automatically — advancing
        `AVAILABLE → RESERVED` and stamping the reserving resident onto `current_resident_id` as
        a provisional hold — when a move-in agreement bound to that unit is activated."

        Design: Difficulty/resource_temporal_overlap/bed_single_occupancy_overlap_capacity_one
        """
        fac = create_facility(care_point_rate_cents=2000)
        unit = create_unit(fac["id"], wing="ASSISTED_LIVING", monthly_base_rent_cents=400000)
        resa = create_resident(fac["id"], full_name="Bed A", date_of_birth="1936-05-05")
        agra = get_success_data(api.create_move_in_agreement(
            {"resident_id": resa["id"], "unit_id": unit["id"], "move_in_date": "2026-07-01", "community_fee_cents": 0},
            REGISTRAR))
        validate_success(
            api.activate_move_in_agreement(agra["id"], {"expected_unit_version": unit["version"]}, REGISTRAR), 200,
        )
        unit_now = validate_success(api.get_unit(unit["id"], STAFF), 200)
        assert unit_now["status"] == "RESERVED"
        assert unit_now["current_resident_id"] == resa["id"]


class TestBillingPeriodBucketOverlap:
    """At most one non-VOID statement per (resident, year, month)."""

    def test_duplicate_period_statement_rejected(self, api):
        """PRD §3.8: "At most one non-void statement may exist for a given resident, year, and
        month combination; a duplicate is rejected with `ERR_DUPLICATE_STATEMENT_PERIOD`."

        Design: Difficulty/resource_temporal_overlap/billing_period_month_bucket_overlap
        """
        fac = create_facility(care_point_rate_cents=2000)
        res = create_resident(fac["id"], full_name="Bill Month", date_of_birth="1938-07-07")
        get_success_data(api.create_billing_statement(
            {"resident_id": res["id"], "period_year": 2026, "period_month": 8, "is_first_statement": False}, BILLING))
        resp = api.create_billing_statement(
            {"resident_id": res["id"], "period_year": 2026, "period_month": 8, "is_first_statement": False}, BILLING)
        validate_error(resp, "ERR_DUPLICATE_STATEMENT_PERIOD", expected_status=409)

    def test_distinct_period_statement_allowed(self, api):
        """PRD §3.8: "A `BillingClerk` creates a **BillingStatement** in `DRAFT` status for a
        resident and a billing month."

        Design: Difficulty/resource_temporal_overlap/billing_period_month_bucket_overlap
        """
        fac = create_facility(care_point_rate_cents=2000)
        res = create_resident(fac["id"], full_name="Bill Month", date_of_birth="1938-07-07")
        get_success_data(api.create_billing_statement(
            {"resident_id": res["id"], "period_year": 2026, "period_month": 8, "is_first_statement": False}, BILLING))
        # A different month for the same resident is a different bucket -> allowed.
        second = validate_success(api.create_billing_statement(
            {"resident_id": res["id"], "period_year": 2026, "period_month": 9, "is_first_statement": False}, BILLING), 201)
        assert second["period_month"] == 9
