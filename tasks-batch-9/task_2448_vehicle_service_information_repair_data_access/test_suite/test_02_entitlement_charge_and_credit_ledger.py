"""Entitlement pricing, the data-credit ledger and the constraint ladder.

Covers per-line rounding of the subscription charge, the divergence between the
provisional charge and the final settlement, the conservation identity that ties
the ledger together, and the precedence of the seat cap over affordability.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    EntitlementStatus,
    SettlementStatus,
    ShopTier,
    assert_data_credit_conservation,
    assert_entitlement,
    assert_seat_counts,
    assert_shop,
    factories,
    fixtures,
    make_platform_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubscriptionChargePerLineRounding:
    """Rounding happens once per covered-area line, never once at the end."""

    def test_three_covered_areas_charge_84999_not_85000(self, api):
        """Each line rounds on its own, so the total is one cent short of 85,000.

        PRD 3.3: "the per-line base is 33,333 and a third cents, the per-line
        product is 28,333.3333 cents, the line charge rounds to 28,333, and
        `charged_cents` is 84,999" — "whereas summing the exact line values and
        rounding once at the end would have produced 85,000, which is not the
        specified answer".

        Design: Difficulty/combinatorial_formula/entitlement_charge_per_line_rounding_order_is_pinned
        """
        ctx = fixtures.build_funded_shop(api, seat_cap=10)

        entitlement = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"], seats_total=3
                ),
                ctx["manager_headers"],
            ),
            201,
        )

        assert_entitlement(entitlement)
        assert entitlement["charged_cents"] == 84999
        assert entitlement["charged_cents"] != 85000

    def test_the_rounded_total_is_exactly_what_the_ledger_is_debited(self, api):
        """The debit equals the stamped charge and the seat ledger opens empty.

        PRD 3.3: "On success the platform stamps `charged_cents`, debits the
        shop's `data_credit_balance_cents` by that amount and advances the shop's
        `version` by 1", and "the new entitlement opens with `status` of
        `PENDING`, `settlement_status` of `UNSETTLED`, `settled_cents` of 0,
        `seats_assigned` of 0 and `seats_available` equal to `seats_total`".

        Design: Difficulty/combinatorial_formula/entitlement_charge_per_line_rounding_order_is_pinned
        """
        ctx = fixtures.build_funded_shop(api, seat_cap=10)

        entitlement = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"], seats_total=3
                ),
                ctx["manager_headers"],
            ),
            201,
        )
        shop = fixtures.refresh_shop(api, ctx)

        assert_shop(shop)
        assert entitlement["status"] == EntitlementStatus.PENDING
        assert entitlement["settlement_status"] == SettlementStatus.UNSETTLED
        assert entitlement["settled_cents"] == 0
        assert_seat_counts(entitlement, 0, 3)
        assert shop["data_credit_balance_cents"] == 115001
        assert shop["funded_credit_total_cents"] == 200000
        assert_data_credit_conservation(shop, entitlement)


class TestProvisionalVersusFinalSubscriptionCharge:
    """The purchase-time variant and the settlement-time variant differ."""

    def test_cancelling_ten_days_into_a_31_day_window_settles_27419(self, api):
        """The final variant prorates the already-stamped provisional charge.

        PRD 3.4: "`settled_cents` is the already-stamped `charged_cents`
        multiplied by the elapsed day count and divided by the window day count,
        rounded half up once to whole cents" — worked through, "`settled_cents`
        is 84,999 multiplied by 10, divided by 31, rounded half up, giving
        27,419".

        Design: Difficulty/dual_variant_calc/entitlement_charge_provisional_vs_final_subscription_divergence
        """
        ctx = fixtures.build_settled_entitlement(
            api, settle_at="2026-08-11T00:00:00Z", cancel_reason="SHOP_EXIT"
        )
        entitlement = ctx["entitlement"]

        assert_entitlement(entitlement)
        assert entitlement["charged_cents"] == 84999
        assert entitlement["settled_cents"] == 27419
        assert entitlement["settlement_status"] == SettlementStatus.SETTLED
        assert entitlement["status"] == EntitlementStatus.CANCELLED

    def test_the_two_variants_diverge_by_the_refunded_difference(self, api):
        """The refund is the gap between the two variants of the same charge.

        PRD 3.4: "In both variants the refund credited back to the shop is
        `charged_cents` minus `settled_cents`; the same entitlement that was worth
        84,999 provisionally is worth 27,419 finally, and the 57,580 difference
        returns to `data_credit_balance_cents`." That leaves the balance at 172,581
        while `funded_credit_total_cents` stays at 200,000.

        Design: Difficulty/dual_variant_calc/entitlement_charge_provisional_vs_final_subscription_divergence
        """
        ctx = fixtures.build_settled_entitlement(
            api, settle_at="2026-08-11T00:00:00Z", cancel_reason="SHOP_EXIT"
        )
        entitlement = ctx["entitlement"]
        shop = ctx["shop"]

        assert entitlement["charged_cents"] - entitlement["settled_cents"] == 57580
        assert shop["data_credit_balance_cents"] == 172581
        assert shop["funded_credit_total_cents"] == 200000
        assert_data_credit_conservation(shop, entitlement)


class TestDataCreditConservation:
    """The ledger identity holds at every checkpoint of a purchase's life."""

    def test_conservation_holds_at_funding_and_immediately_after_purchase(self, api):
        """Balance plus the unsettled charge always returns the funded total.

        PRD 3.3: "Taking the shop's `data_credit_balance_cents`, adding the
        `charged_cents` of every entitlement of that shop whose
        `settlement_status` is `UNSETTLED`, and adding the `settled_cents` of
        every entitlement whose `settlement_status` is `SETTLED`, must yield
        exactly `funded_credit_total_cents`." The worked run starts by funding
        200,000 cents "and the balance and funded total are both 200,000".

        Design: Difficulty/compensating_invariant/data_credit_conservation_across_funding_charge_and_settlement
        """
        ctx = fixtures.build_licensed_catalogue(api)
        fixtures.add_shop(api, ctx, funding_cents=None)
        admin = make_platform_admin_headers()

        funded = validate_success(
            api.fund_shop_credit(
                ctx["shop"]["id"], factories.credit_funding_payload(200000), admin
            )
        )
        assert funded["data_credit_balance_cents"] == 200000
        assert funded["funded_credit_total_cents"] == 200000
        assert_data_credit_conservation(funded)

        entitlement = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(ctx["shop"]["id"], ctx["license"]["id"]),
                ctx["manager_headers"],
            ),
            201,
        )
        shop = fixtures.refresh_shop(api, ctx)

        assert entitlement["charged_cents"] == 84999
        assert entitlement["settlement_status"] == SettlementStatus.UNSETTLED
        assert entitlement["settled_cents"] == 0
        assert shop["data_credit_balance_cents"] == 115001
        assert_data_credit_conservation(shop, entitlement)

    def test_conservation_holds_after_settlement_and_funding_never_decreases(
        self, api
    ):
        """Settlement swaps the outstanding term without disturbing the identity.

        PRD 3.3: "`funded_credit_total_cents` is a lifetime total and never
        decreases for any reason." Gateway fees stay out of the identity, since
        "secure-gateway access fees accrue as a separate running total and are
        never netted against the data-credit balance".

        Design: Difficulty/compensating_invariant/data_credit_conservation_across_funding_charge_and_settlement
        """
        ctx = fixtures.build_licensed_catalogue(api)
        fixtures.add_shop(api, ctx, funding_cents=None)
        admin = make_platform_admin_headers()
        validate_success(
            api.fund_shop_credit(
                ctx["shop"]["id"], factories.credit_funding_payload(200000), admin
            )
        )
        fixtures.add_entitlement(api, ctx, activate=True)
        fixtures.set_clock(api, ctx, "2026-08-11T00:00:00Z")

        cancelled = validate_success(
            api.cancel_entitlement(
                ctx["entitlement"]["id"],
                factories.reason_payload("consolidating vendors"),
                ctx["manager_headers"],
            )
        )
        shop = fixtures.refresh_shop(api, ctx)

        assert cancelled["settled_cents"] == 27419
        assert cancelled["settlement_status"] == SettlementStatus.SETTLED
        assert shop["data_credit_balance_cents"] == 172581
        assert shop["funded_credit_total_cents"] == 200000
        assert shop["gateway_fee_accrued_cents"] == 0
        assert_data_credit_conservation(shop, cancelled)


