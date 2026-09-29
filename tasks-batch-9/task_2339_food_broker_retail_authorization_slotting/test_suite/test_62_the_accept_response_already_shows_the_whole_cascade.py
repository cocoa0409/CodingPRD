"""Immediate consistency: the accept body, and every read after it, agree without a retry."""

import pytest

from test_helpers import (
    AuthorizationState,
    CreditPosture,
    DealState,
    PresentationStatus,
    SettlementStateAuthorization,
    UPC_1,
    UPC_2,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
)
from test_helpers import factories as F

CHAIN_STORES = 1200
BUDGET_CENTS = 20000000
FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 400
ITEM_COUNT = 2
FORECAST_UNITS = 100000
GROSS_FEE_CENTS = 10000000
VOLUME_CREDIT_CENTS = 300000
NET_BEFORE_ADMIN_CENTS = 9700000
ADMIN_FEE_CENTS = 145500
QUOTED_FEE_CENTS = 9845500
SHARE_CENTS = 4922750
COST_PER_UNIT = 98.46
EXPECTED_RATIO_BPS = 4922


@pytest.fixture
def two_awarded_items_on_one_proposed_deal(api):
    """Both items win a slot, so one deal owns two PENDING_SETUP authorizations."""
    retailer = fixtures.create_retailer(api, total_store_count=CHAIN_STORES)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    first = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    second = fixtures.validated_item(
        api,
        principal["id"],
        retailer["id"],
        upc=UPC_2,
        description="Frozen Empanadas 10ct",
        case_pack_units=10,
        list_price_cents=2000,
        unit_cost_cents=1150,
    )
    item_ids = [first["id"], second["id"]]
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=2)
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], item_ids
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=ITEM_COUNT,
        forecast_annual_units=FORECAST_UNITS,
        amortization_periods=4,
    )
    review = fixtures.lock_and_decide(api, review["id"], retailer["id"], item_ids)
    return {
        "retailer": retailer,
        "principal": principal,
        "items": [first, second],
        "review": review,
        "presentation": presentation,
        "deal": deal,
        "pinned_version": fixtures.get_principal(api, principal["id"])["version"],
        "buyer_headers": make_retailer_buyer_headers(retailer["id"]),
    }


def accept_the_standing_offer(api, scope):
    return get_success_data(
        api.accept_deal(
            scope["deal"]["id"],
            F.accept_payload(scope["pinned_version"]),
            scope["buyer_headers"],
        ),
        200,
    )


def linked_authorizations(api, scope):
    return fixtures.list_authorizations(api, slotting_deal_id=scope["deal"]["id"])


