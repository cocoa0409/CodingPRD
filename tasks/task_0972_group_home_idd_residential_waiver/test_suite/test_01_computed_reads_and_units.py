"""Computed reads with dual variants: census, EVV units, staffing (PRD 3.4, 3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_active_isp,
    create_and_verify_visit,
    create_authorization_payload,
    create_bed_assignment_payload,
    create_evv_visit_payload,
    create_home_payload,
    create_individual_payload,
    create_isp_payload,
    create_shift_payload,
    get_success_data,
    make_billing_headers,
    make_case_manager_headers,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency,
    setup_agency_with_clinical_staff,
    setup_agency_with_core_staff,
    setup_billable_pipeline,
    setup_claim_for_individual,
    setup_enrolled_individual,
    setup_home,
    setup_staff,
    admit_resident,
    api_client,
    validate_success,
)

ADMIN = TEST_USERS["agency_admin_headers"]
ANY = TEST_USERS["any_headers"]
BILL1 = TEST_USERS["billing_headers"]


class TestCensusCurrentVsProjected:
    """Census read: current variant vs projected variant (PRD 3.4)."""

    def test_current_census_counts_only_active_assignments(self, api):
        """PRD 3.4: "The current census on a given date is the count of `ACTIVE`
        bed assignments at the home whose `move_in_date` is on or before the date
        and whose `move_out_date` is either absent or strictly after the date".

        Design: Difficulty/dual_variant_calc/census_current_vs_projected_diverge
        """
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=3)
        ind1 = setup_enrolled_individual(agency, cm, q, legal_name="Ind One")
        ind2 = setup_enrolled_individual(agency, cm, q, legal_name="Ind Two")
        set_clock("2026-06-01T00:00:00Z")
        admit_resident(home, ind1, cm, q, bed_label="R1-A", move_in_date="2026-06-01")
        # PENDING admission inside the 14-day projection window.
        get_success_data(api.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1-B", ind2["id"], move_in_date="2026-06-10"),
            make_case_manager_headers(cm["id"]),
        ))

        data = validate_success(api.get_home_census(home["id"], ANY, "2026-06-01"))
        assert data["current_census"] == 1, (
            f"current census counts only ACTIVE, got {data['current_census']}"
        )

    def test_projected_census_adds_pending_within_projection_window(self, api):
        """PRD 3.4: "The projected census adds to the current census the count of
        `PENDING` bed assignments at the home whose `move_in_date` is on or before
        the date plus fourteen days".

        Design: Difficulty/dual_variant_calc/census_current_vs_projected_diverge
        """
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=3)
        ind1 = setup_enrolled_individual(agency, cm, q, legal_name="Ind One")
        ind2 = setup_enrolled_individual(agency, cm, q, legal_name="Ind Two")
        set_clock("2026-06-01T00:00:00Z")
        admit_resident(home, ind1, cm, q, bed_label="R1-A", move_in_date="2026-06-01")
        get_success_data(api.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1-B", ind2["id"], move_in_date="2026-06-10"),
            make_case_manager_headers(cm["id"]),
        ))

        data = validate_success(api.get_home_census(home["id"], ANY, "2026-06-01"))
        assert data["projected_census"] == 2, (
            f"projected census adds PENDING inside +14d, got {data['projected_census']}"
        )
        assert data["current_census"] != data["projected_census"]


class TestEvvProvisionalVsFinalUnits:
    """EVV provisional vs final unit variants (PRD 3.8)."""

    def test_provisional_units_round_half_up_from_raw_timestamps(self, api):
        """PRD 3.8: "When the authorization's `unit_type` is `FIFTEEN_MIN`,
        `provisional_units` is the duration divided by 15, rounded half-up to the
        nearest integer, with a floor of one unit".

        Design: Difficulty/dual_variant_calc/evv_provisional_vs_final_units_diverge
        """
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        visit = get_success_data(api.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                service_date="2026-06-02",
                check_in_at="2026-06-02T09:00:00Z",
                check_out_at="2026-06-02T10:40:00Z",
            ),
            ctx["d1_headers"],
        ))
        # 100 minutes / 15 = 6.67 -> round half-up to 7.
        assert visit["provisional_units"] == 7, (
            f"expected 7 provisional units, got {visit['provisional_units']}"
        )

    def test_final_units_from_adjusted_minutes_differ_from_provisional(self, api):
        """PRD 3.8: "The `adjusted_minutes` must be a positive multiple of 15
        (otherwise `ERR_INVALID_REQUEST`); the final units are then exactly
        `adjusted_minutes` divided by 15, with no further rounding."

        Design: Difficulty/dual_variant_calc/evv_provisional_vs_final_units_diverge
        """
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        visit = get_success_data(api.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                service_date="2026-06-02",
                check_in_at="2026-06-02T09:00:00Z",
                check_out_at="2026-06-02T10:40:00Z",
            ),
            ctx["d1_headers"],
        ))
        assert visit["provisional_units"] == 7
        get_success_data(api.flag_evv_exception(visit["id"], ctx["q_headers"]))
        resolved = get_success_data(api.resolve_evv_exception(
            visit["id"],
            {"adjusted_minutes": 75, "resolution_note": "EVV device malfunction"},
            ctx["q_headers"],
        ))
        assert resolved["final_units"] == 5, (
            f"final = 75/15 = 5, got {resolved['final_units']}"
        )
        assert resolved["verification_status"] == "VERIFIED"
        auth = get_success_data(api.get_authorization(ctx["auth"]["id"], ANY))
        assert auth["consumed_units"] == 5
        assert auth["remaining_units"] == 19


class TestStaffingScheduledVsActual:
    """Staffing-check scheduled vs actual variants (PRD 3.4)."""

    def _setup_two_wheelchair_residents_one_shift(self, api):
        base = setup_agency_with_clinical_staff()
        agency, cm, q, d1 = base["agency"], base["cm"], base["q"], base["d1"]
        home = setup_home(agency, certified_bed_count=4)
        r1 = setup_enrolled_individual(agency, cm, q, legal_name="Res One", mobility_level="WHEELCHAIR")
        r2 = setup_enrolled_individual(agency, cm, q, legal_name="Res Two", mobility_level="WHEELCHAIR")
        set_clock("2026-06-01T00:00:00Z")
        admit_resident(home, r1, cm, q, bed_label="R1")
        admit_resident(home, r2, cm, q, bed_label="R2")
        shift = get_success_data(api.create_shift(
            create_shift_payload(home["id"], d1["id"]),
            ADMIN,
        ))
        return home, shift

    def test_scheduled_variant_counts_scheduled_shifts(self, api):
        """PRD 3.4: "The scheduled DSP count is the number of shift assignments
        at the home on `shift_date` with matching `shift_type` and status in
        `SCHEDULED`, `CONFIRMED`, or `COMPLETED` (cancelled shifts are excluded)."

        Design: Difficulty/dual_variant_calc/staffing_scheduled_vs_actual_variant_diverge
        """
        home, _shift = self._setup_two_wheelchair_residents_one_shift(api)
        data = validate_success(api.get_home_staffing_check(home["id"], ANY, "2026-06-02", "DAY"))
        assert data["weighted_census"] == 4
        assert data["required_dsps"] == 1  # ceil(4/4)
        assert data["scheduled_dsps"] == 1
        assert data["compliant_scheduled"] is True

    def test_actual_variant_counts_verified_evv_attendance_only(self, api):
        """PRD 3.4: "The actual DSP count is the number of distinct
        `staff_member_id` values on EVV visits whose `shift_id` points at one of
        this home's shifts on `shift_date` with matching `shift_type` and whose
        `verification_status` is `VERIFIED`."

        Design: Difficulty/dual_variant_calc/staffing_scheduled_vs_actual_variant_diverge
        """
        home, _shift = self._setup_two_wheelchair_residents_one_shift(api)
        data = validate_success(api.get_home_staffing_check(home["id"], ANY, "2026-06-02", "DAY"))
        assert data["actual_dsps"] == 0, (
            f"no verified EVV attendance yet, got {data['actual_dsps']}"
        )
        assert data["compliant_actual"] is False
        # The two variants provably disagree on identical census data.
        assert data["compliant_scheduled"] != data["compliant_actual"]


class TestStaffingWeightedCeiling:
    """Weighted staffing: multi-input non-linear ceiling (PRD 3.4)."""

    def _setup_four_resident_home(self, api):
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=4)
        residents = [
            setup_enrolled_individual(agency, cm, q, legal_name=n, mobility_level=m)
            for n, m in [
                ("Res WC1", "WHEELCHAIR"), ("Res WC2", "WHEELCHAIR"),
                ("Res AMB", "AMBULATORY"), ("Res AST", "ASSIST"),
            ]
        ]
        set_clock("2026-06-01T00:00:00Z")
        for i, r in enumerate(residents, start=1):
            admit_resident(home, r, cm, q, bed_label=f"B{i}")
        return home

    def test_day_ratio_tier_applies_ceiling(self, api):
        """PRD 3.4: "The required DSP count is the weighted census divided by the
        ratio and rounded up to the next integer". Weight 2+2+1+1 = 6; ratio 4.

        Design: Difficulty/combinatorial_formula/staffing_weighted_ceiling_multi_input
        """
        home = self._setup_four_resident_home(api)
        data = validate_success(api.get_home_staffing_check(home["id"], ANY, "2026-06-02", "DAY"))
        assert data["weighted_census"] == 6
        assert data["required_dsps"] == 2, f"ceil(6/4) = 2, got {data['required_dsps']}"

    def test_night_ratio_tier_changes_result_nonlinearly(self, api):
        """PRD 3.4: "The applicable ratio is the agency's `day_staff_ratio` when
        `shift_type` is `DAY` and the agency's `night_staff_ratio` when
        `shift_type` is `NIGHT`."

        Design: Difficulty/combinatorial_formula/staffing_weighted_ceiling_multi_input
        """
        home = self._setup_four_resident_home(api)
        data = validate_success(api.get_home_staffing_check(home["id"], ANY, "2026-06-02", "NIGHT"))
        assert data["required_dsps"] == 1, f"ceil(6/8) = 1, got {data['required_dsps']}"


class TestPerVisitRoundingThenSum:
    """Claim aggregation pins per-visit rounding before summation (PRD 3.10)."""

    def _setup_two_eight_minute_verified_visits(self, api):
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        create_and_verify_visit(ctx, "2026-06-02T09:00:00Z", "2026-06-02T09:08:00Z")
        create_and_verify_visit(ctx, "2026-06-02T10:00:00Z", "2026-06-02T10:08:00Z")
        return ctx

    def test_claim_total_units_sum_per_visit_rounded_units(self, api):
        """PRD 3.10: "The per-visit rounding order is pinned: units are rounded
        per visit first (during the provisional/final computation), and the
        integer per-visit units are then summed into the claim line".

        Design: Difficulty/combinatorial_formula/per_visit_rounding_then_sum_pinned
        """
        ctx = self._setup_two_eight_minute_verified_visits(api)
        claim = setup_claim_for_individual(ctx)
        # Each 8-minute visit: max(1, round_half_up(8/15)) = 1 unit; 1 + 1 = 2.
        assert claim["total_units"] == 2, (
            f"per-visit-first yields 2 units, got {claim['total_units']}"
        )

    def test_claim_total_amount_uses_integer_unit_sum(self, api):
        """PRD 3.10: "summing raw minutes across visits and then rounding is
        forbidden and would produce different totals." Two 8-minute visits at
        1500 cents/unit: per-visit-first = 2 units = 3000 cents; the forbidden
        order would produce round(16/15) = 1 unit = 1500 cents.

        Design: Difficulty/combinatorial_formula/per_visit_rounding_then_sum_pinned
        """
        ctx = self._setup_two_eight_minute_verified_visits(api)
        claim = setup_claim_for_individual(ctx)
        assert claim["total_amount_cents"] == 3000, (
            f"2 units * 1500 = 3000, got {claim['total_amount_cents']}"
        )
