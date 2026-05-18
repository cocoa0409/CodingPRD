"""Commission split arithmetic and PROVISIONAL vs FINAL variants.

Cites PRD §3.8 (Commission Splits and Net-to-Seller). The arithmetic is
pinned order: gross → buyer-side → listing-side residual → per-side
agent/brokerage split.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_offer,
    api_client,
    assert_commission_residual_invariants,
    assert_commission_split,
    attach_contingency,
    close_listing,
    get_listing_state,
    list_commission_splits,
    make_listing_agent_headers,
    patch_agent_payload,
    setup_listing_under_contract,
    setup_sold_listing,
    submit_offer,
    validate_success,
    waive_contingency,
)


def _filter(splits, variant):
    return [s for s in splits if s.get("variant") == variant]


class TestCommissionSplitProvisional:
    """PRD §3.8 PROVISIONAL emitted at acceptance."""

    def test_provisional_emitted_on_acceptance(self, api):
        """PRD §3.6: 'A CommissionSplit row with variant of PROVISIONAL
        is emitted using the commission-split calculation in §3.8.'

        Claim: After accept, exactly one CommissionSplit row with
        variant=PROVISIONAL exists for the listing.
        """
        state = setup_listing_under_contract(
            list_price_cents=50_000_000,
            co_op_pct=0.025,
            total_commission_pct=0.06,
            listing_agent_split=0.70,
            buyer_agent_split=0.70,
        )
        splits = list_commission_splits(
            state["accepted_listing"]["id"], variant="PROVISIONAL",
        )
        prov = _filter(splits, "PROVISIONAL")
        assert len(prov) == 1, (
            f"PRD §3.6 must emit exactly one PROVISIONAL row, got "
            f"{len(prov)}: {splits}"
        )
        row = prov[0]
        assert_commission_split(row)

    def test_provisional_arithmetic_exact_cents(self, api):
        """PRD §3.8: pinned order — gross = round(sale * total);
        buyer_side = round(sale * co_op); listing_side = gross -
        buyer_side; listing_agent = round(listing_side * la_split);
        buyer_agent = round(buyer_side * ba_split).

        Claim: For sale=50,000,000, co_op=0.025, total=0.06,
        la_split=0.70, ba_split=0.70:
          gross = round(50_000_000 * 0.06)   = 3,000,000
          buyer_side = round(50_000_000 * 0.025) = 1,250,000
          listing_side = 3,000,000 - 1,250,000 = 1,750,000
          listing_agent = round(1_750_000 * 0.70) = 1,225,000
          listing_brokerage = 1_750_000 - 1_225_000 = 525,000
          buyer_agent = round(1_250_000 * 0.70) = 875,000
          buyer_brokerage = 1_250_000 - 875_000 = 375,000

        # difficulty: dual_variant_calc/commission_split_provisional_vs_final_on_brokerage_split_change
        """
        state = setup_listing_under_contract(
            list_price_cents=50_000_000,
            co_op_pct=0.025,
            total_commission_pct=0.06,
            listing_agent_split=0.70,
            buyer_agent_split=0.70,
        )
        splits = list_commission_splits(
            state["accepted_listing"]["id"], variant="PROVISIONAL",
        )
        prov = _filter(splits, "PROVISIONAL")
        assert len(prov) == 1
        row = prov[0]
        assert row["sale_price_cents"] == 50_000_000
        assert row["gross_commission_cents"] == 3_000_000
        assert row["buyer_side_cents"] == 1_250_000
        assert row["listing_side_cents"] == 1_750_000
        assert row["listing_agent_cents"] == 1_225_000
        assert row["listing_brokerage_cents"] == 525_000
        assert row["buyer_agent_cents"] == 875_000
        assert row["buyer_brokerage_cents"] == 375_000
        assert_commission_residual_invariants(row)

    def test_provisional_residual_invariants(self, api):
        """PRD §3.8: 'a residual assignment that guarantees the two
        side totals add up exactly to the gross, with no penny drift'.

        Claim: For an arbitrary sale-price+rate combination, the
        residual identity holds.

        # difficulty: combinatorial_formula/co_op_commission_residual_assignment_ordering
        # difficulty: compensating_invariant/commission_split_residual_invariant_cents
        """
        state = setup_listing_under_contract(
            list_price_cents=49_999_999,   # one cent shy of $500k
            co_op_pct=0.025,
            total_commission_pct=0.06,
            listing_agent_split=0.70,
            buyer_agent_split=0.70,
        )
        splits = list_commission_splits(
            state["accepted_listing"]["id"], variant="PROVISIONAL",
        )
        prov = _filter(splits, "PROVISIONAL")
        assert len(prov) == 1
        row = prov[0]
        # PRD §3.8: gross = round_half_up(49_999_999 * 0.06)
        # = 49_999_999 * 0.06 = 2_999_999.94 → round_half_up → 2_999_999
        # (0.94 < 0.5 from the half-cent perspective; actually
        # 2_999_999.94 rounds to 3_000_000 because .94 > .5 of the next
        # cent boundary). Let's recompute carefully:
        # 49_999_999 * 0.06 = 2_999_999.94. round_half_up to nearest
        # integer: 0.94 >= 0.5 → 3_000_000.
        # buyer_side = round_half_up(49_999_999 * 0.025) =
        # round_half_up(1_249_999.975) = 1_250_000 (.975 >= .5).
        # listing_side = 3_000_000 - 1_250_000 = 1_750_000.
        assert row["gross_commission_cents"] == 3_000_000
        assert row["buyer_side_cents"] == 1_250_000
        assert row["listing_side_cents"] == 1_750_000
        # Residual identities — PRD §3.8.
        assert_commission_residual_invariants(row)


class TestCommissionSplitFinal:
    """PRD §3.8 FINAL emitted at close."""

    def test_final_emitted_on_close(self, api):
        """PRD §3.7: 'On close, ... a CommissionSplit row with variant
        of FINAL is emitted'.

        Claim: After successful close, a CommissionSplit row with
        variant=FINAL exists alongside the PROVISIONAL row.
        """
        state = setup_sold_listing()
        splits = list_commission_splits(
            state["sold_listing"]["id"],
        )
        prov = _filter(splits, "PROVISIONAL")
        final = _filter(splits, "FINAL")
        assert len(prov) == 1
        assert len(final) == 1
        assert_commission_split(final[0])
        assert_commission_residual_invariants(final[0])

    def test_provisional_and_final_diverge_on_buyer_agent_split_change(
        self, api,
    ):
        """PRD §3.8: 'The FINAL snapshot is computed at the moment the
        listing transitions from UNDER_CONTRACT to SOLD — i.e., at
        close — and uses each agent's brokerage_split_pct as it stands
        at close. If an agent's brokerage split changed between
        acceptance and close, the FINAL row diverges from the
        PROVISIONAL row even though the sale price is identical; the
        PROVISIONAL row is not retroactively updated, and both rows
        coexist in storage.'

        Claim: BUYER_AGENT.brokerage_split_pct moves from 0.70 to
        0.65 between accept and close → PROVISIONAL.buyer_agent_cents
        (875_000) ≠ FINAL.buyer_agent_cents (812_500); PROVISIONAL is
        NOT mutated.

        # difficulty: dual_variant_calc/commission_split_provisional_vs_final_on_brokerage_split_change
        # difficulty: compensating_invariant/commission_split_residual_invariant_cents
        """
        state = setup_listing_under_contract(
            list_price_cents=50_000_000,
            co_op_pct=0.025,
            total_commission_pct=0.06,
            listing_agent_split=0.70,
            buyer_agent_split=0.70,
        )
        # Edit buyer agent's split to 0.65 via MlsAdmin.
        ba = state["buyer_agent"]
        resp = api.patch_agent(
            ba["id"],
            patch_agent_payload(version=ba["version"], brokerage_split_pct=0.65),
            TEST_USERS["mls_admin_headers"],
        )
        validate_success(resp, 200)
        # Re-fetch the listing for current version, then close.
        listing_now = get_listing_state(state["accepted_listing"]["id"])
        close_listing(
            listing_now, state["listing_agent"],
            version=listing_now["version"],
        )
        splits = list_commission_splits(listing_now["id"])
        prov = _filter(splits, "PROVISIONAL")
        final = _filter(splits, "FINAL")
        assert len(prov) == 1 and len(final) == 1
        prov_row = prov[0]
        final_row = final[0]
        # PROVISIONAL values per §3.8 pinned arithmetic.
        assert prov_row["buyer_agent_cents"] == 875_000
        assert prov_row["buyer_brokerage_cents"] == 375_000
        assert prov_row["listing_agent_cents"] == 1_225_000
        assert prov_row["listing_brokerage_cents"] == 525_000
        # FINAL: buyer_side_cents still 1_250_000 (sale unchanged);
        # buyer_agent_cents = round_half_up(1_250_000 * 0.65) = 812_500;
        # buyer_brokerage_cents = 1_250_000 - 812_500 = 437_500.
        assert final_row["buyer_agent_cents"] == 812_500
        assert final_row["buyer_brokerage_cents"] == 437_500
        # Listing side unchanged (split unchanged).
        assert final_row["listing_agent_cents"] == 1_225_000
        assert final_row["listing_brokerage_cents"] == 525_000
        # PROVISIONAL must NOT be retroactively updated.
        assert prov_row["buyer_agent_cents"] != final_row["buyer_agent_cents"]
        assert_commission_residual_invariants(prov_row)
        assert_commission_residual_invariants(final_row)

    def test_gross_commission_identical_across_provisional_and_final(
        self, api,
    ):
        """PRD §3.8 + PRD §2.7: With sale_price unchanged, gross
        commission cents is identical across PROVISIONAL and FINAL —
        the residual identity holds within each row.

        # difficulty: compensating_invariant/commission_split_residual_invariant_cents
        """
        state = setup_sold_listing(
            list_price_cents=50_000_000,
            co_op_pct=0.025,
            total_commission_pct=0.06,
            listing_agent_split=0.70,
            buyer_agent_split=0.70,
        )
        splits = list_commission_splits(state["sold_listing"]["id"])
        prov = _filter(splits, "PROVISIONAL")[0]
        final = _filter(splits, "FINAL")[0]
        assert prov["sale_price_cents"] == final["sale_price_cents"] == 50_000_000
        assert prov["gross_commission_cents"] == final["gross_commission_cents"] == 3_000_000


class TestProvisionalNetToSeller:
    """PRD §3.8 provisional_net_to_seller_cents at acceptance time."""

    def test_provisional_net_to_seller_computed(self, api):
        """PRD §3.8: 'The provisional net-to-seller, stored on the
        accepted offer as provisional_net_to_seller_cents, is
        calculated at acceptance time as the offer's offer_price_cents
        minus the offer's estimated_seller_concessions_cents, minus
        the buyer-side commission obtained by multiplying
        offer_price_cents by the listing's co_op_pct and rounding
        half-up to a whole cent, minus the listing-side commission
        obtained by multiplying offer_price_cents by the difference
        between the listing's total_commission_pct and co_op_pct and
        rounding half-up to a whole cent.'

        Claim: For offer_price=50_000_000, est_concessions=100_000,
        co_op=0.025, total=0.06:
          buyer-side = round(50_000_000 * 0.025) = 1_250_000
          listing-side = round(50_000_000 * (0.06 - 0.025))
                       = round(50_000_000 * 0.035) = 1_750_000
          net = 50_000_000 - 100_000 - 1_250_000 - 1_750_000 = 46_900_000

        # difficulty: dual_variant_calc/offer_net_to_seller_provisional_vs_final_on_concession_drift
        """
        from test_helpers import setup_listing_and_buyer
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer(
            list_price_cents=50_000_000,
            co_op_pct=0.025,
            total_commission_pct=0.06,
        )
        offer = submit_offer(
            listing, buyer, ba,
            offer_price_cents=50_000_000,
            earnest_money_cents=1_000_000,
            estimated_seller_concessions_cents=100_000,
        )
        accepted = accept_offer(listing, offer, la)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["provisional_net_to_seller_cents"] == 46_900_000, (
            f"PRD §3.8 provisional net mismatch: got "
            f"{accepted['provisional_net_to_seller_cents']!r}, expected 46_900_000"
        )
