"""Benefits screening: dual-variant tiering, inclusive tier boundaries, and the
re-screen cycle (PRD §3.7)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    register_client, create_staff_member, open_case,
    create_screening, run_screening, verify_screening,
    create_benefit_screening_payload, staff_headers,
)

ADMIN = TEST_USERS["center_admin_headers"]


def _case_with_manager():
    mgr = create_staff_member()
    client = register_client(household_size=2)
    case = open_case(client, mgr)
    return mgr, client, case


class TestDualVariantProgramSet:
    def test_self_reported_variant_strips_cash_assist(self):
        """PRD §3.7: "Each tier carries a program set: `TIER_A` yields `SNAP`,
        `MEDICAID`, `CASH_ASSIST`, and `ESL_SUBSIDY`; `TIER_B` yields `SNAP` and
        `ESL_SUBSIDY`; `TIER_C` yields `ESL_SUBSIDY` alone; and `TIER_D` yields an
        empty set, which is a valid no-match outcome. The variant then filters the
        set: the self-reported variant strips `CASH_ASSIST` — cash assistance is
        documentation-gated — while the verified variant keeps the full tier set."

        Design: Difficulty/dual_variant_calc/benefits_self_reported_vs_verified_program_set
        """
        mgr, _client, case = _case_with_manager()
        scr = create_screening(case, mgr, stated_income=2820720)
        ran = run_screening(scr, mgr)
        assert ran["status"] == "SCREENED"
        assert ran["variant_used"] == "SELF_REPORTED"
        assert ran["tier"] == "TIER_A"
        assert sorted(ran["eligible_programs"]) == ["ESL_SUBSIDY", "MEDICAID", "SNAP"], \
            "CASH_ASSIST is stripped under the self-reported variant"

    def test_verified_variant_restores_full_tier_set(self):
        """PRD §3.7: "Later, a `CaseManager` attaches document-verified income by
        supplying `documented_annual_income_cents`; this verification leaves the
        screening in `SCREENED` but flips `variant_used` to `VERIFIED` and
        recomputes the trio under the verified variant."
        PRD §3.7: "the self-reported variant strips `CASH_ASSIST` — cash
        assistance is documentation-gated — while the verified variant keeps the
        full tier set."

        Design: Difficulty/dual_variant_calc/benefits_self_reported_vs_verified_program_set
        """
        mgr, _client, case = _case_with_manager()
        scr = create_screening(case, mgr, stated_income=2820720)
        run_screening(scr, mgr)
        verified = verify_screening(scr, mgr, 2820720)
        assert verified["status"] == "SCREENED", "verify is not a status transition"
        assert verified["variant_used"] == "VERIFIED"
        assert verified["tier"] == "TIER_A"
        assert sorted(verified["eligible_programs"]) == [
            "CASH_ASSIST", "ESL_SUBSIDY", "MEDICAID", "SNAP"], \
            "the verified variant keeps the full tier set for identical income"


class TestTierInclusiveBoundary:
    def test_income_at_exactly_138pct_fpl_is_tier_a(self):
        """PRD §3.7: "Tiering works against the federal poverty guideline,
        expressed as annual cents by household size: 1506000 for one person,
        2044000 for two, 2582000 for three, 3120000 for four, 3658000 for five,
        4196000 for six, 4734000 for seven, and 5272000 for eight; households
        larger than eight use the eight-person figure."
        PRD §3.7: "Tier assignment ignores the rounded ratio and instead compares
        integer income cents against floored guideline multiples: `TIER_A` when
        income is no greater than the floored value of 138 percent of the
        guideline".

        Design: Difficulty/boundary_precision_check/benefits_tier_inclusive_boundary_at_138pct_fpl
        """
        mgr, _client, case = _case_with_manager()
        # floor(2044000 * 138 / 100) == 2820720 exactly: the inclusive upper edge.
        scr = create_screening(case, mgr, stated_income=2820720)
        ran = run_screening(scr, mgr)
        assert ran["tier"] == "TIER_A", "income equal to the floored 138% threshold is TIER_A"
        assert ran["income_ratio"] == pytest.approx(1.38, abs=1e-9)

    def test_one_hundred_cents_over_boundary_is_tier_b(self):
        """PRD §3.7: "Tier assignment ignores the rounded ratio and instead
        compares integer income cents against floored guideline multiples:
        `TIER_A` when income is no greater than the floored value of 138 percent
        of the guideline; `TIER_B` when income exceeds that floor but not the
        floored 200 percent; `TIER_C` when income exceeds the floored 200 percent
        but not the floored 300 percent; and `TIER_D` otherwise."
        PRD §3.7: "Each tier carries a program set: `TIER_A` yields `SNAP`,
        `MEDICAID`, `CASH_ASSIST`, and `ESL_SUBSIDY`; `TIER_B` yields `SNAP` and
        `ESL_SUBSIDY`; `TIER_C` yields `ESL_SUBSIDY` alone; and `TIER_D` yields an
        empty set, which is a valid no-match outcome."

        Design: Difficulty/boundary_precision_check/benefits_tier_inclusive_boundary_at_138pct_fpl
        """
        mgr, _client, case = _case_with_manager()
        scr = create_screening(case, mgr, stated_income=2820820)
        ran = run_screening(scr, mgr)
        assert ran["tier"] == "TIER_B", "one hundred cents over the threshold flips the tier"
        assert sorted(ran["eligible_programs"]) == ["ESL_SUBSIDY", "SNAP"]


class TestReopenCycle:
    def test_screening_reopen_cycle_clears_results(self):
        """PRD §3.7: "reopening returns a `SCREENED` screening to `DRAFT`,
        clearing `tier` and `income_ratio` to null and `eligible_programs` to an
        empty array for a fresh pass."
        PRD §3.7: "Running a draft screening moves it to `SCREENED` and evaluates
        the **self-reported** variant".

        Design: Corner/state_machines/screening_reopen_cycle_clears_results
        """
        mgr = create_staff_member()
        client = register_client(household_size=1)
        case = open_case(client, mgr)
        scr = create_screening(case, mgr, stated_income=1000000)
        run_screening(scr, mgr)

        reopened = validate_success(api_client.reopen_benefit_screening(
            scr["id"], staff_headers(mgr)))
        assert reopened["status"] == "DRAFT"
        assert reopened["tier"] is None
        assert reopened["income_ratio"] is None
        assert reopened["eligible_programs"] == []

        rerun = validate_success(api_client.run_benefit_screening(
            scr["id"], staff_headers(mgr)))
        assert rerun["status"] == "SCREENED", "the reopened cycle runs again from DRAFT"
        assert rerun["tier"] == "TIER_A"
