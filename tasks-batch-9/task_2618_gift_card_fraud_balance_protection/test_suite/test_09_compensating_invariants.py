"""Two conserved quantities, each restored exactly by its compensating operation.

The first is one card's signed ledger sum under a redemption reversal; the second is the
portfolio-wide net funded liability under a claim approval and its rescission.
"""

from test_helpers import assert_signed_amount
from test_helpers.fixtures import (
    create_rack,
    create_store,
    decide_claim,
    file_claim,
    funded_physical_card,
    open_period,
    read_card,
    read_claim,
    read_exposure_summary,
    read_period,
    redeem,
    rescind_claim,
    reverse,
    total_count,
)
from test_helpers.test_users import (
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)


class TestReversalConservesTheLedgerSum:
    """"current_balance_cents is the sum of every event's signed amount"."""

    def _redeemed_card(self, client):
        """A 12345-cent card with one 4321-cent redemption at a second store, leaving 8024."""
        store1 = create_store(client, name="Prairie Books", region_code="MW", address_line="14 Prairie Ln")
        store2 = create_store(client, name="Airport News", region_code="MW", address_line="2 Terminal C")
        rack = create_rack(client, store1["id"], rack_label="RACK-P1", expected_card_count=6)
        card = funded_physical_card(client, 12345, store=store1, rack=rack)["card"]
        redemption = redeem(
            client, card["id"], 4321, store2["id"], pos_terminal_id="T-99", memo="unauthorized"
        )
        return {"card_id": card["id"], "redemption": redemption}

    def test_the_signed_sum_equals_the_balance_before_any_compensation(self, client):
        """"The debit kinds, whose signed_amount_cents is the negated amount, are REDEMPTION,
        REISSUE_DEBIT and REISSUE_CREDIT_REVERSAL", so 12345 plus -4321 is the 8024 the card
        reports.

        Design: Difficulty/compensating_invariant/redemption_reversal_conserves_card_ledger_signed_sum
        """
        world = self._redeemed_card(client)

        card = read_card(client, world["card_id"])
        assert card["current_balance_cents"] == 8024
        assert card["total_loaded_cents"] == 12345
        assert card["total_redeemed_cents"] == 4321
        assert world["redemption"]["signed_amount_cents"] == -4321
        assert 12345 + (-4321) == card["current_balance_cents"]
        assert_signed_amount(world["redemption"])

    def test_the_reversal_restores_the_balance_by_adding_a_credit_row(self, client):
        """"A new REDEMPTION_REVERSAL event is appended, carrying the original's amount as a
        positive movement, with reverses_event_id pointing at the original", and
        total_loaded_cents "is the sum of the raw amounts over the credit kinds only".

        Design: Difficulty/compensating_invariant/redemption_reversal_conserves_card_ledger_signed_sum
        """
        world = self._redeemed_card(client)

        reversal = reverse(
            client,
            world["redemption"]["id"],
            headers=make_risk_manager_headers("risk-1"),
            reversal_reason="chargeback confirmed, redemption unwound",
        )

        assert reversal["type"] == "REDEMPTION_REVERSAL"
        assert reversal["signed_amount_cents"] == 4321
        assert reversal["reverses_event_id"] == world["redemption"]["id"]
        card = read_card(client, world["card_id"])
        assert card["current_balance_cents"] == 12345
        assert card["total_loaded_cents"] == 16666
        assert card["total_redeemed_cents"] == 0
        assert float(card["drawdown_ratio"]) == 0.00
        assert card["activation_state"] == "ACTIVE"

    def test_the_original_row_survives_unmutated_alongside_its_reversal(self, client):
        """"The original event is never mutated — history is append-only", and "An event
        counts as reversed precisely when some other event exists whose reverses_event_id
        points at it".

        Design: Difficulty/compensating_invariant/redemption_reversal_conserves_card_ledger_signed_sum
        """
        world = self._redeemed_card(client)
        admin = make_platform_admin_headers()

        reverse(
            client,
            world["redemption"]["id"],
            headers=make_risk_manager_headers("risk-1"),
            reversal_reason="chargeback confirmed, redemption unwound",
        )

        assert total_count(client.list_ledger_events(admin, {"card_id": world["card_id"]})) == 3
        assert total_count(
            client.list_ledger_events(admin, {"reverses_event_id": world["redemption"]["id"]})
        ) == 1
        original = client.get_ledger_event(world["redemption"]["id"], admin).json()["data"]
        assert original["amount_cents"] == 4321
        assert original["signed_amount_cents"] == -4321


