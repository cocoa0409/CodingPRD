"""Management scoring at the second decimal place, and the filing gate's party checks."""
import pytest

from test_helpers import ApiErrorId, api_client, make_filer_headers
from test_helpers.assertions import assert_merger_application
from test_helpers.fixtures import (
    application_consummated,
    create_application,
    create_institution,
    create_regulatory_schedule,
    read_application,
    read_institution,
    two_bank_world,
)
from prd_bench_local_runner.testing import validate_error


class TestManagementCompositeRoundingOrder:
    """The weighting order is observable in the second decimal place."""

    def test_each_weighted_product_is_rounded_before_any_addition(self):
        """PRD §3.2: "Each score is multiplied by its own weight — 0.35 for officer experience,
        0.30 for risk management, 0.175 for compliance history and 0.175 for integration
        readiness — and **each weighted product is rounded half-up to two decimal places before any
        addition happens**."
        PRD §3.2: "The four rounded products are then added and the sum is itself rounded half-up to
        two decimal places to give `management_composite_score`."

        Design: Difficulty/combinatorial_formula/management_composite_per_product_rounding_order
        """
        world = two_bank_world()
        application = world["application"]

        assert_merger_application(application)
        assert application["management_composite_score"] == pytest.approx(70.11, abs=0.005), (
            "scores 72/68/67/73 give 25.20 + 20.40 + 11.73 + 12.78 = 70.11, "
            f"got {application['management_composite_score']}"
        )

    def test_summing_the_unrounded_products_is_not_what_the_service_does(self):
        """PRD §3.2: "Summing the unrounded products and rounding once at the end produces a
        different answer in ordinary cases and is not what this service does."

        Design: Difficulty/combinatorial_formula/management_composite_per_product_rounding_order
        """
        world = two_bank_world()

        score = world["application"]["management_composite_score"]

        assert score != pytest.approx(70.10, abs=0.001), (
            "70.10 is the answer produced by rounding only once at the end; "
            "the per-product rounding must land on 70.11"
        )

    def test_composite_at_the_threshold_bands_satisfactory(self):
        """PRD §3.2: "The composite is then banded into `management_rating`: a composite of 70.00 or
        more is `SATISFACTORY`, a composite of at least 55.00 but below 70.00 is `CONDITIONAL`, and
        anything below 55.00 is `UNSATISFACTORY`."

        Design: Difficulty/combinatorial_formula/management_composite_per_product_rounding_order
        """
        world = two_bank_world()

        assert world["application"]["management_rating"] == "SATISFACTORY"

    def test_a_new_application_starts_on_both_axes_at_version_one(self):
        """PRD §3.2: "A new application starts in `filing_status` `DRAFT` on one axis and
        `public_review_status` `NOT_OPEN` on the other, with `competitive_posture` `NOT_ANALYZED`,
        `substantive_protest_count` and `unresolved_protest_count` at 0, `amendment_round` at 0,
        `post_closing_monitoring_status` `NOT_APPLICABLE`, and `earliest_decision_at`,
        `recommendation` and `recommended_by_user_id` all null."

        Design: Difficulty/combinatorial_formula/management_composite_per_product_rounding_order
        """
        world = two_bank_world()
        application = world["application"]

        assert application["filing_status"] == "DRAFT"
        assert application["public_review_status"] == "NOT_OPEN"
        assert application["competitive_posture"] == "NOT_ANALYZED"
        assert application["version"] == 1


class TestFilingRequiresBothPartiesActive:
    """An institution merged away can be neither party to a new filing."""

    def test_submit_is_refused_when_the_target_has_been_merged_out(self):
        """PRD §3.11: "The target institution's `status` becomes `MERGED_OUT`, and a `MERGED_OUT`
        institution can never again be the acquirer or the target of a submitted application."
        PRD §3.4: "Both the acquirer and the target must have `status` `ACTIVE`, since an
        institution that has already been merged away can be neither party to a new filing; either
        being `MERGED_OUT` yields `ERR_INSTITUTION_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_target_institution_is_merged_out
        """
        world = application_consummated()
        target = world["target"]
        assert read_institution(target["id"])["status"] == "MERGED_OUT"
        second_acquirer = create_institution(
            legal_name="Crestline Bank", charter_type="NATIONAL", primary_regulator="OCC",
            latest_cra_rating="SATISFACTORY",
        )
        second = create_application(second_acquirer["id"], target["id"])
        create_regulatory_schedule(second["id"], second_acquirer["id"])

        response = api_client.submit_merger_application(
            second["id"], make_filer_headers(second_acquirer["id"])
        )

        validate_error(response, ApiErrorId.ERR_INSTITUTION_NOT_ACTIVE.value, 409)

    def test_the_first_application_stays_consummated_and_the_second_stays_draft(self):
        """PRD §3.11: "The application's `filing_status` becomes `CONSUMMATED` and its `version`
        increments by 1."
        PRD §3.4: "A successful filing sets `filing_status` to `SUBMITTED` and increments the
        application's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_target_institution_is_merged_out
        """
        world = application_consummated()
        target = world["target"]
        second_acquirer = create_institution(
            legal_name="Crestline Bank", charter_type="NATIONAL", primary_regulator="OCC",
            latest_cra_rating="SATISFACTORY",
        )
        second = create_application(second_acquirer["id"], target["id"])
        create_regulatory_schedule(second["id"], second_acquirer["id"])
        api_client.submit_merger_application(second["id"], make_filer_headers(second_acquirer["id"]))

        first = read_application(world["application"]["id"], world["acquirer"]["id"])
        blocked = read_application(second["id"], second_acquirer["id"])

        assert first["filing_status"] == "CONSUMMATED"
        assert blocked["filing_status"] == "DRAFT", (
            "a refused filing leaves the application on the state it came from"
        )

    def test_the_blocked_filing_fails_on_the_party_check_and_not_on_its_own_merits(self):
        """PRD §3.4: "The acquirer's `latest_cra_rating` must be `OUTSTANDING` or `SATISFACTORY`,
        and a rating of `NEEDS_TO_IMPROVE` or `SUBSTANTIAL_NONCOMPLIANCE` yields
        `ERR_CRA_RATING_INSUFFICIENT`."
        PRD §3.4: "Finally that schedule's `capital_adequacy_flag` must be `WELL_CAPITALIZED`, and
        any weaker flag yields `ERR_PRO_FORMA_CAPITAL_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_when_target_institution_is_merged_out
        """
        world = application_consummated()
        second_acquirer = create_institution(
            legal_name="Crestline Bank", charter_type="NATIONAL", primary_regulator="OCC",
            latest_cra_rating="SATISFACTORY",
        )
        second = create_application(second_acquirer["id"], world["target"]["id"])

        schedule = create_regulatory_schedule(second["id"], second_acquirer["id"])

        assert second["management_rating"] == "SATISFACTORY", (
            "the management gate would have passed, so the party check is what fired"
        )
        assert schedule["capital_adequacy_flag"] == "WELL_CAPITALIZED", (
            "the capital gate would have passed, so the party check is what fired"
        )
