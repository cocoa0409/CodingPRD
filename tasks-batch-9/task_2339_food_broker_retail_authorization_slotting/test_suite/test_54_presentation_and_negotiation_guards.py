"""Five guards that only a half-negotiated, half-awarded review can reach."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    AgreementStatus,
    ApiErrorId,
    AuthorizationState,
    DealState,
    DiscontinueReason,
    PresentationStatus,
    PrincipalStatus,
    PromotionState,
    UPC_1,
    UPC_2,
    UPC_3,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F

AWARD_STORE_COUNT = 400
DEAL_FEE_CENTS = 9000
FUTURE_WINDOW_START = "2026-09-20T00:00:00Z"
FUTURE_WINDOW_END = "2026-09-21T00:00:00Z"


@pytest.fixture
def review_decided_for_one_of_three_principals(api):
    """P1 won and is still negotiating; P2's deck never left DRAFT; P3's deck was declined."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    winner = fixtures.active_principal(api, retailer["id"])
    stalled = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"name": "Sunglow Frozen", "code": "SGF"},
        agreement_overrides={"base_commission_bps": 550, "tier_commission_bps": 350},
    )
    declined = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"name": "Great Lakes Foods", "code": "GLF"},
        agreement_overrides={"base_commission_bps": 480, "tier_commission_bps": 280},
    )
    winning_item = fixtures.validated_item(
        api, winner["principal"]["id"], retailer["id"], upc=UPC_1
    )
    stalled_item = fixtures.validated_item(
        api,
        stalled["principal"]["id"],
        retailer["id"],
        upc=UPC_2,
        description="Frozen Empanadas 10ct",
    )
    declined_item = fixtures.validated_item(
        api,
        declined["principal"]["id"],
        retailer["id"],
        upc=UPC_3,
        description="Churro Bites 8ct",
    )
    review = fixtures.opened_review(api, retailer["id"])

    winning_deck = fixtures.submitted_presentation(
        api, review["id"], winner["principal"]["id"], [winning_item["id"]]
    )
    winning_deal = fixtures.proposed_deal(
        api, winning_deck["id"], fee_per_store_cents=DEAL_FEE_CENTS, store_count_in_scope=200
    )
    draft_deck = fixtures.create_presentation(
        api, review["id"], stalled["principal"]["id"], [stalled_item["id"]]
    )
    draft_deck_deal = fixtures.proposed_deal(
        api, draft_deck["id"], fee_per_store_cents=DEAL_FEE_CENTS, store_count_in_scope=200
    )
    declined_deck = fixtures.submitted_presentation(
        api, review["id"], declined["principal"]["id"], [declined_item["id"]]
    )

    fixtures.lock_and_decide(
        api,
        review["id"],
        retailer["id"],
        [winning_item["id"]],
        default_store_count=AWARD_STORE_COUNT,
    )
    authorization = fixtures.authorizations_for_review(api, review["id"])[0]
    return {
        "retailer": retailer,
        "winner": winner,
        "stalled": stalled,
        "declined": declined,
        "review": review,
        "winning_deck": winning_deck,
        "winning_deal": winning_deal,
        "draft_deck": draft_deck,
        "draft_deck_deal": draft_deck_deal,
        "declined_deck": declined_deck,
        "authorization": authorization,
    }


def read_deck(api, deck):
    return get_success_data(api.get_presentation(deck["id"], ACCOUNT_MANAGER_HEADERS), 200)


def read_agreement(api, agreement_id):
    return get_success_data(api.get_agreement(agreement_id, BROKER_ADMIN_HEADERS), 200)


def attempt_agreement_termination(api, scope):
    return api.terminate_agreement(
        scope["winner"]["agreement"]["id"], BROKER_ADMIN_HEADERS
    )


def attempt_principal_termination(api, scope):
    return api.set_principal_status(
        scope["winner"]["principal"]["id"],
        F.principal_status_payload(PrincipalStatus.TERMINATED),
        BROKER_ADMIN_HEADERS,
    )


def reject_the_winning_deal(api, scope):
    return get_success_data(
        api.reject_deal(
            scope["winning_deal"]["id"],
            F.reject_deal_payload("FEE_TOO_HIGH"),
            make_retailer_buyer_headers(scope["retailer"]["id"]),
        ),
        200,
    )