class TestSeatCapOutranksAffordability:
    """The last rung of the ladder is affordability, so the cap speaks first."""

    def test_a_seat_cap_breach_is_reported_even_when_credit_is_also_short(self, api):
        """Eight seats against a cap of five is refused on the cap, not the money.

        PRD 3.3: "Any of those three failures returns `ERR_SEAT_CAP_EXCEEDED`
        (HTTP 422)", while affordability comes last — "Only after every other
        check has passed does the platform test whether the shop can pay". "This
        is the last rung of the ladder in §2.7, so a shop with an empty balance
        that also breached its seat cap hears about the seat cap first."

        Design: Difficulty/priority_pair_validation_conflict/create_entitlement_seat_cap_beats_insufficient_data_credit
        """
        ctx = fixtures.build_funded_shop(
            api, funding_cents=1000, tier=ShopTier.BASIC, shop_name="Thin Credit Auto"
        )

        response = api.create_entitlement(
            factories.entitlement_payload(
                ctx["shop"]["id"], ctx["license"]["id"], seats_total=8
            ),
            ctx["manager_headers"],
        )

        error = validate_error(response, ApiErrorId.SEAT_CAP_EXCEEDED, 422)
        assert error["error_id"] != ApiErrorId.INSUFFICIENT_DATA_CREDIT

    def test_a_refused_purchase_leaves_the_ledger_and_the_listing_untouched(self, api):
        """No charge is stamped and no entitlement row survives the refusal.

        PRD 3.3: the debit of `data_credit_balance_cents` happens only "On
        success", and affordability is tested only "after every other check has
        passed", so a purchase refused on the seat cap moves nothing.

        Design: Difficulty/priority_pair_validation_conflict/create_entitlement_seat_cap_beats_insufficient_data_credit
        """
        ctx = fixtures.build_funded_shop(
            api, funding_cents=1000, tier=ShopTier.BASIC, shop_name="Thin Credit Auto"
        )
        validate_error(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"], seats_total=8
                ),
                ctx["manager_headers"],
            ),
            ApiErrorId.SEAT_CAP_EXCEEDED,
            422,
        )

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 1000
        assert shop["funded_credit_total_cents"] == 1000

        rows, meta = validate_paginated(
            api.list_entitlements(ctx["manager_headers"], {"shop_id": ctx["shop"]["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
