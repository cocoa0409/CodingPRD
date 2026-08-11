"""Auction settlement: estimate vs final waterfall variants, pinned evaluation
order, and the double-entry ledger invariant across settle/void (PRD §2.8, §3.7)."""
from test_helpers import (
    validate_success,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    register_owner,
    register_bicycle,
    setup_unclaimed_intake,
    create_auction_for_intake,
    setup_open_auction,
    place_bid,
    get_all_ledger_entries,
    assert_ledger_balance,
    assert_ledger_entry,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _settled_auction(
    api,
    appraised_value_cents=100000,
    bid_amount=30000,
    ends_at="2026-06-10T00:00:00Z",
    close_clock="2026-06-13T00:00:00Z",
    serial="ZZZ999",
):
    """UNCLAIMED intake -> auction -> OPEN -> one bid -> close at `close_clock`
    -> settle. Returns dict(org, intake, auction, bid, settled)."""
    scenario = setup_open_auction(
        serial=serial, appraised_value_cents=appraised_value_cents, ends_at=ends_at
    )
    bidder = register_owner("bidder@x.com", "Bidder One")
    bid = place_bid(
        scenario["auction"]["id"], bidder, bid_amount, scenario["auction_version"]
    )
    set_clock(close_clock)
    validate_success(api.close_auction(scenario["auction"]["id"], REGISTRAR))
    settled = validate_success(api.settle_auction(scenario["auction"]["id"], REGISTRAR))
    scenario.update({"bidder": bidder, "bid": bid, "settled": settled})
    return scenario


class TestEstimateVsFinalVariants:
    def test_auction_estimate_vs_final_settlement_late_close(self, api):
        """PRD §3.7: "Estimate and final variants legitimately diverge: a close
        later than the scheduled `ends_at` accrues additional storage days, and the
        winning bid rather than the reserve drives the gross — with a reserve of
        20000 cents and a scheduled end forty days after intake, the estimate
        projects a partner payout of 13275 cents, while a winning bid of 30000
        cents closed on day forty-three settles to a final payout of 21870 cents."

        Design: Difficulty/dual_variant_calc/auction_estimate_vs_final_settlement_late_close
        """
        scenario = _settled_auction(api)  # close at 06-13 == day 43
        auction = validate_success(api.get_auction(scenario["auction"]["id"], REGISTRAR))
        assert auction["estimated_partner_payout_cents"] == 13275, (
            f"estimate variant must project 13275, got "
            f"{auction['estimated_partner_payout_cents']}"
        )
        assert auction["final_storage_fee_cents"] == 5700, (
            f"38 chargeable days * 150 == 5700, got {auction['final_storage_fee_cents']}"
        )
        assert auction["final_program_commission_cents"] == 2430, (
            f"round(0.10 * 24300) == 2430, got {auction['final_program_commission_cents']}"
        )
        assert auction["final_partner_payout_cents"] == 21870, (
            f"final payout must be 21870, got {auction['final_partner_payout_cents']}"
        )
        assert auction["estimated_partner_payout_cents"] != auction["final_partner_payout_cents"], (
            "the two variants must diverge on the same auction row"
        )
        intake = validate_success(api.get_recovery_intake(scenario["intake"]["id"], REGISTRAR))
        assert intake["status"] == "DISPOSED"

    def test_auction_estimate_vs_final_diverge_via_gross_on_time_close(self, api):
        """PRD §3.7: "the winning bid rather than the reserve drives the gross."
        PRD §3.7: "Then the estimate variant of the settlement waterfall runs,
        writing `estimated_storage_fee_cents`,
        `estimated_program_commission_cents`, and
        `estimated_partner_payout_cents`."

        Closing exactly at the scheduled ends_at keeps storage identical (5250) in
        both variants, yet the winning bid 30000 (vs reserve 20000) still yields a
        final payout of 22275 against the estimate's 13275.

        Design: Difficulty/dual_variant_calc/auction_estimate_vs_final_settlement_late_close
        """
        scenario = _settled_auction(api, close_clock="2026-06-10T00:00:00Z")
        auction = validate_success(api.get_auction(scenario["auction"]["id"], REGISTRAR))
        assert auction["estimated_partner_payout_cents"] == 13275
        assert auction["final_storage_fee_cents"] == 5250, (
            f"35 chargeable days * 150 == 5250, got {auction['final_storage_fee_cents']}"
        )
        assert auction["final_program_commission_cents"] == 2475, (
            f"round(0.10 * 24750) == 2475, got {auction['final_program_commission_cents']}"
        )
        assert auction["final_partner_payout_cents"] == 22275, (
            f"final payout must be 22275, got {auction['final_partner_payout_cents']}"
        )


class TestPinnedEvaluationOrder:
    def test_auction_settlement_pinned_evaluation_order(self, api):
        """PRD §3.7: "The waterfall's evaluation order is pinned and contractual —
        later steps depend on earlier ones, so evaluating in any other order is
        undefined: first, the gross is the `reserve_price_cents`; second, the
        storage cutoff is the scheduled `ends_at`; third, the storage fee is the
        smaller of the accrued storage through that cutoff and thirty percent of
        the gross rounded half-up; fourth, the base is the gross minus the storage
        fee; fifth, the commission is ten percent of the portion of the base up to
        50000 cents, rounded half-up, plus fifteen percent of any portion of the
        base above 50000 cents, rounded half-up, with the two rounded tier
        components then summed; sixth, the partner payout is the gross minus the
        storage fee minus the commission."

        Winning bid 50000, close at day 38: storage min(33*150, 15000) == 4950,
        commission 4505, payout 40545.

        Design: Difficulty/combinatorial_formula/auction_settlement_pinned_evaluation_order
        """
        scenario = _settled_auction(
            api,
            appraised_value_cents=200000,
            bid_amount=50000,
            ends_at="2026-06-08T00:00:00Z",
            close_clock="2026-06-08T00:00:00Z",
            serial="ORD777",
        )
        auction = validate_success(api.get_auction(scenario["auction"]["id"], REGISTRAR))
        assert auction["final_storage_fee_cents"] == 4950, (
            f"min(33*150, round(0.30*50000)) == 4950, got {auction['final_storage_fee_cents']}"
        )
        assert auction["final_program_commission_cents"] == 4505, (
            f"round(0.10 * 45050) + round(0.15 * 0) == 4505, got "
            f"{auction['final_program_commission_cents']}"
        )
        assert auction["final_partner_payout_cents"] == 40545, (
            f"50000 - 4950 - 4505 == 40545, got {auction['final_partner_payout_cents']}"
        )
        total = (
            auction["final_storage_fee_cents"]
            + auction["final_program_commission_cents"]
            + auction["final_partner_payout_cents"]
        )
        assert total == 50000, f"waterfall must conserve the gross 50000, got {total}"

    def test_auction_settlement_commission_tier_straddle(self, api):
        """PRD §3.7: "fifth, the commission is ten percent of the portion of the
        base up to 50000 cents, rounded half-up, plus fifteen percent of any
        portion of the base above 50000 cents, rounded half-up, with the two
        rounded tier components then summed"

        Winning bid 100000, close at day 38: storage 4950, base 95050, commission
        round(0.10*50000)=5000 + round(0.15*45050)=6758 == 11758, payout 83292.

        Design: Difficulty/combinatorial_formula/auction_settlement_pinned_evaluation_order
        """
        scenario = _settled_auction(
            api,
            appraised_value_cents=200000,
            bid_amount=100000,
            ends_at="2026-06-08T00:00:00Z",
            close_clock="2026-06-08T00:00:00Z",
            serial="ORD778",
        )
        auction = validate_success(api.get_auction(scenario["auction"]["id"], REGISTRAR))
        assert auction["final_storage_fee_cents"] == 4950
        assert auction["final_program_commission_cents"] == 11758, (
            f"5000 + 6758 == 11758, got {auction['final_program_commission_cents']}"
        )
        assert auction["final_partner_payout_cents"] == 83292, (
            f"100000 - 4950 - 11758 == 83292, got {auction['final_partner_payout_cents']}"
        )
        total = (
            auction["final_storage_fee_cents"]
            + auction["final_program_commission_cents"]
            + auction["final_partner_payout_cents"]
        )
        assert total == 100000, f"waterfall must conserve the gross 100000, got {total}"


class TestDoubleEntryInvariant:
    def test_settle_then_void_double_entry_balance(self, api):
        """PRD §2.8: "The governing invariant, evaluated over the whole table after
        every financial transition (registration, transfer acceptance, auction
        settlement, settlement void), is exact: the sum of `amount_cents` over all
        `CREDIT` rows minus the sum over all `DEBIT` rows equals zero."
        PRD §3.7: "Voiding the settlement — allowed only from `SETTLED` (otherwise
        `ERR_AUCTION_NOT_SETTLABLE`) — moves the auction to `VOIDED` and, for every
        ledger entry created by the settle, appends a mirrored `REVERSAL` entry
        with the direction swapped and an equal `amount_cents`, preserving
        double-entry balance exactly."

        Registration fee 2060 + settle set 60000 per side == 62060 after settle;
        the void adds another 60000 per side == 122060, with 8 REVERSAL rows.

        Design: Difficulty/compensating_invariant/settle_then_void_double_entry_balance
        """
        owner = register_owner("registrar-owner@x.com", "Reg Owner")
        bicycle = register_bicycle(
            owner, serial_number="LED100", declared_value_cents=150000
        )
        assert bicycle["registration_fee_cents"] == 2060
        scenario = _settled_auction(api, serial="LED200")  # bid 30000, close day 43
        entries_after_settle = get_all_ledger_entries()
        credits, debits = assert_ledger_balance(entries_after_settle)
        assert credits == 62060 and debits == 62060, (
            f"after settle each side must total 62060 (2060 + 60000), "
            f"got CREDIT {credits} / DEBIT {debits}"
        )
        validate_success(api.void_settlement(scenario["auction"]["id"], REGISTRAR))
        entries_after_void = get_all_ledger_entries()
        credits, debits = assert_ledger_balance(entries_after_void)
        assert credits == 122060 and debits == 122060, (
            f"after the compensating void each side must total 122060, "
            f"got CREDIT {credits} / DEBIT {debits}"
        )
        reversals = [e for e in entries_after_void if e["entry_type"] == "REVERSAL"]
        assert len(reversals) == 8, (
            f"the 8 settle entries must produce exactly 8 mirrored REVERSAL rows, "
            f"got {len(reversals)}"
        )
        for entry in entries_after_void:
            assert_ledger_entry(entry)

    def test_void_reversals_mirror_directions_and_intake_stays_disposed(self, api):
        """PRD §3.7: "for every ledger entry created by the settle, appends a
        mirrored `REVERSAL` entry with the direction swapped and an equal
        `amount_cents`, preserving double-entry balance exactly. The void is
        financial only: the intake remains `DISPOSED`."

        Design: Difficulty/compensating_invariant/settle_then_void_double_entry_balance
        """
        scenario = _settled_auction(api, serial="LED201")
        validate_success(api.void_settlement(scenario["auction"]["id"], REGISTRAR))
        entries = get_all_ledger_entries({"auction_id": scenario["auction"]["id"]})
        settle_entries = [e for e in entries if e["entry_type"] != "REVERSAL"]
        reversals = [e for e in entries if e["entry_type"] == "REVERSAL"]
        assert len(settle_entries) == 8 and len(reversals) == 8
        swap = {"DEBIT": "CREDIT", "CREDIT": "DEBIT"}
        for original in settle_entries:
            matches = [
                r for r in reversals
                if r["amount_cents"] == original["amount_cents"]
                and r["direction"] == swap[original["direction"]]
                and r["account"] == original["account"]
            ]
            assert matches, (
                f"no mirrored REVERSAL found for {original['entry_type']} "
                f"{original['direction']}/{original['account']} "
                f"{original['amount_cents']}"
            )
        auction = validate_success(api.get_auction(scenario["auction"]["id"], REGISTRAR))
        assert auction["status"] == "VOIDED"
        intake = validate_success(api.get_recovery_intake(scenario["intake"]["id"], REGISTRAR))
        assert intake["status"] == "DISPOSED", (
            f"void is financial only: intake must remain DISPOSED, got {intake['status']}"
        )


class TestImmediateConsistency:
    def test_settle_immediately_visible_in_response(self, api):
        """PRD §2.10: "State changes propagate eagerly and atomically."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.7: "When a `WINNING` bid exists, the final variant of the waterfall
        runs with the winning bid's amount as the gross and `closed_at` as the
        storage cutoff ... writing `final_storage_fee_cents`,
        `final_program_commission_cents`, and `final_partner_payout_cents`."

        Winning bid 30000 closed at the scheduled ends_at (day 40): storage 5250,
        commission 2475, payout 22275.

        Design: Corner/consistency_model/settle_immediately_visible_in_response
        """
        scenario = _settled_auction(api, close_clock="2026-06-10T00:00:00Z", serial="IMM200")
        settled = scenario["settled"]
        assert settled["status"] == "SETTLED", (
            f"the settle response itself must carry status SETTLED, got {settled['status']}"
        )
        assert settled["final_partner_payout_cents"] == 22275, (
            f"the settle response itself must carry final_partner_payout_cents 22275, "
            f"got {settled['final_partner_payout_cents']}"
        )
        assert settled["winning_bid_id"] == scenario["bid"]["id"]
        read_back = validate_success(api.get_auction(scenario["auction"]["id"], REGISTRAR))
        assert read_back["status"] == "SETTLED"
        assert read_back["final_partner_payout_cents"] == 22275, (
            "a follow-up read must show identical final values (immediate consistency)"
        )