class TestPresentationAndNegotiationGuards:
    def test_a_deal_on_a_still_draft_deck_cannot_be_accepted(
        self, api, review_decided_for_one_of_three_principals
    ):
        """Every other acceptance condition holds; only the deck's own status does not.

        PRD: "the presentation's `status` must be `ACCEPTED`, otherwise
        `ERR_PRESENTATION_NOT_ACCEPTED`"

        PRD: "A `RetailerBuyer` accepts a deal in `PROPOSED` state, which is legal only while
        `last_offer_side` is `BROKER`; a `BrokerAccountManager` accepts a deal in `COUNTERED` state,
        which is legal only while `last_offer_side` is `RETAILER`."

        Design: Corner/errors/presentation_and_negotiation_guards_complete_the_error_catalog
        """
        scope = review_decided_for_one_of_three_principals
        principal_before = fixtures.get_principal(api, scope["stalled"]["principal"]["id"])
        assert read_deck(api, scope["draft_deck"])["status"] == PresentationStatus.DRAFT

        response = api.accept_deal(
            scope["draft_deck_deal"]["id"],
            F.accept_payload(principal_before["version"]),
            make_retailer_buyer_headers(scope["retailer"]["id"]),
        )

        validate_error(response, ApiErrorId.PRESENTATION_NOT_ACCEPTED, 409)
        assert fixtures.get_deal(api, scope["draft_deck_deal"]["id"])["state"] == (
            DealState.PROPOSED
        )
        assert fixtures.get_principal(api, scope["stalled"]["principal"]["id"])["version"] == (
            principal_before["version"]
        )

    def test_a_negotiation_may_still_be_opened_on_a_declined_deck(
        self, api, review_decided_for_one_of_three_principals
    ):
        """Deck creation carries no status precondition at all.

        PRD: "A new deal begins with `state` at `DRAFT`, `round_index` at 0, `last_offer_side` null,
        `accepted_fee_cents`, `recovered_cents`, `written_off_cents`, `unamortized_balance_cents` and
        `periods_posted` all at 0, `reject_reason` null, and `current_fee_per_store_cents` seeded from
        `requested_fee_per_store_cents`."

        Design: Corner/errors/presentation_and_negotiation_guards_complete_the_error_catalog
        """
        scope = review_decided_for_one_of_three_principals
        assert read_deck(api, scope["declined_deck"])["status"] == PresentationStatus.DECLINED

        late_deal = fixtures.create_deal(
            api,
            scope["declined_deck"]["id"],
            requested_fee_per_store_cents=DEAL_FEE_CENTS,
            store_count_in_scope=200,
        )

        assert late_deal["state"] == DealState.DRAFT
        assert late_deal["current_fee_per_store_cents"] == DEAL_FEE_CENTS
        assert late_deal["round_index"] == 0
        assert late_deal["last_offer_side"] is None

    def test_the_declined_deck_guard_lives_on_the_propose_call(
        self, api, review_decided_for_one_of_three_principals
    ):
        """The offer, not the opening, is what a declined deck refuses.

        PRD: "A broker offer moves the deal `DRAFT` → `PROPOSED` with `proposed_fee_per_store_cents`,
        provided the presentation is in `DRAFT`, `SUBMITTED` or `ACCEPTED` status; proposing on a
        declined deck is `ERR_PRESENTATION_DECLINED`."

        Design: Corner/errors/presentation_and_negotiation_guards_complete_the_error_catalog
        """
        scope = review_decided_for_one_of_three_principals
        late_deal = fixtures.create_deal(
            api,
            scope["declined_deck"]["id"],
            requested_fee_per_store_cents=DEAL_FEE_CENTS,
            store_count_in_scope=200,
        )

        response = api.propose_deal(
            late_deal["id"], F.propose_payload(DEAL_FEE_CENTS), ACCOUNT_MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.PRESENTATION_DECLINED, 409)
        stalled_deal = fixtures.get_deal(api, late_deal["id"])
        assert stalled_deal["state"] == DealState.DRAFT
        assert stalled_deal["round_index"] == 0

    def test_a_live_offer_pins_the_rate_card_in_place(
        self, api, review_decided_for_one_of_three_principals
    ):
        """The winner's own deal is still PROPOSED for that principal, chain and category.

        PRD: "Termination moves an agreement `ACTIVE` → `TERMINATED`, and is blocked while any
        slotting deal for the same principal, chain and category is still live in `PROPOSED` or
        `COUNTERED` — the rejection is `ERR_AGREEMENT_HAS_OPEN_NEGOTIATION`, on the principle that a
        broker may not pull the rate card out from under an offer that is on the table."

        Design: Corner/errors/presentation_and_negotiation_guards_complete_the_error_catalog
        """
        scope = review_decided_for_one_of_three_principals

        response = attempt_agreement_termination(api, scope)

        validate_error(response, ApiErrorId.AGREEMENT_HAS_OPEN_NEGOTIATION, 409)
        assert read_agreement(api, scope["winner"]["agreement"]["id"])["status"] == (
            AgreementStatus.ACTIVE
        )

    def test_a_pending_setup_authorization_counts_as_live_and_blocks_termination(
        self, api, review_decided_for_one_of_three_principals
    ):
        """The awarded slot is not yet AUTHORIZED, and it still pins the principal.

        PRD: "Termination is reachable from either `ACTIVE` or `SUSPENDED` and, in both cases, requires
        that no authorization on any of this principal's items is in `PENDING_SETUP`, `AUTHORIZED` or
        `AT_RISK`; a live authorization blocks the move with `ERR_PRINCIPAL_HAS_LIVE_AUTHORIZATIONS`."

        Design: Corner/errors/presentation_and_negotiation_guards_complete_the_error_catalog
        """
        scope = review_decided_for_one_of_three_principals
        assert scope["authorization"]["authorization_state"] == AuthorizationState.PENDING_SETUP

        response = attempt_principal_termination(api, scope)

        validate_error(response, ApiErrorId.PRINCIPAL_HAS_LIVE_AUTHORIZATIONS, 409)
        assert fixtures.get_principal(api, scope["winner"]["principal"]["id"])["status"] == (
            PrincipalStatus.ACTIVE
        )

    def test_planning_a_promotion_is_free_but_committing_it_needs_shelf_space(
        self, api, review_decided_for_one_of_three_principals
    ):
        """The window is in the future, so nothing temporal masks the state guard.

        PRD: "A planned event begins with `state` at `PLANNED`, `actual_funding_cents` and
        `settled_funding_cents` at 0, and `committed_at` null."

        PRD: "The authorization must be `AUTHORIZED`: an `AT_RISK` authorization is refused with
        `ERR_AUTHORIZATION_AT_RISK`, and one that is `PENDING_SETUP` or `DISCONTINUED` with
        `ERR_AUTHORIZATION_NOT_AUTHORIZED`."

        Design: Corner/errors/presentation_and_negotiation_guards_complete_the_error_catalog
        """
        scope = review_decided_for_one_of_three_principals

        planned = fixtures.create_promotion(
            api,
            scope["authorization"]["id"],
            window_start=FUTURE_WINDOW_START,
            window_end=FUTURE_WINDOW_END,
            planned_funding_cents=100000,
        )
        response = api.commit_promotion(planned["id"], ACCOUNT_MANAGER_HEADERS)

        assert planned["state"] == PromotionState.PLANNED
        assert planned["committed_at"] is None
        validate_error(response, ApiErrorId.AUTHORIZATION_NOT_AUTHORIZED, 409)

    def test_rejecting_the_deal_frees_both_the_agreement_and_the_principal(
        self, api, review_decided_for_one_of_three_principals
    ):
        """The rejection discontinues the awarded slot, which is what the two guards were counting.

        PRD: "Rejection is not merely bookkeeping: every authorization linked to that deal whose
        `authorization_state` is `PENDING_SETUP` is moved to `DISCONTINUED` with `discontinue_reason`
        recorded as `DEAL_REJECTED`, because a slot awarded on the strength of a fee nobody agreed to
        cannot stand."

        PRD: "Both termination paths cascade identically: every commission agreement of this principal
        whose `status` is `ACTIVE` is set to `TERMINATED`."

        Design: Corner/errors/presentation_and_negotiation_guards_complete_the_error_catalog
        """
        scope = review_decided_for_one_of_three_principals
        validate_error(
            attempt_agreement_termination(api, scope),
            ApiErrorId.AGREEMENT_HAS_OPEN_NEGOTIATION,
            409,
        )
        validate_error(
            attempt_principal_termination(api, scope),
            ApiErrorId.PRINCIPAL_HAS_LIVE_AUTHORIZATIONS,
            409,
        )

        rejected = reject_the_winning_deal(api, scope)

        assert rejected["state"] == DealState.REJECTED
        authorization = fixtures.get_authorization(api, scope["authorization"]["id"])
        assert authorization["authorization_state"] == AuthorizationState.DISCONTINUED
        assert authorization["discontinue_reason"] == DiscontinueReason.DEAL_REJECTED
        terminated_agreement = get_success_data(attempt_agreement_termination(api, scope), 200)
        assert terminated_agreement["status"] == AgreementStatus.TERMINATED
        terminated_principal = get_success_data(attempt_principal_termination(api, scope), 200)
        assert terminated_principal["status"] == PrincipalStatus.TERMINATED
