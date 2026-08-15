"""Packaging waterfall: Pell lookup and proration, the pinned candidate order
and per-fund offer computation, pool exhaustion at the exact boundary, and the
eligibility filters (priority cohort, verification-complete) plus the build
prerequisite (PRD §2.10, §3.3, §3.6)."""
from test_helpers import (
    SSN_NOT_SELECTED_A,
    SSN_NOT_SELECTED_B,
    SSN_SELECTED_A,
    SSN_SELECTED_B,
    SSN_SELECTED_D,
    TEST_USERS,
    ApiErrorId,
    build_package,
    create_package,
    get_package,
    get_package_lines,
    import_isir,
    lines_by_fund,
    register_student,
    setup_open_aid_year,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]

# PELL + SEOG + SUB + UNSUB + INST_GRANT in pinned rank order.
WATERFALL_FUNDS = [
    {"fund_code": "PELL", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 739500, "pool_budget_cents": 0, "packaging_rank": 1,
     "requires_verification_complete": False},
    {"fund_code": "SEOG", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 200000, "pool_budget_cents": 1000000,
     "packaging_rank": 2, "requires_verification_complete": False},
    {"fund_code": "SUB", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 350000, "pool_budget_cents": 0, "packaging_rank": 3,
     "requires_verification_complete": False},
    {"fund_code": "UNSUB", "category": "FEDERAL_TITLE_IV", "need_based": False,
     "annual_cap_cents": 200000, "pool_budget_cents": 0, "packaging_rank": 4,
     "requires_verification_complete": False},
    {"fund_code": "INST_GRANT", "category": "INSTITUTIONAL", "need_based": True,
     "annual_cap_cents": 500000, "pool_budget_cents": 800000,
     "packaging_rank": 5, "requires_verification_complete": False},
]

SEOG_ONLY = [
    {"fund_code": "SEOG", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 200000, "pool_budget_cents": 350000,
     "packaging_rank": 1, "requires_verification_complete": False},
]

PELL_PLUS_GATED_SEOG = [
    {"fund_code": "PELL", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 739500, "pool_budget_cents": 0, "packaging_rank": 1,
     "requires_verification_complete": False},
    {"fund_code": "SEOG", "category": "FEDERAL_TITLE_IV", "need_based": True,
     "annual_cap_cents": 200000, "pool_budget_cents": 1000000,
     "packaging_rank": 2, "requires_verification_complete": True},
]

PRIORITY_ONLY_FUND = [
    {"fund_code": "INST_AID", "category": "INSTITUTIONAL", "need_based": True,
     "annual_cap_cents": 100000, "pool_budget_cents": 1000000,
     "priority_cohort_only": True, "packaging_rank": 1,
     "requires_verification_complete": False},
]


def _efc_zero_student(ssn, name, email, enrollment="FULL_TIME"):
    return register_student(ssn, full_name=name, email=email,
                            enrollment_status=enrollment)


def _efc_zero_isir(student_id, aid_year_id, **overrides):
    return import_isir(student_id, aid_year_id,
                       agi_cents=2000000, household_size=4,
                       number_in_college=1, **overrides)


def _build_lines_for(student_id, aid_year_id):
    package = create_package(student_id, aid_year_id)
    build_package(package["id"])
    return package["id"], get_package_lines(package["id"])


class TestPellProrationVariants:
    def test_pell_full_time_pays_full_row(self, api):
        """PRD §3.6: "Enrollment proration then applies: `FULL_TIME` pays one hundred percent, `THREE_QUARTER` pays seventy-five percent, `HALF_TIME` pays fifty percent, and `LESS_THAN_HALF` pays zero — the Pell offer is the floor of the row's `award_cents` multiplied by the proration percentage and divided by one hundred."
        PRD §3.6: "One AwardLine is created per fund whose final offer is greater than zero, with `offered_cents` set to that offer, `accepted_cents` and `disbursed_cents` starting at zero, status `OFFERED`, and a `sequence_number` assigned in evaluation order starting at 1."

        Design: Difficulty/dual_variant_calc/pell_variant_proration_full_vs_half
        """
        env = setup_open_aid_year()
        student = _efc_zero_student(SSN_NOT_SELECTED_A, "Full Timer",
                                    "full@example.edu")
        _efc_zero_isir(student["id"], env["aid_year"]["id"])
        _pkg_id, lines = _build_lines_for(student["id"], env["aid_year"]["id"])

        # EFC 0 lands in schedule row [0, 150000] -> 739_500 at 100% proration.
        assert len(lines) == 1
        assert lines[0]["offered_cents"] == 739500
        assert lines[0]["sequence_number"] == 1
        assert lines[0]["status"] == "OFFERED"
        assert lines[0]["accepted_cents"] == 0
        assert lines[0]["disbursed_cents"] == 0

    def test_pell_half_time_pays_half_row(self, api):
        """PRD §3.6: "Enrollment proration then applies: `FULL_TIME` pays one hundred percent, `THREE_QUARTER` pays seventy-five percent, `HALF_TIME` pays fifty percent, and `LESS_THAN_HALF` pays zero — the Pell offer is the floor of the row's `award_cents` multiplied by the proration percentage and divided by one hundred."

        Design: Difficulty/dual_variant_calc/pell_variant_proration_full_vs_half
        """
        env = setup_open_aid_year()
        student = _efc_zero_student(SSN_NOT_SELECTED_B, "Half Timer",
                                    "half@example.edu", enrollment="HALF_TIME")
        _efc_zero_isir(student["id"], env["aid_year"]["id"])
        _pkg_id, lines = _build_lines_for(student["id"], env["aid_year"]["id"])

        # floor(739_500 * 50 / 100) = 369_750.
        assert len(lines) == 1
        assert lines[0]["offered_cents"] == 369750
        assert lines[0]["sequence_number"] == 1


