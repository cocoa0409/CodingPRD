"""Nine machines, nine declared starting positions."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    AgreementStatus,
    CatalogState,
    ConflictRuleStatus,
    DealState,
    DeductionSettlementState,
    DisputeState,
    PresentationStatus,
    PrincipalStatus,
    PromotionState,
    ReviewStatus,
    fixtures,
    get_success_data,
)
from test_helpers import factories as F

REQUESTED_FEE_PER_STORE_CENTS = 12500
DEDUCTION_AMOUNT_CENTS = 90000


@pytest.fixture
def freshly_created_graph(api):
    """One of every resource whose lifecycle has a declared entry point."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api, name="Northwind Foods", code="NWF")
    partner = fixtures.create_principal(api, name="Sunglow Frozen", code="SGF")
    item = fixtures.create_item(api, principal["id"])
    agreement = fixtures.create_agreement(
        api, principal["id"], retailer["id"], activate=False
    )
    conflict_rule = get_success_data(
        api.create_conflict_rule(
            F.conflict_rule_payload(principal["id"], partner["id"]), BROKER_ADMIN_HEADERS
        ),
        201,
    )
    review = fixtures.create_review(api, retailer["id"])
    presentation = fixtures.create_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deal = fixtures.create_deal(
        api,
        presentation["id"],
        requested_fee_per_store_cents=REQUESTED_FEE_PER_STORE_CENTS,
        store_count_in_scope=400,
        amortization_periods=6,
    )
    deduction = fixtures.create_deduction(
        api, retailer["id"], principal["id"], amount_cents=DEDUCTION_AMOUNT_CENTS
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "agreement": agreement,
        "conflict_rule": conflict_rule,
        "review": review,
        "presentation": presentation,
        "deal": deal,
        "deduction": deduction,
    }


class TestDeclaredInitialStates:
    def test_the_trading_partner_machines_start_where_they_are_declared(
        self, api, freshly_created_graph
    ):
        """A principal is a prospect, a rate card is a draft, a conflict edge is already live.

        PRD: "The principal lifecycle runs `PROSPECT` → `ACTIVE` ⇄ `SUSPENDED` →
        `TERMINATED`, driven by a `BrokerAdmin` supplying the target `status`."

        PRD: "A drafted agreement begins with `status` at `DRAFT` and `activated_at` null, and
        no overlap check is performed at draft time — a broker may prepare as many overlapping
        drafts as it likes."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        assert freshly_created_graph["principal"]["status"] == PrincipalStatus.PROSPECT
        assert freshly_created_graph["agreement"]["status"] == AgreementStatus.DRAFT
        assert freshly_created_graph["agreement"]["activated_at"] is None
        assert freshly_created_graph["conflict_rule"]["status"] == ConflictRuleStatus.ACTIVE

    def test_a_scheduled_review_is_not_an_open_one(self, api, freshly_created_graph):
        """Opening is an explicit transition, so the calendar entry starts closed.

        PRD: "A scheduled review begins with `status` at `SCHEDULED`, `slots_awarded` at 0,
        `slots_remaining` equal to `new_item_slots`, `reopen_count` at 0 and `decided_at` null."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        review = freshly_created_graph["review"]

        assert review["status"] == ReviewStatus.SCHEDULED
        assert review["slots_awarded"] == 0
        assert review["slots_remaining"] == review["new_item_slots"]
        assert review["reopen_count"] == 0
        assert review["decided_at"] is None

    def test_an_item_and_a_deck_both_start_unfinished(self, api, freshly_created_graph):
        """No catalog data yet, and no submission yet.

        PRD: "A new deck begins with `status` at `DRAFT`, `authorized_item_count` at 0 and
        `submitted_at` null, and reports its preparation progress as `prep_completeness_bps`:
        the count of listed items whose `catalog_state` is `VALIDATED`, multiplied by 10,000,
        divided by the total number of listed items, floored to a whole number of basis points."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        assert freshly_created_graph["item"]["catalog_state"] == CatalogState.INCOMPLETE
        assert freshly_created_graph["item"]["catalog_submission_round"] == 0
        assert freshly_created_graph["presentation"]["status"] == PresentationStatus.DRAFT
        assert freshly_created_graph["presentation"]["authorized_item_count"] == 0
        assert freshly_created_graph["presentation"]["prep_completeness_bps"] == 0

    def test_opening_a_negotiation_is_not_yet_making_an_offer(self, api, freshly_created_graph):
        """The deal rests in DRAFT with the retailer's ask merely recorded.

        PRD: "A new deal begins with `state` at `DRAFT`, `round_index` at 0, `last_offer_side`
        null, `accepted_fee_cents`, `recovered_cents`, `written_off_cents`,
        `unamortized_balance_cents` and `periods_posted` all at 0, `reject_reason` null, and
        `current_fee_per_store_cents` seeded from `requested_fee_per_store_cents`."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        deal = freshly_created_graph["deal"]

        assert deal["state"] == DealState.DRAFT
        assert deal["round_index"] == 0
        assert deal["last_offer_side"] is None
        assert deal["accepted_fee_cents"] == 0
        assert deal["recovered_cents"] == 0
        assert deal["written_off_cents"] == 0
        assert deal["unamortized_balance_cents"] == 0
        assert deal["periods_posted"] == 0
        assert deal["reject_reason"] is None
        assert deal["current_fee_per_store_cents"] == REQUESTED_FEE_PER_STORE_CENTS

    def test_a_deduction_starts_on_two_dimensions_at_once(self, api, freshly_created_graph):
        """The money is open and the claim has not been raised — both simultaneously.

        PRD: "A new deduction begins with `settlement_state` at `OPEN`, `dispute_state` at
        `NOT_DISPUTED`, `open_cents` equal to `amount_cents`, `claim_amount_cents`,
        `recovered_cents`, `conceded_cents`, `substantiation_doc_count` and `refile_count` all
        at 0, and `filed_by_user_id`, `approved_by_user_id` and `denial_reason` all null."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        deduction = freshly_created_graph["deduction"]

        assert deduction["settlement_state"] == DeductionSettlementState.OPEN
        assert deduction["dispute_state"] == DisputeState.NOT_DISPUTED
        assert deduction["open_cents"] == DEDUCTION_AMOUNT_CENTS
        assert deduction["claim_amount_cents"] == 0
        assert deduction["recovered_cents"] == 0
        assert deduction["conceded_cents"] == 0
        assert deduction["substantiation_doc_count"] == 0
        assert deduction["refile_count"] == 0
        assert deduction["filed_by_user_id"] is None
        assert deduction["approved_by_user_id"] is None
        assert deduction["denial_reason"] is None

    def test_a_planned_promotion_has_spent_nothing_yet(self, api):
        """The event exists but no money has moved and no slot is held.

        PRD: "A planned event begins with `state` at `PLANNED`, `actual_funding_cents` and
        `settled_funding_cents` at 0, and `committed_at` null."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        scope = fixtures.awarded_authorization_without_deal(api)

        promotion = fixtures.create_promotion(api, scope["authorization"]["id"])

        assert promotion["state"] == PromotionState.PLANNED
        assert promotion["actual_funding_cents"] == 0
        assert promotion["settled_funding_cents"] == 0
        assert promotion["committed_at"] is None
