"""Presentation submission reports the closed deadline ahead of the conflict rule."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    ACCOUNT_MANAGER_HEADERS,
    UPC_1,
    UPC_2,
    ApiErrorId,
    ConflictRuleStatus,
    ConflictScope,
    PresentationStatus,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers import factories as F

BEFORE_DEADLINE = "2026-08-19T23:59:59Z"
AFTER_DEADLINE = "2026-08-21T00:00:00Z"


@pytest.fixture
def conflicting_decks_past_the_deadline(api):
    """Two conflicting principals in one open review, with the deadline already passed.

    The first principal's deck is already submitted, so the second principal's
    submission breaks both the deadline rule and the conflict rule at once.
    """
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    first = fixtures.active_principal(api, retailer["id"])["principal"]
    second = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"name": "Sunglow Frozen", "code": "SGF"},
        agreement_overrides={"base_commission_bps": 450, "tier_commission_bps": 275},
    )["principal"]

    rule = get_success_data(
        api.create_conflict_rule(
            F.conflict_rule_payload(
                first["id"],
                second["id"],
                scope=ConflictScope.RETAILER_LEVEL,
                retailer_id=retailer["id"],
            ),
            BROKER_ADMIN_HEADERS,
        ),
        201,
    )

    first_item = fixtures.validated_item(api, first["id"], retailer["id"], upc=UPC_1)
    second_item = fixtures.validated_item(
        api,
        second["id"],
        retailer["id"],
        upc=UPC_2,
        description="Frozen Empanadas 10ct",
        case_pack_units=10,
        list_price_cents=2000,
        unit_cost_cents=1150,
    )

    review = fixtures.opened_review(api, retailer["id"], new_item_slots=2)
    fixtures.submitted_presentation(api, review["id"], first["id"], [first_item["id"]])
    blocked = fixtures.create_presentation(
        api, review["id"], second["id"], [second_item["id"]]
    )
    fixtures.set_clock(api, AFTER_DEADLINE)
    return {
        "retailer": retailer,
        "rule": rule,
        "review": review,
        "blocked": blocked,
    }


def attempt_submit(api, scope):
    return api.submit_presentation(scope["blocked"]["id"], ACCOUNT_MANAGER_HEADERS)


class TestSubmissionPrecedenceDeadlineBeforeConflict:
    def test_the_temporal_rule_wins_and_carries_its_own_status(
        self, api, conflicting_decks_past_the_deadline
    ):
        """A 422 deadline error, not the conflict rule's 409, even though both apply.

        PRD: "Then the temporal check: the logical clock must be strictly before the review's
        `submission_deadline`, otherwise `ERR_REVIEW_SUBMISSION_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/presentation_submission_deadline_beats_principal_conflict_rule
        """
        response = attempt_submit(api, conflicting_decks_past_the_deadline)

        validate_error(response, ApiErrorId.REVIEW_SUBMISSION_CLOSED, 422)
        assert ApiErrorId.PRINCIPAL_CONFLICT not in response.text

    def test_the_refused_submission_leaves_the_deck_in_draft(
        self, api, conflicting_decks_past_the_deadline
    ):
        """Nothing about the presentation moves when the submission is refused.

        PRD: "Submitting the deck moves `status` from `DRAFT` to `SUBMITTED` and is the most
        heavily guarded operation in the system."

        Design: Difficulty/priority_pair_validation_conflict/presentation_submission_deadline_beats_principal_conflict_rule
        """
        attempt_submit(api, conflicting_decks_past_the_deadline)

        presentation = get_success_data(
            api.get_presentation(
                conflicting_decks_past_the_deadline["blocked"]["id"], ACCOUNT_MANAGER_HEADERS
            ),
            200,
        )
        assert presentation["status"] == PresentationStatus.DRAFT
        assert presentation["submitted_at"] is None

    def test_rolling_the_clock_back_reveals_the_live_conflict_rule(
        self, api, conflicting_decks_past_the_deadline
    ):
        """Inside the deadline the identical submit is refused by the conflict rule instead.

        PRD: "No `ACTIVE` conflict rule may pair this principal with a principal that already
        holds a presentation in `SUBMITTED` or `ACCEPTED` status in this same review, where
        the rule's `category_code` equals the review's category and the rule's `scope` is
        either `NATIONAL` or is `RETAILER_LEVEL` with a `retailer_id` equal to the review's
        chain; a match is `ERR_PRINCIPAL_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/presentation_submission_deadline_beats_principal_conflict_rule
        """
        fixtures.set_clock(api, BEFORE_DEADLINE)

        response = attempt_submit(api, conflicting_decks_past_the_deadline)
        validate_error(response, ApiErrorId.PRINCIPAL_CONFLICT, 409)
        assert ApiErrorId.REVIEW_SUBMISSION_CLOSED not in response.text

    def test_waiving_the_rule_clears_the_last_obstacle(
        self, api, conflicting_decks_past_the_deadline
    ):
        """With the edge retired and the clock inside the deadline, the deck submits.

        PRD: "A `BrokerAdmin` may later retire the edge by moving it `ACTIVE` → `WAIVED` with
        a `waiver_reason`, which is recorded on the rule; `WAIVED` is terminal, and from that
        point the pair is no longer considered by the conflict check that guards presentation
        submission."

        Design: Difficulty/priority_pair_validation_conflict/presentation_submission_deadline_beats_principal_conflict_rule
        """
        fixtures.set_clock(api, BEFORE_DEADLINE)
        waived = get_success_data(
            api.waive_conflict_rule(
                conflicting_decks_past_the_deadline["rule"]["id"],
                F.waive_payload("Competitive overlap resolved"),
                BROKER_ADMIN_HEADERS,
            ),
            200,
        )
        assert waived["status"] == ConflictRuleStatus.WAIVED
        assert waived["waiver_reason"] == "Competitive overlap resolved"

        submitted = get_success_data(attempt_submit(api, conflicting_decks_past_the_deadline), 200)
        assert submitted["status"] == PresentationStatus.SUBMITTED
        assert submitted["prep_completeness_bps"] == 10000