class TestWaterfallPinnedOrder:
    def _build_waterfall_package(self, api):
        env = setup_open_aid_year(fund_specs=WATERFALL_FUNDS)
        student = _efc_zero_student(SSN_NOT_SELECTED_A, "Pack Order",
                                    "p@example.edu")
        _efc_zero_isir(student["id"], env["aid_year"]["id"])
        package = create_package(student["id"], env["aid_year"]["id"])
        package = build_package(package["id"])
        lines = get_package_lines(package["id"])
        return env, package, lines_by_fund(lines, env["funds"])

    def test_lines_created_in_rank_order_with_pinned_amounts(self, api):
        """PRD §3.6: "The funds considered are the aid year's `ACTIVE` FundTypes, taken in ascending `packaging_rank` with ties broken by `fund_code` ascending."
        PRD §3.6: "The annual `SUB` cap is 350,000 cents at grade level one, 450,000 at level two, and 550,000 at levels three, four, and five — and the `SUB` caps for `INDEPENDENT` students are identical to those for `DEPENDENT` students at every level. The `UNSUB` cap for a `DEPENDENT` student is a flat 200,000 cents at every level from one through five, while an `INDEPENDENT` student may receive 600,000 cents at levels one and two and 700,000 at levels three, four, and five. `SUB` is need-based: its offer is the smaller of its cap and the running remaining need. `UNSUB` is not: its offer is the smaller of its cap and the running remaining cost-of-attendance gap."

        Design: Difficulty/combinatorial_formula/packaging_waterfall_circular_order_mode_c
        """
        env, package, by_code = self._build_waterfall_package(api)
        expected = {"PELL": 739500, "SEOG": 200000, "SUB": 350000,
                    "UNSUB": 200000, "INST_GRANT": 500000}
        assert set(by_code.keys()) == set(expected.keys())
        for position, code in enumerate(
                ["PELL", "SEOG", "SUB", "UNSUB", "INST_GRANT"], start=1):
            line = by_code[code]
            assert line["offered_cents"] == expected[code], (
                f"{code} offer: expected {expected[code]}, "
                f"got {line['offered_cents']}")
            assert line["sequence_number"] == position, (
                f"{code} must be evaluated at position {position}")

    def test_package_aggregates_after_waterfall(self, api):
        """PRD §3.6: "`efc_used_cents` is the current ISIR's `efc_official_cents` minus the sum of `applied_efc_delta_cents` over those approved cases, floored at zero. `need_cents` is the cost snapshot minus the EFC snapshot, floored at zero, and is recomputed whenever the package is rebuilt."
        PRD §3.6: "The package's `gift_aid_cents` accumulates offers of funds that are `need_based` and not loan funds — that is, whose `fund_code` is none of `SUB`, `UNSUB`, or `PLUS`."

        Design: Difficulty/combinatorial_formula/packaging_waterfall_circular_order_mode_c
        """
        env, package, by_code = self._build_waterfall_package(api)
        assert package["coa_used_cents"] == 2400000
        assert package["efc_used_cents"] == 0
        assert package["need_cents"] == 2400000
        # 739_500 + 200_000 + 350_000 + 200_000 + 500_000.
        assert package["total_offered_cents"] == 1989500
        # Gift aid excludes the SUB/UNSUB loan funds: 739_500 + 200_000 + 500_000.
        assert package["gift_aid_cents"] == 1439500