class TestTheAcceptResponseAlreadyShowsTheWholeCascade:
    def test_the_standing_quote_sits_in_the_upper_administration_tier(
        self, api, two_awarded_items_on_one_proposed_deal
    ):
        """Two items in scope double the gross, which pushes the net past the tier-1 ceiling.

        PRD: "`gross_fee_cents` is `current_fee_per_store_cents` multiplied by
        `store_count_in_scope` and then by `item_count_in_scope`."

        PRD: "The tier is keyed on the net figure *before* the administration fee is added — never on
        `quoted_fee_cents` and never on `accepted_fee_cents` — even though the administration fee is itself
        part of the quoted figure."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        scope = two_awarded_items_on_one_proposed_deal

        deal = fixtures.get_deal(api, scope["deal"]["id"])

        assert deal["state"] == DealState.PROPOSED
        assert deal["gross_fee_cents"] == GROSS_FEE_CENTS
        assert deal["volume_credit_cents"] == VOLUME_CREDIT_CENTS
        assert deal["net_before_admin_cents"] == NET_BEFORE_ADMIN_CENTS
        assert deal["admin_fee_cents"] == ADMIN_FEE_CENTS
        assert deal["quoted_fee_cents"] == QUOTED_FEE_CENTS

    def test_the_award_left_two_authorizations_waiting_on_the_same_deal(
        self, api, two_awarded_items_on_one_proposed_deal
    ):
        """The deck is ACCEPTED and both slots are booked, but nothing is authorized yet.

        PRD: "Every presentation of this review with at least one awarded item moves `status` from
        `SUBMITTED` to `ACCEPTED` and has `authorized_item_count` set to the number of its own items that
        were awarded, and its live deal stays in `PROPOSED` or `COUNTERED` and thereby becomes acceptable."

        PRD: "Its `authorized_store_count` is the linked deal's `store_count_in_scope`; when there is no
        linked deal, it is the `default_store_count` supplied on the decision."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        scope = two_awarded_items_on_one_proposed_deal

        rows = linked_authorizations(api, scope)

        assert len(rows) == 2
        for row in rows:
            assert row["authorization_state"] == AuthorizationState.PENDING_SETUP
            assert row["settlement_state"] == SettlementStateAuthorization.UNBILLED
            assert row["authorized_store_count"] == STORE_COUNT
        deck = get_success_data(
            api.get_presentation(scope["presentation"]["id"], scope["buyer_headers"]), 200
        )
        assert deck["status"] == PresentationStatus.ACCEPTED
        assert deck["authorized_item_count"] == ITEM_COUNT

    def test_the_accept_response_itself_reports_the_state_after_the_auto_advance(
        self, api, two_awarded_items_on_one_proposed_deal
    ):
        """The body never shows the transient ACCEPTED state, nor a null accepted fee.

        PRD: "The deal does not rest in `ACCEPTED`: the system advances it `ACCEPTED` → `AMORTIZING`
        inside the same request, which is where the cascade of §3.6 fires, and the principal's `version`
        advances by one."

        PRD: "One field is not an integer: `cost_per_forecast_unit_cents` is a decimal number rounded half
        up to exactly two decimal places, and it is null when the deal carries no forecast volume."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        scope = two_awarded_items_on_one_proposed_deal

        accepted = accept_the_standing_offer(api, scope)

        assert accepted["state"] == DealState.AMORTIZING
        assert accepted["state"] != DealState.ACCEPTED
        assert accepted["accepted_fee_cents"] == QUOTED_FEE_CENTS
        assert accepted["unamortized_balance_cents"] == QUOTED_FEE_CENTS
        assert accepted["cost_per_forecast_unit_cents"] == pytest.approx(COST_PER_UNIT)

    def test_the_very_next_read_shows_both_authorizations_already_moved_and_funded(
        self, api, two_awarded_items_on_one_proposed_deal
    ):
        """No read-after-write delay: the shares are allocated before the accept returns.

        PRD: "The second hop allocates the money: `slotting_share_cents` distributes `accepted_fee_cents`
        across those authorizations by taking the base share as `accepted_fee_cents` divided by the number
        of linked authorizations, floored to whole cents, computing the remainder as `accepted_fee_cents`
        less the base share multiplied by that count, and giving one extra cent to each of the first
        *remainder* authorizations in an order defined by `created_at` ascending and then item `upc`
        ascending."

        PRD: "Across a deal's authorizations, the sum of `slotting_share_cents` equals the deal's
        `accepted_fee_cents` exactly, with no cent lost or duplicated."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        scope = two_awarded_items_on_one_proposed_deal
        accepted = accept_the_standing_offer(api, scope)

        rows = linked_authorizations(api, scope)

        assert len(rows) == 2
        for row in rows:
            assert row["authorization_state"] == AuthorizationState.AUTHORIZED
            assert row["settlement_state"] == SettlementStateAuthorization.SLOTTING_AMORTIZING
            assert row["slotting_share_cents"] == SHARE_CENTS
        assert sum(row["slotting_share_cents"] for row in rows) == accepted["accepted_fee_cents"]

    def test_the_principals_aggregates_are_already_re_derived_when_the_accept_returns(
        self, api, two_awarded_items_on_one_proposed_deal
    ):
        """Committed money, open liability, the ratio and the posture all land in the same request.

        PRD: "Every derived aggregate on a principal — committed slotting, open liability, open deductions,
        at-risk authorizations — is recomputed on the same request that changes its inputs, and those
        aggregates feed a credit posture that can freeze a principal out of further commitments before the
        broker over-extends itself."

        PRD: "`credit_posture` is then derived against two inclusive thresholds and one count: it is
        `RESTRICTED` when `at_risk_authorization_count` is 2 or more, or `liability_ratio_bps` is 7,500 or
        more"

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        scope = two_awarded_items_on_one_proposed_deal
        accept_the_standing_offer(api, scope)

        principal = fixtures.get_principal(api, scope["principal"]["id"])

        assert principal["slotting_budget_cents"] == BUDGET_CENTS
        assert principal["slotting_committed_cents"] == QUOTED_FEE_CENTS
        assert principal["open_slotting_liability_cents"] == QUOTED_FEE_CENTS
        assert principal["liability_ratio_bps"] == EXPECTED_RATIO_BPS
        assert principal["credit_posture"] == CreditPosture.NORMAL
        assert principal["at_risk_authorization_count"] == 0
        assert principal["version"] == scope["pinned_version"] + 1

    def test_trade_spend_was_recomputed_inside_the_accept_and_not_by_a_later_job(
        self, api, two_awarded_items_on_one_proposed_deal
    ):
        """No promotion has settled, so the whole trade spend is the slotting share.

        PRD: "Each authorization's `trade_spend_total_cents` is then recomputed as `slotting_share_cents`
        plus `promo_settled_funding_cents`."

        PRD: "Several operations in this system mutate more than one entity. Those cascades are not
        best-effort: they complete inside the same request that triggered them, in the order the workflow
        narrative states, and they are what keeps four conserved quantities true at all times."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        scope = two_awarded_items_on_one_proposed_deal
        accept_the_standing_offer(api, scope)
        first_row = linked_authorizations(api, scope)[0]

        authorization = fixtures.get_authorization(api, first_row["id"])

        assert authorization["promo_settled_funding_cents"] == 0
        assert authorization["slotting_share_cents"] == SHARE_CENTS
        assert authorization["trade_spend_total_cents"] == SHARE_CENTS

    def test_repeating_every_read_returns_the_same_values_with_no_convergence(
        self, api, two_awarded_items_on_one_proposed_deal
    ):
        """Nothing settles late, so a second look at the deal, the slots and the principal is identical.

        PRD: "On a slotting deal, `accepted_fee_cents` always equals `recovered_cents` plus
        `unamortized_balance_cents` plus `written_off_cents` — after every amortization posting, every
        reversal and every write-off."

        PRD: "Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on
        every change to the resource, and `version`, an integer that is 1 when the resource is created and
        increases by exactly one on every mutation of that resource."

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        scope = two_awarded_items_on_one_proposed_deal
        accepted = accept_the_standing_offer(api, scope)
        first_deal = fixtures.get_deal(api, scope["deal"]["id"])
        first_rows = linked_authorizations(api, scope)
        first_principal = fixtures.get_principal(api, scope["principal"]["id"])

        second_deal = fixtures.get_deal(api, scope["deal"]["id"])
        second_rows = linked_authorizations(api, scope)
        second_principal = fixtures.get_principal(api, scope["principal"]["id"])

        assert first_deal == accepted
        assert second_deal == first_deal
        assert second_rows == first_rows
        assert second_principal == first_principal
        assert first_deal["accepted_fee_cents"] == (
            first_deal["recovered_cents"]
            + first_deal["unamortized_balance_cents"]
            + first_deal["written_off_cents"]
        )
