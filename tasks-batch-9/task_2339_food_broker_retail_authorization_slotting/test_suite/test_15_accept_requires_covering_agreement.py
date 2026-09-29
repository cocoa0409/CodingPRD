"""Acceptance is gated on a rate card whose half-open window covers the acceptance date."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    UPC_1,
    AgreementStatus,
    AmortizationMethod,
    ApiErrorId,
    AuthorizationState,
    DealState,
    SettlementStateAuthorization,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_version_bumped_by, assert_version_unchanged

FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 400
GROSS_FEE_CENTS = 5000000
ADMIN_FEE_CENTS = 125000
ACCEPTED_FEE_CENTS = 5125000
LAPSE_DATE = "2026-09-01"


@pytest.fixture
def awarded_deal_under_a_lapsed_agreement(api):
    """A decided review and a live offer, but the only rate card expired on the award date.

    The agreement's window closes on 2026-09-01, so it covered the 2026-08-01 deck
    submission and no longer covers the 2026-09-02 acceptance.
    """
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(
        api, retailer["id"], agreement_overrides={"effective_end_date": LAPSE_DATE}
    )
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=2)
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=6,
        amortization_method=AmortizationMethod.FORECAST_STRAIGHT,
    )
    fixtures.lock_and_decide(api, review["id"], retailer["id"], [item["id"]])
    return {
        "retailer": retailer,
        "principal": principal,
        "agreement": bundle["agreement"],
        "item": item,
        "review": review,
        "presentation": presentation,
        "deal": deal,
    }


def attempt_accept(api, scope):
    principal = fixtures.get_principal(api, scope["principal"]["id"])
    return api.accept_deal(
        scope["deal"]["id"],
        F.accept_payload(principal["version"]),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def activate_successor_agreement(api, scope):
    """Draft and activate a second rate card starting exactly where the first one ended."""
    return fixtures.create_agreement(
        api,
        scope["principal"]["id"],
        scope["retailer"]["id"],
        effective_start_date=LAPSE_DATE,
        effective_end_date="2027-01-01",
    )


class TestAcceptRequiresCoveringAgreement:
    def test_a_still_active_but_lapsed_rate_card_blocks_acceptance(
        self, api, awarded_deal_under_a_lapsed_agreement
    ):
        """The agreement is ACTIVE, yet its window no longer contains the clock date.

        PRD: "Ranges in this system are **half-open**: the start bound is inclusive and the end
        bound is exclusive."

        Design: Difficulty/cross_entity_state_dependency/deal_accept_requires_agreement_window_covering_the_acceptance_date
        """
        agreement = get_success_data(
            api.get_agreement(
                awarded_deal_under_a_lapsed_agreement["agreement"]["id"], BROKER_ADMIN_HEADERS
            ),
            200,
        )
        assert agreement["status"] == AgreementStatus.ACTIVE
        assert agreement["effective_end_date"] == LAPSE_DATE

        response = attempt_accept(api, awarded_deal_under_a_lapsed_agreement)
        validate_error(response, ApiErrorId.NO_ACTIVE_COMMISSION_AGREEMENT, 422)

    def test_the_award_decision_itself_was_never_gated_on_coverage(
        self, api, awarded_deal_under_a_lapsed_agreement
    ):
        """The authorization exists and waits on its negotiation, coverage notwithstanding.

        PRD: "For every awarded item, processed in ascending `upc` order, an `Authorization` is
        created with `authorization_state` at `PENDING_SETUP` and `settlement_state` at
        `UNBILLED`, carrying the `review_id` of the deciding review, the `item_id` of the
        awarded item, and a `retailer_id` denormalized from the review so that chain-scope
        checks never need to walk the graph."

        Design: Difficulty/cross_entity_state_dependency/deal_accept_requires_agreement_window_covering_the_acceptance_date
        """
        authorization = fixtures.authorization_for_deal(
            api, awarded_deal_under_a_lapsed_agreement["deal"]["id"]
        )

        assert authorization["authorization_state"] == AuthorizationState.PENDING_SETUP
        assert authorization["settlement_state"] == SettlementStateAuthorization.UNBILLED
        assert authorization["authorized_store_count"] == STORE_COUNT

    def test_the_refused_acceptance_moves_nothing(
        self, api, awarded_deal_under_a_lapsed_agreement
    ):
        """The offer stays on the table and the principal is untouched.

        PRD: "Acceptance freezes `accepted_fee_cents` at the standing `quoted_fee_cents`, sets
        `unamortized_balance_cents` to that same figure, and computes
        `cost_per_forecast_unit_cents` as `accepted_fee_cents` divided by
        `forecast_annual_units`, rounded half up to two decimal places — null when
        `forecast_annual_units` is zero."

        Design: Difficulty/cross_entity_state_dependency/deal_accept_requires_agreement_window_covering_the_acceptance_date
        """
        before = fixtures.get_principal(
            api, awarded_deal_under_a_lapsed_agreement["principal"]["id"]
        )
        attempt_accept(api, awarded_deal_under_a_lapsed_agreement)

        deal = fixtures.get_deal(api, awarded_deal_under_a_lapsed_agreement["deal"]["id"])
        assert deal["state"] == DealState.PROPOSED
        assert deal["unamortized_balance_cents"] == 0

        after = fixtures.get_principal(
            api, awarded_deal_under_a_lapsed_agreement["principal"]["id"]
        )
        assert after["slotting_committed_cents"] == 0
        assert_version_unchanged(before, after)

    def test_an_exactly_adjacent_successor_card_activates_cleanly(
        self, api, awarded_deal_under_a_lapsed_agreement
    ):
        """A window starting on the old end date is not an overlap.

        PRD: "Because the windows are half-open, exact adjacency is legal: a new window whose
        `effective_start_date` equals the existing window's `effective_end_date` activates
        cleanly."

        Design: Difficulty/cross_entity_state_dependency/deal_accept_requires_agreement_window_covering_the_acceptance_date
        """
        successor = activate_successor_agreement(api, awarded_deal_under_a_lapsed_agreement)

        assert successor["status"] == AgreementStatus.ACTIVE
        assert successor["effective_start_date"] == LAPSE_DATE
        assert successor["activated_at"] is not None

    def test_the_identical_acceptance_succeeds_once_coverage_is_restored(
        self, api, awarded_deal_under_a_lapsed_agreement
    ):
        """Nothing about the deal changed; only the calendar coverage did.

        PRD: "an `ACTIVE` commission agreement for the principal, the review's chain and the
        review's category must cover the current logical-clock date, otherwise
        `ERR_NO_ACTIVE_COMMISSION_AGREEMENT`"

        Design: Difficulty/cross_entity_state_dependency/deal_accept_requires_agreement_window_covering_the_acceptance_date
        """
        scope = awarded_deal_under_a_lapsed_agreement
        validate_error(attempt_accept(api, scope), ApiErrorId.NO_ACTIVE_COMMISSION_AGREEMENT, 422)

        activate_successor_agreement(api, scope)
        before = fixtures.get_principal(api, scope["principal"]["id"])
        accepted = get_success_data(attempt_accept(api, scope), 200)

        assert accepted["state"] == DealState.AMORTIZING
        assert accepted["gross_fee_cents"] == GROSS_FEE_CENTS
        assert accepted["admin_fee_cents"] == ADMIN_FEE_CENTS
        assert accepted["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert accepted["cost_per_forecast_unit_cents"] is None

        after = fixtures.get_principal(api, scope["principal"]["id"])
        assert after["slotting_committed_cents"] == ACCEPTED_FEE_CENTS
        assert_version_bumped_by(before, after, 1)

    def test_the_gating_agreement_is_never_mutated_by_any_of_this(
        self, api, awarded_deal_under_a_lapsed_agreement
    ):
        """Only the window's position against the clock decides; the rate card is read-only here.

        PRD: "On success, `activated_at` is stamped from the logical clock, and presentation
        submission and deal acceptance become possible for every date the window covers."

        Design: Difficulty/cross_entity_state_dependency/deal_accept_requires_agreement_window_covering_the_acceptance_date
        """
        scope = awarded_deal_under_a_lapsed_agreement
        attempt_accept(api, scope)
        activate_successor_agreement(api, scope)
        get_success_data(attempt_accept(api, scope), 200)

        original = get_success_data(
            api.get_agreement(scope["agreement"]["id"], BROKER_ADMIN_HEADERS), 200
        )
        assert original["status"] == AgreementStatus.ACTIVE
        assert original["effective_end_date"] == LAPSE_DATE
        assert original["version"] == scope["agreement"]["version"]