class TestRescindConservesNetFundedLiability:
    """"every compensating pair in the system leaves it unchanged"."""

    def _approved_world(self, client):
        """The four-hop cascade run once: a 20000-cent card drained to 16910 by three
        redemptions, an OPEN period, and a claim approved by risk-7."""
        store1 = create_store(client, name="Harbor Gifts II", region_code="NE", address_line="11 Harbor Way")
        store2 = create_store(client, name="Transit Kiosk II", region_code="NE", address_line="3 Transit Plz")
        rack = create_rack(client, store1["id"], rack_label="RACK-H2", expected_card_count=12)
        card = funded_physical_card(client, 20000, store=store1, rack=rack)["card"]
        for index, amount in enumerate((1010, 1030, 1050), start=1):
            redeem(client, card["id"], amount, store2["id"], memo=f"drain {index}")
        period = open_period(client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", label="2026-08-rescind")
        before = read_exposure_summary(client, period["id"])
        claim = file_claim(
            client,
            card["id"],
            disputed_amount_cents=3090,
            purchased_at="2026-08-01T00:00:00Z",
            headers=make_pos_associate_headers("pos-7"),
            claimant_name="Ines Sartori",
            claimant_contact="ines@example.com",
            purchase_receipt_ref="RCPT-1501",
            packaging_photo_ref="PHOTO-1501",
        )
        approved = decide_claim(
            client,
            claim["id"],
            "APPROVE",
            headers=make_risk_manager_headers("risk-7"),
            decision_note="tampered packaging confirmed",
        )
        after = read_exposure_summary(client, period["id"])
        return {
            "card_id": card["id"],
            "period": period,
            "before": before,
            "claim": approved,
            "after": after,
        }

    def test_the_approval_leaves_the_portfolio_total_unchanged(self, client):
        """"A claim approval moves residual_transfer_cents from the original card to the
        replacement (net zero on the sum), adds reissue_amount_cents to the replacement
        card, and adds that same reissue_amount_cents to unauthorized_writeoff_cents — the
        two additions cancel in the subtraction."

        Design: Difficulty/compensating_invariant/claim_rescind_conserves_net_funded_liability
        """
        world = self._approved_world(client)

        assert world["before"]["net_funded_liability_cents"] == 16910
        assert world["before"]["unauthorized_writeoff_cents"] == 0
        assert world["after"]["net_funded_liability_cents"] == 16910
        assert world["after"]["unauthorized_writeoff_cents"] == 2628
        assert world["claim"]["reissue_amount_cents"] == 2628
        assert 19538 - 2628 == world["after"]["net_funded_liability_cents"]

    def test_the_rescission_restores_the_same_total_a_third_time(self, client):
        """"The matching rescission reverses both legs and restores the pre-approval value
        precisely", the OPEN period having its "unauthorized_writeoff_cents decremented by
        reissue_amount_cents".

        Design: Difficulty/compensating_invariant/claim_rescind_conserves_net_funded_liability
        """
        world = self._approved_world(client)

        rescind_claim(
            client,
            world["claim"]["id"],
            headers=make_liability_accountant_headers(),
            rescind_reason="claimant admitted the redemptions were made by a household member",
        )

        final = read_exposure_summary(client, world["period"]["id"])
        assert final["net_funded_liability_cents"] == 16910
        assert final["unauthorized_writeoff_cents"] == 0
        assert (
            world["before"]["net_funded_liability_cents"]
            == world["after"]["net_funded_liability_cents"]
            == final["net_funded_liability_cents"]
        )
        period = read_period(client, world["period"]["id"])
        assert period["unauthorized_writeoff_cents"] == 0
        assert period["state"] == "OPEN"

    def test_the_rescission_quarantines_the_replacement_and_revives_the_original(self, client):
        """"The replacement card transitions ACTIVE → VOIDED ... having its risk_posture
        forced to FROZEN and its closed_at stamped ... The original card returns CLOSED →
        ACTIVE, its closed_at cleared back to empty."

        Design: Difficulty/compensating_invariant/claim_rescind_conserves_net_funded_liability
        """
        world = self._approved_world(client)
        replacement_id = world["claim"]["reissued_card_id"]

        rescind_claim(
            client,
            world["claim"]["id"],
            headers=make_liability_accountant_headers(),
            rescind_reason="claimant admitted the redemptions were made by a household member",
        )

        replacement = read_card(client, replacement_id)
        assert replacement["activation_state"] == "VOIDED"
        assert replacement["risk_posture"] == "FROZEN"
        assert replacement["current_balance_cents"] == 0
        original = read_card(client, world["card_id"])
        assert original["activation_state"] == "ACTIVE"
        assert original["current_balance_cents"] == 16910
        assert not original["closed_at"]
        voided = client.list_gift_cards(make_platform_admin_headers(), {"activation_state": "VOIDED"})
        assert total_count(voided) == 1

    def test_the_rescinded_claim_retains_its_historical_figures(self, client):
        """The claim "moves APPROVED → RESCINDED, records the reason, and retains
        reissue_amount_cents, residual_transfer_cents and reissued_card_id for audit rather
        than clearing them".

        Design: Difficulty/compensating_invariant/claim_rescind_conserves_net_funded_liability
        """
        world = self._approved_world(client)
        replacement_id = world["claim"]["reissued_card_id"]

        rescinded = rescind_claim(
            client,
            world["claim"]["id"],
            headers=make_liability_accountant_headers(),
            rescind_reason="claimant admitted the redemptions were made by a household member",
        )

        assert rescinded["state"] == "RESCINDED"
        assert rescinded["reissue_amount_cents"] == 2628
        assert rescinded["residual_transfer_cents"] == 16910
        assert rescinded["reissued_card_id"] == replacement_id
        stored = read_claim(client, world["claim"]["id"])
        assert stored["state"] == "RESCINDED"
        assert stored["reissue_amount_cents"] == 2628