class TestPellLookupBoundaries:
    def test_efc_at_inclusive_row_top_selects_higher_row(self, api):
        """PRD §3.6: "The Pell lookup inside step three reads the aid year's `pell_schedule` and finds the single row whose inclusive boundaries satisfy `efc_min` at or below the package's `efc_used_cents` and `efc_max` at or above it; that row's `award_cents` is the pre-proration offer."
        PRD §3.3: "with each tier's product rounded half-up to whole cents before the tiers are summed, that rounding order being pinned."

        Design: Difficulty/combinatorial_formula/pell_lookup_boundary_rows_mode_b
        """
        env = setup_open_aid_year()
        student = _efc_zero_student(SSN_NOT_SELECTED_A, "Boundary Low",
                                    "l@example.edu")
        isir = import_isir(student["id"], env["aid_year"]["id"],
                           agi_cents=3014285, household_size=4,
                           number_in_college=1)
        # AI = 614_285; tier-2 product 114_285 * 0.35 = 39_999.75 -> 40_000;
        # EFC = 150_000, the inclusive top of row [0, 150000].
        assert isir["efc_provisional_cents"] == 150000
        _pkg_id, lines = _build_lines_for(student["id"], env["aid_year"]["id"])
        assert len(lines) == 1
        assert lines[0]["offered_cents"] == 739500

    def test_efc_one_cent_over_row_top_selects_next_row(self, api):
        """PRD §3.6: "The Pell lookup inside step three reads the aid year's `pell_schedule` and finds the single row whose inclusive boundaries satisfy `efc_min` at or below the package's `efc_used_cents` and `efc_max` at or above it; that row's `award_cents` is the pre-proration offer."
        PRD §3.3: "with each tier's product rounded half-up to whole cents before the tiers are summed, that rounding order being pinned."

        Design: Difficulty/combinatorial_formula/pell_lookup_boundary_rows_mode_b
        """
        env = setup_open_aid_year()
        student = _efc_zero_student(SSN_NOT_SELECTED_B, "Boundary High",
                                    "m@example.edu")
        isir = import_isir(student["id"], env["aid_year"]["id"],
                           agi_cents=3014288, household_size=4,
                           number_in_college=1)
        # AI = 614_288; tier-2 product 114_288 * 0.35 = 40_000.80 -> 40_001;
        # EFC = 150_001 -> row [150001, 300000].
        assert isir["efc_provisional_cents"] == 150001
        _pkg_id, lines = _build_lines_for(student["id"], env["aid_year"]["id"])
        assert len(lines) == 1
        assert lines[0]["offered_cents"] == 500000


class TestFundPoolExhaustionBoundary:
    def _build_three_students(self, api):
        env = setup_open_aid_year(fund_specs=SEOG_ONLY)
        s1 = _efc_zero_student(SSN_NOT_SELECTED_A, "First", "e1@example.edu")
        s2 = _efc_zero_student(SSN_NOT_SELECTED_B, "Second", "e2@example.edu")
        s3 = register_student(SSN_SELECTED_D, full_name="Third",
                              email="e3@example.edu")
        for s in (s1, s2):
            _efc_zero_isir(s["id"], env["aid_year"]["id"])
        _efc_zero_isir(s3["id"], env["aid_year"]["id"], cps_selection_flag=True)
        p1 = create_package(s1["id"], env["aid_year"]["id"])
        build_package(p1["id"])
        p2 = create_package(s2["id"], env["aid_year"]["id"])
        build_package(p2["id"])
        p3 = create_package(s3["id"], env["aid_year"]["id"])
        return env, p1, p2, p3

    def test_pool_at_exactly_budget_auto_exhausts_fund(self, api):
        """PRD §2.10: "A non-PELL fund whose `pool_reserved_cents` reaches or exceeds its `pool_budget_cents` is automatically transitioned from `ACTIVE` to `EXHAUSTED` after the AwardLine mutation that caused it, with its `version` incremented; should a later mutation reduce `pool_reserved_cents` below `pool_budget_cents`, the fund automatically returns from `EXHAUSTED` to `ACTIVE`."

        Design: Difficulty/boundary_precision_check/fund_pool_exhaustion_exact_boundary
        """
        env, p1, p2, p3 = self._build_three_students(api)
        fund = validate_success(api.get_fund_type(env["funds"]["SEOG"]["id"],
                                                  OFFICER))
        # 200_000 (first) + 150_000 (second, capped by the pool check) = the
        # 350_000 budget exactly; the >= comparison fires EXHAUSTED.
        assert fund["pool_reserved_cents"] == 350000
        assert fund["status"] == "EXHAUSTED"

    def test_exactly_exhausted_pool_yields_no_line_for_next_student(self, api):
        """PRD §3.6: "Fourth, the pool check for every fund except `PELL`: the offer is capped at `pool_budget_cents` minus `pool_reserved_cents`, and the fund is skipped entirely when that leaves zero or less; `PELL` skips the pool check as an entitlement."
        PRD §3.6: "A fund whose offer is zero produces no line at all."

        Design: Difficulty/boundary_precision_check/fund_pool_exhaustion_exact_boundary
        """
        env, p1, p2, p3 = self._build_three_students(api)
        package = build_package(p3["id"])
        lines = get_package_lines(p3["id"])
        assert lines == []
        assert package["total_offered_cents"] == 0


