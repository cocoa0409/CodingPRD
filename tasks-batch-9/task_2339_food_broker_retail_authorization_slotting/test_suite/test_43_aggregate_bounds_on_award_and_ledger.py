"""Bounds that count other rows: slots, chain size, claim size, period sequence and nesting."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    AuthorizationState,
    DisputeState,
    PresentationStatus,
    SettlementStateAuthorization,
    UPC_1,
    UPC_2,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_version_unchanged

CHAIN_STORE_COUNT = 1200
AWARD_STORE_COUNT = 400
OVERSIZED_STORE_COUNT = 5000
DEDUCTION_AMOUNT_CENTS = 50000


@pytest.fixture
def locked_review_with_two_items_and_one_slot(api):
    """One slot, two validated items in a single locked deck, and an open 50,000 deduction."""
    retailer = fixtures.create_retailer(api, total_store_count=CHAIN_STORE_COUNT)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    first_item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    second_item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_2)
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=1)
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [first_item["id"], second_item["id"]]
    )
    fixtures.lock_review(api, review["id"], retailer["id"])
    fixtures.set_clock(api, fixtures.DECIDE_INSTANT)
    deduction = fixtures.create_deduction(
        api,
        retailer["id"],
        principal["id"],
        amount_cents=DEDUCTION_AMOUNT_CENTS,
        deduction_date="2026-09-01",
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "first_item": first_item,
        "second_item": second_item,
        "review": review,
        "presentation": presentation,
        "deduction": deduction,
    }


def attempt_decision(api, scope, item_ids, default_store_count):
    """Decide with a fresh version pin; the clock already sits inside the decision window."""
    review = fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])
    return api.decide_review(
        scope["review"]["id"],
        F.decide_payload(
            review["version"], item_ids, default_store_count=default_store_count
        ),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def award_the_first_item(api, scope):
    """Award the single slot to the first item and return its live authorization."""
    get_success_data(
        attempt_decision(api, scope, [scope["first_item"]["id"]], AWARD_STORE_COUNT), 200
    )
    return fixtures.authorizations_for_review(api, scope["review"]["id"])[0]


def attempt_posting(api, scope, authorization, **overrides):
    return api.post_snapshot(
        F.snapshot_payload(authorization["id"], authorization["version"], **overrides),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


class TestAggregateBoundsOnAwardAndLedger:
    def test_a_store_count_above_the_chain_size_outranks_the_slot_shortfall(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """Two items against one slot and 5,000 stores against 1,200: the structural bound answers.

        PRD: "No authorization may be created for more stores than the chain has, so a resulting
        `authorized_store_count` above the chain's `total_store_count` is
        `ERR_STORE_COUNT_EXCEEDS_CHAIN`."

        PRD: "And finally the fiscal gate: the number of items in `authorized_item_ids` must not
        exceed the review's `slots_remaining`, otherwise `ERR_REVIEW_SLOTS_EXCEEDED`."

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot

        response = attempt_decision(
            api,
            scope,
            [scope["first_item"]["id"], scope["second_item"]["id"]],
            OVERSIZED_STORE_COUNT,
        )

        validate_error(response, ApiErrorId.STORE_COUNT_EXCEEDS_CHAIN, 409)

    def test_awarding_two_items_into_one_slot_is_refused(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """With the store count legal, the slot pool is the only remaining bound.

        PRD: "And finally the fiscal gate: the number of items in `authorized_item_ids` must not
        exceed the review's `slots_remaining`, otherwise `ERR_REVIEW_SLOTS_EXCEEDED`."

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot

        response = attempt_decision(
            api,
            scope,
            [scope["first_item"]["id"], scope["second_item"]["id"]],
            AWARD_STORE_COUNT,
        )

        validate_error(response, ApiErrorId.REVIEW_SLOTS_EXCEEDED, 409)
        review = fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])
        assert review["slots_awarded"] == 0
        assert review["slots_remaining"] == 1

    def test_one_award_consumes_the_slot_and_auto_advances_the_authorization(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """No live negotiation exists, so the awarded authorization goes live while still UNBILLED.

        PRD: "An authorization created with no linked deal has nothing to negotiate and therefore
        auto-advances `PENDING_SETUP` → `AUTHORIZED` immediately in the same request, while remaining
        `UNBILLED` on the settlement dimension."

        PRD: "Every presentation of this review with at least one awarded item moves `status` from
        `SUBMITTED` to `ACCEPTED` and has `authorized_item_count` set to the number of its own items
        that were awarded, and its live deal stays in `PROPOSED` or `COUNTERED` and thereby becomes
        acceptable."

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot

        authorization = award_the_first_item(api, scope)

        review = fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])
        assert review["slots_awarded"] == 1
        assert review["slots_remaining"] == 0
        assert authorization["item_id"] == scope["first_item"]["id"]
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert authorization["settlement_state"] == SettlementStateAuthorization.UNBILLED
        assert authorization["authorized_store_count"] == AWARD_STORE_COUNT
        presentation = get_success_data(
            api.get_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS), 200
        )
        assert presentation["status"] == PresentationStatus.ACCEPTED
        assert presentation["authorized_item_count"] == 1

    def test_a_claim_larger_than_the_deduction_is_refused(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """One cent over the charged amount is not a claim the chain will hear.

        PRD: "Filing a post-audit claim is a `BrokerAccountManager` action carrying
        `claim_amount_cents`."

        PRD: "and `claim_amount_cents` to be no greater than `amount_cents`, otherwise
        `ERR_CLAIM_EXCEEDS_DEDUCTION`"

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot

        response = api.dispute_deduction(
            scope["deduction"]["id"],
            F.dispute_payload(DEDUCTION_AMOUNT_CENTS + 1),
            ACCOUNT_MANAGER_HEADERS,
        )

        validate_error(response, ApiErrorId.CLAIM_EXCEEDS_DEDUCTION, 409)
        deduction = fixtures.get_deduction(api, scope["deduction"]["id"])
        assert deduction["dispute_state"] == DisputeState.NOT_DISPUTED
        assert deduction["open_cents"] == DEDUCTION_AMOUNT_CENTS

    def test_a_gap_in_the_period_sequence_is_refused(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """Nothing has been reported yet, so period 2 has no predecessor to follow.

        PRD: "`period_index` is 1-based and must equal the authorization's current
        `periods_reported` plus one — no gaps and no back-filling — otherwise
        `ERR_PERIOD_OUT_OF_SEQUENCE`; a live posting already occupying that period is
        `ERR_PERIOD_ALREADY_POSTED`."

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot
        authorization = award_the_first_item(api, scope)

        response = attempt_posting(
            api,
            scope,
            authorization,
            period_index=2,
            reported_store_count=AWARD_STORE_COUNT,
            distributed_store_count=380,
            reported_case_volume=900,
        )

        validate_error(response, ApiErrorId.PERIOD_OUT_OF_SEQUENCE, 409)

    def test_the_two_nesting_bounds_are_refused_and_no_rejection_moves_the_version(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """Reported above authorized and distributed above reported both fail, and the same pin
        still works afterwards.

        PRD: "The store counts must nest: `distributed_store_count` may not exceed
        `reported_store_count`, otherwise `ERR_DISTRIBUTION_EXCEEDS_REPORTED`, and
        `reported_store_count` may not exceed the authorization's `authorized_store_count`, otherwise
        `ERR_REPORTED_EXCEEDS_AUTHORIZED`."

        PRD: "The principal's aggregates, `at_risk_authorization_count`, `liability_ratio_bps` and
        `credit_posture` are re-derived. The authorization's `version` advances by one."

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot
        authorization = award_the_first_item(api, scope)

        validate_error(
            attempt_posting(
                api,
                scope,
                authorization,
                period_index=1,
                reported_store_count=500,
                distributed_store_count=380,
                reported_case_volume=900,
            ),
            ApiErrorId.REPORTED_EXCEEDS_AUTHORIZED,
            409,
        )
        validate_error(
            attempt_posting(
                api,
                scope,
                authorization,
                period_index=1,
                reported_store_count=300,
                distributed_store_count=350,
                reported_case_volume=900,
            ),
            ApiErrorId.DISTRIBUTION_EXCEEDS_REPORTED,
            409,
        )

        assert_version_unchanged(
            authorization, fixtures.get_authorization(api, authorization["id"])
        )
        posted = get_success_data(
            attempt_posting(
                api,
                scope,
                authorization,
                period_index=1,
                reported_store_count=AWARD_STORE_COUNT,
                distributed_store_count=AWARD_STORE_COUNT,
                reported_case_volume=1000,
            ),
            201,
        )
        assert posted["period_index"] == 1

    def test_re_posting_a_live_period_reports_the_uniqueness_error(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """Period 1 breaks both the uniqueness rule and the sequence rule; uniqueness is listed first.

        PRD: "And at most one live `POSTING` ledger entry exists per combination of
        `authorization_id` and `period_index` (`ERR_PERIOD_ALREADY_POSTED`)."

        PRD: "Within a band, checks are applied in the order listed here."

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot
        authorization = award_the_first_item(api, scope)
        fixtures.post_period(
            api,
            authorization["id"],
            scope["retailer"]["id"],
            period_index=1,
            reported_store_count=AWARD_STORE_COUNT,
            distributed_store_count=AWARD_STORE_COUNT,
            reported_case_volume=1000,
        )

        response = attempt_posting(
            api,
            scope,
            fixtures.get_authorization(api, authorization["id"]),
            period_index=1,
            reported_store_count=AWARD_STORE_COUNT,
            distributed_store_count=399,
            reported_case_volume=800,
        )

        validate_error(response, ApiErrorId.PERIOD_ALREADY_POSTED, 409)

    def test_only_the_highest_live_period_may_be_reversed(
        self, api, locked_review_with_two_items_and_one_slot
    ):
        """Once period 2 exists, period 1 is no longer the entry that may be cancelled.

        PRD: "Only the highest live `period_index` of an authorization may be reversed, otherwise
        `ERR_SNAPSHOT_NOT_LATEST`, and reversing an already-reversed posting or a `REVERSAL` entry
        itself is `ERR_SNAPSHOT_ALREADY_REVERSED`."

        Design: Corner/validations/aggregate_bounds_on_award_snapshots_and_claims_rejected
        """
        scope = locked_review_with_two_items_and_one_slot
        authorization = award_the_first_item(api, scope)
        first_period = fixtures.post_period(
            api,
            authorization["id"],
            scope["retailer"]["id"],
            period_index=1,
            reported_store_count=AWARD_STORE_COUNT,
            distributed_store_count=AWARD_STORE_COUNT,
            reported_case_volume=1000,
        )
        second_period = fixtures.post_period(
            api,
            authorization["id"],
            scope["retailer"]["id"],
            period_index=2,
            reported_store_count=AWARD_STORE_COUNT,
            distributed_store_count=AWARD_STORE_COUNT,
            reported_case_volume=1100,
        )

        response = api.reverse_snapshot(
            first_period["id"], make_retailer_buyer_headers(scope["retailer"]["id"])
        )

        validate_error(response, ApiErrorId.SNAPSHOT_NOT_LATEST, 409)
        assert second_period["period_index"] == 2
        assert second_period["is_reversed"] is False
