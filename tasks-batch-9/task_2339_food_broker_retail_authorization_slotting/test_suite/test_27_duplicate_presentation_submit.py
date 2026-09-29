"""Submitting a deck twice is not a no-op — the second attempt is an invalid move."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    PresentationStatus,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers.assertions import assert_version_bumped_by, assert_version_unchanged


@pytest.fixture
def draft_deck_in_an_open_review(api):
    """An active principal with a validated item and a DRAFT deck ready to submit."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"])
    review = fixtures.opened_review(api, retailer["id"])
    presentation = fixtures.create_presentation(api, review["id"], principal["id"], [item["id"]])
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "review": review,
        "presentation": presentation,
    }


def submit(api, scope):
    return api.submit_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS)


class TestDuplicatePresentationSubmit:
    def test_the_first_submit_moves_the_deck_and_stamps_the_instant(
        self, api, draft_deck_in_an_open_review
    ):
        """DRAFT to SUBMITTED with a full completeness score, because the item is validated.

        PRD: "On success `submitted_at` is stamped from the logical clock and
        `prep_completeness_bps` is recomputed — necessarily 10,000, since every listed item has
        been validated."

        Design: Corner/state_machines/second_presentation_submit_is_rejected_as_invalid_state
        """
        submitted = get_success_data(submit(api, draft_deck_in_an_open_review), 200)

        assert submitted["status"] == PresentationStatus.SUBMITTED
        assert submitted["submitted_at"] is not None
        assert submitted["prep_completeness_bps"] == 10000

    def test_the_second_submit_is_refused_as_an_invalid_state(
        self, api, draft_deck_in_an_open_review
    ):
        """SUBMITTED has no self-loop, so the double click is rejected, not absorbed.

        PRD: "The target must be in a state from which the requested transition exists, and
        companion resources must be in the states the transition names — covering `status` on
        principals, agreements and reviews, `catalog_state` on items, `status` on presentations,
        `state` on deals and promotion events, both `authorization_state` and `settlement_state`
        on authorizations, and both `settlement_state` and `dispute_state` on deductions."

        Design: Corner/state_machines/second_presentation_submit_is_rejected_as_invalid_state
        """
        get_success_data(submit(api, draft_deck_in_an_open_review), 200)

        validate_error(submit(api, draft_deck_in_an_open_review), ApiErrorId.INVALID_STATE, 409)

    def test_the_deck_version_advances_exactly_once_across_both_calls(
        self, api, draft_deck_in_an_open_review
    ):
        """One mutation happened, so one version step is all that may be recorded.

        PRD: "Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
        refreshed on every change to the resource, and `version`, an integer that is 1 when the
        resource is created and increases by exactly one on every mutation of that resource."

        Design: Corner/state_machines/second_presentation_submit_is_rejected_as_invalid_state
        """
        scope = draft_deck_in_an_open_review
        submitted = get_success_data(submit(api, scope), 200)
        validate_error(submit(api, scope), ApiErrorId.INVALID_STATE, 409)

        after = get_success_data(
            api.get_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS), 200
        )

        assert_version_bumped_by(scope["presentation"], submitted, 1)
        assert_version_unchanged(submitted, after)
        assert after["status"] == PresentationStatus.SUBMITTED

    def test_the_refused_call_does_not_disturb_the_review(self, api, draft_deck_in_an_open_review):
        """The parent review was not mutated by the submission, so nothing can double-count.

        PRD: "A change to a *derived* field counts as a mutation: when an accepted slotting fee
        moves a principal's committed total, or a distribution posting moves an authorization's
        void counters, the affected resource's `updated_at` is refreshed and its `version`
        advances."

        Design: Corner/state_machines/second_presentation_submit_is_rejected_as_invalid_state
        """
        scope = draft_deck_in_an_open_review
        get_success_data(submit(api, scope), 200)
        before = fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])

        validate_error(submit(api, scope), ApiErrorId.INVALID_STATE, 409)

        after = fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])
        assert_version_unchanged(before, after)
