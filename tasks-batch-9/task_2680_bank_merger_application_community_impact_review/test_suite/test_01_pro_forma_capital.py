"""Pro forma capital schedules on the two declared bases."""
import pytest

from test_helpers import ApiErrorId, api_client, make_filer_headers
from test_helpers.assertions import assert_pro_forma_schedule
from test_helpers.fixtures import (
    create_regulatory_schedule,
    create_stress_schedule,
    create_undercapitalized_schedule,
    read_application,
    read_schedule,
    submit_application,
    two_bank_world,
)
from prd_bench_local_runner.testing import validate_error


class TestDualBasisCapitalArithmetic:
    """The regulatory basis and the stress basis diverge on identical inputs."""

    def test_regulatory_basis_caps_the_deferred_tax_allowance(self):
        """PRD §3.3: "The deferred tax asset receives an allowance equal to 10 percent of that
        pre-deduction common equity, truncated toward zero to a whole dollar; the excess deferred
        tax asset is the amount by which `deferred_tax_asset_usd` exceeds that allowance, or zero
        when it does not exceed it."
        PRD §3.3: "On this basis `aoci_markdown_usd` is disclosed on the schedule but is not
        deducted from anything."
        PRD §3.3: "When the common-equity ratio is at least 7.00 percent and the leverage ratio is
        at least 5.00 percent, the flag is `WELL_CAPITALIZED`."

        Design: Difficulty/dual_variant_calc/pro_forma_capital_dual_basis_diverges_on_identical_transaction_inputs
        """
        world = two_bank_world()
        schedule = create_regulatory_schedule(
            world["application"]["id"], world["acquirer"]["id"]
        )

        assert_pro_forma_schedule(schedule)
        assert schedule["basis"] == "REGULATORY_ADJUSTED"
        assert schedule["pro_forma_cet1_ratio_pct"] == pytest.approx(7.74, abs=0.005), (
            f"Expected 7.74, got {schedule['pro_forma_cet1_ratio_pct']} on the regulatory basis"
        )
        assert schedule["pro_forma_tier1_leverage_pct"] == pytest.approx(6.52, abs=0.005), (
            f"Expected 6.52, got {schedule['pro_forma_tier1_leverage_pct']} on the regulatory basis"
        )
        assert schedule["capital_adequacy_flag"] == "WELL_CAPITALIZED"

    def test_stress_basis_deducts_the_full_deferred_tax_asset_and_a_credit_mark(self):
        """PRD §3.3: "A credit mark is taken first: 2.5 percent of the target's `total_loans_usd`,
        truncated toward zero to a whole dollar."
        PRD §3.3: "Otherwise, when the common-equity ratio is at least 4.50 percent and the
        leverage ratio is at least 4.00 percent, the flag is `ADEQUATELY_CAPITALIZED`."

        Design: Difficulty/dual_variant_calc/pro_forma_capital_dual_basis_diverges_on_identical_transaction_inputs
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        stress = create_stress_schedule(application_id, acquirer_id)

        assert stress["basis"] == "INTERNAL_STRESS"
        assert stress["pro_forma_cet1_ratio_pct"] == pytest.approx(5.77, abs=0.005), (
            f"Expected 5.77, got {stress['pro_forma_cet1_ratio_pct']} on the stress basis"
        )
        assert stress["pro_forma_tier1_leverage_pct"] == pytest.approx(5.02, abs=0.005), (
            f"Expected 5.02, got {stress['pro_forma_tier1_leverage_pct']} on the stress basis"
        )
        assert stress["capital_adequacy_flag"] == "ADEQUATELY_CAPITALIZED", (
            "the stress basis is harsher, so identical inputs band one step lower"
        )

    def test_each_basis_keeps_its_own_current_schedule_and_bumps_the_application(self):
        """PRD §3.3: "Each schedule carries a `status` of `CURRENT` or `SUPERSEDED`, and at most one
        schedule per application and basis is `CURRENT`."
        PRD §3.3: "Building a new schedule on a basis moves the prior current schedule of that same
        basis to `SUPERSEDED`, and increments the application's `version` by 1."

        Design: Difficulty/dual_variant_calc/pro_forma_capital_dual_basis_diverges_on_identical_transaction_inputs
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        assert world["application"]["version"] == 1

        regulatory = create_regulatory_schedule(application_id, acquirer_id, expected_version=1)
        stress = create_stress_schedule(application_id, acquirer_id, expected_version=2)

        assert read_schedule(regulatory["id"])["status"] == "CURRENT", (
            "a build on a different basis never supersedes the other basis"
        )
        assert read_schedule(stress["id"])["status"] == "CURRENT"
        assert read_application(application_id, acquirer_id)["version"] == 3, (
            "each of the two builds increments the application version by exactly 1"
        )


class TestSubmissionStatePrecedesTheCapitalGate:
    """Own-resource state is evaluated ahead of the pro forma capital gate."""

    def test_resubmit_of_a_submitted_application_reports_the_state_error(self):
        """PRD §2.5: "Own-resource state: the target record is in a state from which the requested
        transition is declared — one of `ERR_INVALID_APPLICATION_STATE`,
        `ERR_COMMENT_PERIOD_NOT_OPEN`, `ERR_INVALID_HEARING_REQUEST_STATE`,
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DECISION_STATE`, `ERR_INVALID_CONDITION_STATE`,
        `ERR_INVALID_CONVERSION_PLAN_STATE`, `ERR_INVALID_REPORT_STATE` or
        `ERR_INVALID_BRANCH_STATE`, all at HTTP 409."
        PRD §2.5: "The current regulatory-basis schedule shows the combined institution well
        capitalized at submission — `ERR_PRO_FORMA_CAPITAL_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/resubmit_state_error_wins_over_pro_forma_capital_insufficiency
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        submitted = submit_application(application_id, acquirer_id)
        assert submitted["filing_status"] == "SUBMITTED"
        create_undercapitalized_schedule(application_id, acquirer_id)

        response = api_client.submit_merger_application(
            application_id, make_filer_headers(acquirer_id)
        )

        validate_error(response, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value, 409)
        assert read_application(application_id, acquirer_id)["filing_status"] == "SUBMITTED"

    def test_superseding_schedule_becomes_current_and_bands_undercapitalized(self):
        """PRD §3.3: "Building a new schedule on a basis moves the prior current schedule of that
        same basis to `SUPERSEDED`, and increments the application's `version` by 1."
        PRD §3.3: "In any other case the flag is `UNDERCAPITALIZED`."

        Design: Difficulty/priority_pair_validation_conflict/resubmit_state_error_wins_over_pro_forma_capital_insufficiency
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        good = create_regulatory_schedule(application_id, acquirer_id)
        submit_application(application_id, acquirer_id)

        bad = create_undercapitalized_schedule(application_id, acquirer_id)

        assert bad["status"] == "CURRENT"
        assert bad["pro_forma_cet1_ratio_pct"] == pytest.approx(0.28, abs=0.005), (
            f"Expected 0.28, got {bad['pro_forma_cet1_ratio_pct']} after the heavier adjustments"
        )
        assert bad["pro_forma_tier1_leverage_pct"] == pytest.approx(0.61, abs=0.005), (
            f"Expected 0.61, got {bad['pro_forma_tier1_leverage_pct']} after the heavier adjustments"
        )
        assert bad["capital_adequacy_flag"] == "UNDERCAPITALIZED"
        assert read_schedule(good["id"])["status"] == "SUPERSEDED"
