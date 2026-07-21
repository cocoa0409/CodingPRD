"""Tournaments: handicap seeding variants, prize pool, seed minimum, withdrawal
compensation invariants, entry check-in dependency, and terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_member_headers,
)
from test_helpers import fixtures as fx


class TestHandicapSeeding:
    def test_full_mode_stamps_uncapped_spot(self, api):
        """PRD 3.5: "For a given entry, the raw spot is the top rating minus that
        entry's member's handicap_rating. The stamped handicap_spot then depends on the
        tournament's handicap_mode: under FULL it is the raw spot uncapped; under CAPPED
        it is the smaller of three and the raw spot; under NONE it is zero."

        Top rating 9, entrant 4 -> raw spot 5; FULL leaves it uncapped at 5.

        Design: Difficulty/dual_variant_calc/handicap_spot_full_vs_capped
        """
        t, _members, entries = fx.setup_tournament_with_entries(
            ratings=[9, 7, 5, 4], handicap_mode="FULL", entry_fee_cents=0, max_entries=8,
            name="FullCup",
        )
        validate_success(api.seed_tournament(t["id"], TEST_USERS["manager"]))
        entry4 = validate_success(api.get_tournament_entry(entries[3]["id"], TEST_USERS["manager"]))
        assert entry4["handicap_spot"] == 5

    def test_capped_mode_caps_spot_at_three(self, api):
        """PRD 3.5: "under CAPPED it is the smaller of three and the raw spot".

        Top rating 9, entrant 4 -> raw spot 5; CAPPED clamps it to 3.

        Design: Difficulty/dual_variant_calc/handicap_spot_full_vs_capped
        """
        t, _members, entries = fx.setup_tournament_with_entries(
            ratings=[9, 7, 5, 4], handicap_mode="CAPPED", entry_fee_cents=0, max_entries=8,
            name="CapCup",
        )
        validate_success(api.seed_tournament(t["id"], TEST_USERS["manager"]))
        entry4 = validate_success(api.get_tournament_entry(entries[3]["id"], TEST_USERS["manager"]))
        assert entry4["handicap_spot"] == 3


class TestPrizePool:
    def test_two_entries_sum_prize_pool(self, api):
        """PRD 3.5: "The prize pool is the running sum of entry_fee_cents over the
        tournament's entries whose status is ENTERED, CHECKED_IN, or ELIMINATED"
        "adds the fee to the tournament's prize_pool_cents, and decrements open_slots by
        one."

        Two entries at 2500 -> prize_pool 5000, open_slots 8-2 = 6.

        Design: Corner/calculations/prize_pool_sums_two_captured_entries
        """
        t, _members, _entries = fx.setup_tournament_with_entries(
            ratings=[5, 5], entry_fee_cents=2500, max_entries=8, fund_each=10000, name="PoolCup",
        )
        after = validate_success(api.get_tournament(t["id"], TEST_USERS["manager"]))
        assert after["prize_pool_cents"] == 5000
        assert after["open_slots"] == 6


class TestSeedMinimum:
    def test_seed_with_three_entries_rejected(self, api):
        """PRD 3.5: "A Manager seeds the bracket (REGISTRATION_OPEN -> SEEDED) only once
        at least four entries have been captured (counting entries in ENTERED or
        CHECKED_IN); fewer than that is refused with ERR_PRECONDITION_NOT_MET."

        Design: Difficulty/boundary_precision_check/seed_requires_at_least_four_entries_three_fails
        """
        t, _members, _entries = fx.setup_tournament_with_entries(
            ratings=[5, 5, 5], entry_fee_cents=0, max_entries=8, name="ThreeCup", fmt="ROUND_ROBIN",
        )
        resp = api.seed_tournament(t["id"], TEST_USERS["manager"])
        validate_error(resp, ApiErrorId.ERR_PRECONDITION_NOT_MET.value)

    def test_seed_with_three_entries_leaves_registration_open(self, api):
        """PRD 3.5: "A Manager seeds the bracket (REGISTRATION_OPEN -> SEEDED) only once
        at least four entries have been captured ...; fewer than that is refused with
        ERR_PRECONDITION_NOT_MET."

        Design: Difficulty/boundary_precision_check/seed_requires_at_least_four_entries_three_fails
        """
        t, _members, _entries = fx.setup_tournament_with_entries(
            ratings=[5, 5, 5], entry_fee_cents=0, max_entries=8, name="ThreeCup", fmt="ROUND_ROBIN",
        )
        validate_error(api.seed_tournament(t["id"], TEST_USERS["manager"]),
                       ApiErrorId.ERR_PRECONDITION_NOT_MET.value)
        after = validate_success(api.get_tournament(t["id"], TEST_USERS["manager"]))
        assert after["status"] == "REGISTRATION_OPEN"


class TestWithdrawInvariants:
    def test_withdraw_conserves_wallet_and_prize_pool(self, api):
        """PRD 3.5: "withdrawal moves the entry ENTERED -> WITHDRAWN, refunds the
        entry_fee_cents back to the member's wallet, subtracts that fee from
        prize_pool_cents, and restores one open_slots."

        Fund 10000, fee 2500: after enter+withdraw wallet returns to 10000 and
        prize_pool to 0 (money conserved).

        Design: Difficulty/compensating_invariant/entry_withdraw_conserves_wallet_plus_prizepool
        """
        plan = fx.make_plan(tier="SILVER", monthly_fee_cents=5000, table_discount_pct=0.10)
        member = fx.make_funded_member(plan["id"], 10000)
        t = fx.make_tournament(name="MoneyCup", entry_fee_cents=2500, max_entries=8,
                               open_registration=True)
        entry = fx.enter_tournament(t["id"], member["id"])
        validate_success(api.withdraw_entry(entry["id"], make_member_headers(member["id"])))
        after_member = validate_success(api.get_member(member["id"], TEST_USERS["manager"]))
        after_t = validate_success(api.get_tournament(t["id"], TEST_USERS["manager"]))
        assert after_member["wallet_credit_cents"] == 10000
        assert after_t["prize_pool_cents"] == 0

    def test_withdraw_marks_entry_withdrawn(self, api):
        """PRD 3.5: "withdrawal moves the entry ENTERED -> WITHDRAWN, refunds the
        entry_fee_cents back to the member's wallet, subtracts that fee from
        prize_pool_cents, and restores one open_slots."

        Design: Difficulty/compensating_invariant/entry_withdraw_conserves_wallet_plus_prizepool
        """
        plan = fx.make_plan(tier="SILVER", monthly_fee_cents=5000, table_discount_pct=0.10)
        member = fx.make_funded_member(plan["id"], 10000)
        t = fx.make_tournament(name="MoneyCup", entry_fee_cents=2500, max_entries=8,
                               open_registration=True)
        entry = fx.enter_tournament(t["id"], member["id"])
        withdrawn = validate_success(
            api.withdraw_entry(entry["id"], make_member_headers(member["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"

    def test_withdraw_restores_open_slots(self, api):
        """PRD 3.5: "withdrawal moves the entry ENTERED -> WITHDRAWN, refunds the
        entry_fee_cents back to the member's wallet, subtracts that fee from
        prize_pool_cents, and restores one open_slots."

        max_entries 6: after enter (open_slots 5) then withdraw, open_slots returns to 6.

        Design: Difficulty/compensating_invariant/entry_withdraw_conserves_open_slots
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_member(plan["id"])
        t = fx.make_tournament(name="SlotCup", fmt="ROUND_ROBIN", entry_fee_cents=0,
                               max_entries=6, open_registration=True)
        entry = fx.enter_tournament(t["id"], member["id"])
        validate_success(api.withdraw_entry(entry["id"], make_member_headers(member["id"])))
        after = validate_success(api.get_tournament(t["id"], TEST_USERS["manager"]))
        assert after["open_slots"] == 6

    def test_withdraw_on_slotcup_marks_entry_withdrawn(self, api):
        """PRD 3.5: "withdrawal moves the entry ENTERED -> WITHDRAWN, refunds the
        entry_fee_cents back to the member's wallet, subtracts that fee from
        prize_pool_cents, and restores one open_slots."

        Design: Difficulty/compensating_invariant/entry_withdraw_conserves_open_slots
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_member(plan["id"])
        t = fx.make_tournament(name="SlotCup", fmt="ROUND_ROBIN", entry_fee_cents=0,
                               max_entries=6, open_registration=True)
        entry = fx.enter_tournament(t["id"], member["id"])
        withdrawn = validate_success(
            api.withdraw_entry(entry["id"], make_member_headers(member["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"


class TestEntryCheckinDependency:
    def test_checkin_requires_tournament_seeded(self, api):
        """PRD 3.5: "A FrontDesk operator checks in an ENTERED entry (ENTERED ->
        CHECKED_IN), which requires the tournament to be SEEDED (otherwise
        ERR_DEPENDENT_STATE)."

        Design: Difficulty/cross_entity_state_dependency/entry_checkin_requires_tournament_seeded
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_member(plan["id"])
        t = fx.make_tournament(name="OpenCup", entry_fee_cents=0, max_entries=8,
                               open_registration=True)
        entry = fx.enter_tournament(t["id"], member["id"])
        resp = api.checkin_entry(entry["id"], TEST_USERS["frontdesk"])
        validate_error(resp, ApiErrorId.ERR_DEPENDENT_STATE.value)

    def test_checkin_on_open_tournament_leaves_entry_entered(self, api):
        """PRD 3.5: "A FrontDesk operator checks in an ENTERED entry (ENTERED ->
        CHECKED_IN), which requires the tournament to be SEEDED (otherwise
        ERR_DEPENDENT_STATE)."

        Design: Difficulty/cross_entity_state_dependency/entry_checkin_requires_tournament_seeded
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_member(plan["id"])
        t = fx.make_tournament(name="OpenCup", entry_fee_cents=0, max_entries=8,
                               open_registration=True)
        entry = fx.enter_tournament(t["id"], member["id"])
        validate_error(api.checkin_entry(entry["id"], TEST_USERS["frontdesk"]),
                       ApiErrorId.ERR_DEPENDENT_STATE.value)
        after = validate_success(api.get_tournament_entry(entry["id"], TEST_USERS["manager"]))
        assert after["status"] == "ENTERED"


class TestTournamentTerminalState:
    def test_open_registration_on_cancelled_tournament_invalid_state(self, api):
        """PRD 2.8: "State — the target resource is in a state from which the requested
        transition is defined, else ERR_INVALID_STATE (409)."
        PRD 3.5: "A tournament advances SCHEDULED -> REGISTRATION_OPEN -> SEEDED ->
        IN_PROGRESS -> COMPLETED under Manager control, and may be cancelled from
        SCHEDULED, REGISTRATION_OPEN, or SEEDED."

        Design: Corner/state_machines/open_registration_from_cancelled_tournament_invalid_state
        """
        t = fx.make_tournament(name="DeadCup", entry_fee_cents=0, max_entries=8)
        validate_success(api.cancel_tournament(t["id"], TEST_USERS["manager"]))
        resp = api.open_tournament(t["id"], TEST_USERS["manager"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_tournament(t["id"], TEST_USERS["manager"]))
        assert after["status"] == "CANCELLED"
