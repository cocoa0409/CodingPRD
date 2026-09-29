"""The two amortization variants applied to identical deals and identical postings."""

import pytest

from test_helpers import UPC_1, UPC_2, AmortizationMethod, AuthorizationState, DealState, fixtures
from test_helpers.assertions import (
    assert_slotting_money_conserved,
    expected_straight_amortization,
    expected_volume_weighted_amortization,
)

FEE_PER_STORE_CENTS = 50000
STORE_COUNT = 100
FORECAST_UNITS = 120000
PERIODS = 6
ACCEPTED_FEE_CENTS = 4756000


@pytest.fixture
def twin_deals(api):
    """Two principals win a slot each in the same review with identical commercials.

    The only difference between the two accepted deals is `amortization_method`, so a
    later posting isolates the divergence the two variants produce.
    """
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    agreement_terms = {
        "base_commission_bps": 500,
        "tier_threshold_cents": 3000000,
        "tier_commission_bps": 300,
    }
    straight_bundle = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"name": "Northwind Foods", "code": "NWF"},
        agreement_overrides=dict(agreement_terms),
    )
    weighted_bundle = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"name": "Southbay Foods", "code": "SBF"},
        agreement_overrides=dict(agreement_terms),
    )
    straight_principal = straight_bundle["principal"]
    weighted_principal = weighted_bundle["principal"]

    straight_item = fixtures.validated_item(
        api, straight_principal["id"], retailer["id"], upc=UPC_1
    )
    weighted_item = fixtures.validated_item(
        api,
        weighted_principal["id"],
        retailer["id"],
        upc=UPC_2,
        description="Mini Pizzas 8ct",
    )

    review = fixtures.opened_review(api, retailer["id"], new_item_slots=4)
    straight_deck = fixtures.submitted_presentation(
        api, review["id"], straight_principal["id"], [straight_item["id"]]
    )
    weighted_deck = fixtures.submitted_presentation(
        api, review["id"], weighted_principal["id"], [weighted_item["id"]]
    )

    common = {
        "store_count_in_scope": STORE_COUNT,
        "item_count_in_scope": 1,
        "forecast_annual_units": FORECAST_UNITS,
        "amortization_periods": PERIODS,
    }
    straight_deal = fixtures.proposed_deal(
        api,
        straight_deck["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        amortization_method=AmortizationMethod.FORECAST_STRAIGHT,
        **common,
    )
    weighted_deal = fixtures.proposed_deal(
        api,
        weighted_deck["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        amortization_method=AmortizationMethod.VOLUME_WEIGHTED,
        **common,
    )

    fixtures.lock_and_decide(
        api, review["id"], retailer["id"], [straight_item["id"], weighted_item["id"]]
    )
    straight_deal = fixtures.accept_as_buyer(
        api, straight_deal["id"], retailer["id"], straight_principal["id"]
    )
    weighted_deal = fixtures.accept_as_buyer(
        api, weighted_deal["id"], retailer["id"], weighted_principal["id"]
    )

    return {
        "retailer": retailer,
        "straight": {
            "principal": straight_principal,
            "deal": straight_deal,
            "authorization": fixtures.authorization_for_deal(api, straight_deal["id"]),
        },
        "weighted": {
            "principal": weighted_principal,
            "deal": weighted_deal,
            "authorization": fixtures.authorization_for_deal(api, weighted_deal["id"]),
        },
    }


def post_one_period(api, retailer_id, authorization_id):
    return fixtures.post_period(
        api,
        authorization_id,
        retailer_id,
        period_index=1,
        reported_store_count=95,
        distributed_store_count=90,
        reported_case_volume=15000,
    )


class TestAmortizationVariantDivergence:
    def test_identical_commercials_freeze_the_same_accepted_fee(self, api, twin_deals):
        """The method never touches the quote ladder, so both fees are the same figure.

        PRD: "Acceptance freezes `accepted_fee_cents` at the standing `quoted_fee_cents`,
        sets `unamortized_balance_cents` to that same figure, and computes
        `cost_per_forecast_unit_cents` as `accepted_fee_cents` divided by
        `forecast_annual_units`, rounded half up to two decimal places — null when
        `forecast_annual_units` is zero."

        Design: Difficulty/dual_variant_calc/amortization_forecast_straight_vs_volume_weighted_divergence
        """
        straight = twin_deals["straight"]["deal"]
        weighted = twin_deals["weighted"]["deal"]

        assert straight["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert weighted["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert straight["gross_fee_cents"] == weighted["gross_fee_cents"] == 5000000
        assert straight["volume_credit_cents"] == weighted["volume_credit_cents"] == 360000
        assert straight["net_before_admin_cents"] == weighted["net_before_admin_cents"] == 4640000
        assert straight["admin_fee_cents"] == weighted["admin_fee_cents"] == 116000
        assert straight["unamortized_balance_cents"] == ACCEPTED_FEE_CENTS
        assert weighted["unamortized_balance_cents"] == ACCEPTED_FEE_CENTS

    def test_forecast_straight_posts_the_floored_period_share(self, api, twin_deals):
        """Period one of six amortizes the floored base share and ignores the volume.

        PRD: "Under `FORECAST_STRAIGHT`, the base amount is `accepted_fee_cents` divided by
        `amortization_periods`, floored to whole cents."

        Design: Difficulty/dual_variant_calc/amortization_forecast_straight_vs_volume_weighted_divergence
        """
        retailer_id = twin_deals["retailer"]["id"]
        entry = post_one_period(api, retailer_id, twin_deals["straight"]["authorization"]["id"])

        assert entry["amortized_amount_cents"] == 792666
        assert entry["amortized_amount_cents"] == expected_straight_amortization(
            ACCEPTED_FEE_CENTS, PERIODS
        )
        deal = fixtures.get_deal(api, twin_deals["straight"]["deal"]["id"])
        assert deal["recovered_cents"] == 792666
        assert deal["unamortized_balance_cents"] == 3963334
        assert deal["periods_posted"] == 1
        assert deal["state"] == DealState.AMORTIZING
        assert_slotting_money_conserved(deal)

    def test_volume_weighted_posts_the_achieved_share_of_the_period_target(self, api, twin_deals):
        """15,000 cases against a 20,000 case target amortizes 7,500 basis points of a period.

        PRD: "Under `VOLUME_WEIGHTED`, the period target is `forecast_annual_units` divided
        by `amortization_periods`, rounded *up* to a whole number of cases."

        Design: Difficulty/dual_variant_calc/amortization_forecast_straight_vs_volume_weighted_divergence
        """
        retailer_id = twin_deals["retailer"]["id"]
        entry = post_one_period(api, retailer_id, twin_deals["weighted"]["authorization"]["id"])

        assert entry["amortized_amount_cents"] == 594500
        assert entry["amortized_amount_cents"] == expected_volume_weighted_amortization(
            ACCEPTED_FEE_CENTS, FORECAST_UNITS, PERIODS, 15000
        )
        deal = fixtures.get_deal(api, twin_deals["weighted"]["deal"]["id"])
        assert deal["recovered_cents"] == 594500
        assert deal["unamortized_balance_cents"] == 4161500
        assert deal["periods_posted"] == 1
        assert deal["state"] == DealState.AMORTIZING
        assert_slotting_money_conserved(deal)

    def test_the_two_variants_diverge_on_the_same_posting(self, api, twin_deals):
        """Same fee, same period, same volume — and a 198,166 cent difference.

        PRD: "The same deal, same posting, will produce materially different amounts under
        the two methods, and therefore reaches `RECOVERED` at different times."

        Design: Difficulty/dual_variant_calc/amortization_forecast_straight_vs_volume_weighted_divergence
        """
        retailer_id = twin_deals["retailer"]["id"]
        straight_entry = post_one_period(
            api, retailer_id, twin_deals["straight"]["authorization"]["id"]
        )
        weighted_entry = post_one_period(
            api, retailer_id, twin_deals["weighted"]["authorization"]["id"]
        )

        assert straight_entry["amortized_amount_cents"] == 792666
        assert weighted_entry["amortized_amount_cents"] == 594500
        assert (
            straight_entry["amortized_amount_cents"] - weighted_entry["amortized_amount_cents"]
            == 198166
        )
        straight_deal = fixtures.get_deal(api, twin_deals["straight"]["deal"]["id"])
        weighted_deal = fixtures.get_deal(api, twin_deals["weighted"]["deal"]["id"])
        assert straight_deal["unamortized_balance_cents"] < weighted_deal["unamortized_balance_cents"]

    def test_the_amortization_method_does_not_move_the_void_rate(self, api, twin_deals):
        """Ten of the hundred authorized stores never took distribution: 1,000 basis points.

        PRD: "Under `STORE_COUNT_BASIS`, `distributed_store_count` is taken from the latest
        live posting, `void_store_count` is `authorized_store_count` less
        `distributed_store_count`, `void_rate_bps` is `void_store_count` multiplied by
        10,000 divided by `authorized_store_count`, floored — or 0 when
        `authorized_store_count` is zero — and `pending_store_count` is 0."

        Design: Difficulty/dual_variant_calc/amortization_forecast_straight_vs_volume_weighted_divergence
        """
        retailer_id = twin_deals["retailer"]["id"]
        post_one_period(api, retailer_id, twin_deals["straight"]["authorization"]["id"])

        authorization = fixtures.get_authorization(
            api, twin_deals["straight"]["authorization"]["id"]
        )
        assert authorization["authorized_store_count"] == STORE_COUNT
        assert authorization["distributed_store_count"] == 90
        assert authorization["void_store_count"] == 10
        assert authorization["pending_store_count"] == 0
        assert authorization["void_rate_bps"] == 1000
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert authorization["periods_reported"] == 1