class TestWaterfallEligibilityFilters:
    def test_verification_gated_fund_skipped_while_case_open(self, api):
        """PRD §3.6: "Second, a fund with `requires_verification_complete` true is skipped unless the student has no verification case at all (a `NOT_SELECTED` outcome) or the case is `COMPLETED_SATISFIED` or `WAIVED`."

        Design: Corner/calculations/packaging_skips_verification_gated_funds
        """
        env = setup_open_aid_year(fund_specs=PELL_PLUS_GATED_SEOG)
        student = register_student(SSN_SELECTED_A, full_name="Gated Fund",
                                   email="gf@example.edu")
        _efc_zero_isir(student["id"], env["aid_year"]["id"])
        # The deterministic selection flagged this record, so a case exists in
        # DOCUMENTS_REQUESTED and the gated SEOG fund must be skipped.
        _pkg_id, lines = _build_lines_for(student["id"], env["aid_year"]["id"])
        by_code = lines_by_fund(lines, env["funds"])
        assert set(by_code.keys()) == {"PELL"}
        assert by_code["PELL"]["offered_cents"] == 739500
        assert get_package(_pkg_id)["total_offered_cents"] == 739500

    def test_priority_cohort_only_fund_filtered_by_cohort(self, api):
        """PRD §3.6: "First, a fund with `priority_cohort_only` true is skipped unless the current ISIR's `cohort` is `PRIORITY`."
        PRD §3.3: "The `cohort` is set to `PRIORITY` when `received_at` is on or before the aid year's `priority_deadline` and to `STANDARD` otherwise; it is fixed at import and never recomputed even if the deadline later changes."

        Design: Corner/calculations/priority_cohort_only_fund_filter
        """
        env = setup_open_aid_year(fund_specs=PRIORITY_ONLY_FUND)
        priority_student = register_student(SSN_SELECTED_B,
                                            full_name="Priority Kid",
                                            email="pr@example.edu")
        standard_student = register_student(SSN_NOT_SELECTED_B,
                                            full_name="Standard Kid",
                                            email="st@example.edu")
        _efc_zero_isir(priority_student["id"], env["aid_year"]["id"],
                       received_at="2026-02-01T00:00:00Z")
        _efc_zero_isir(standard_student["id"], env["aid_year"]["id"],
                       received_at="2026-04-01T00:00:00Z")

        pkg_pr, lines_pr = _build_lines_for(priority_student["id"],
                                            env["aid_year"]["id"])
        pkg_st, lines_st = _build_lines_for(standard_student["id"],
                                            env["aid_year"]["id"])

        assert len(lines_pr) == 1
        assert lines_pr[0]["offered_cents"] == 100000
        assert get_package(pkg_pr)["total_offered_cents"] == 100000
        assert lines_st == []
        assert get_package(pkg_st)["total_offered_cents"] == 0


class TestBuildPrerequisite:
    def test_build_without_current_isir_rejected(self, api):
        """PRD §3.6: "Building the package — `DRAFT` → `PACKAGED` — is permitted only while the aid year is `OPEN` (otherwise `ERR_PARENT_STATE_BLOCKS`) and only when a current ISIR record exists for the student and year (otherwise `ERR_PREREQUISITE_MISSING`)."
        PRD §2.7 (rung 13): "a packaging build requires a current ISIR record for the student and aid year, an ISIR import requires the aid year to be `OPEN`, and fund activation requires the aid year to be `DRAFT` or `OPEN` — otherwise `ERR_PREREQUISITE_MISSING` (422)."

        Design: Corner/validations/build_without_current_isir_prerequisite
        """
        env = setup_open_aid_year()
        student = register_student(SSN_SELECTED_B, full_name="No Isir",
                                   email="ni@example.edu")
        package = create_package(student["id"], env["aid_year"]["id"])
        resp = api.build_award_package(package["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_MISSING)
