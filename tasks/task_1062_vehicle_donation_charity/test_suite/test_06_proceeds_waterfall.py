"""Splitting the proceeds: the waterfall, its journal and its reversal."""
from test_helpers import (
    assert_donation_money_invariants,
    assert_follow_up_task,
    assert_ledger_entry,
    ledger_types,
    make_charity_admin_headers,
    new_charity,
    new_donor,
    new_venue,
    read_charity,
    read_donation,
    read_lot,
    signed_total,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    clear_title,
    donation_ledger,
    donation_tasks,
    new_lot,
    read_pickup,
    sell_lot,
    set_clock,
    setup_sold_donation,
    setup_towed_donation,
)


class TestTowAllowanceEvaluationOrder:
    def test_tow_allowance_is_capped_against_the_provisional_balance(self, api):
        """PRD §3.7: "*Step one — the program fee.* Multiply the gross by that rate and
        round the product half up to whole cents."
        PRD §3.7: "The program reimburses the tow, but only up to a quarter of the
        provisional balance: take twenty-five hundredths of the provisional balance, round
        that half up to whole cents, and use the **lesser** of the billed cost and that
        ceiling. The outcome is written to `tow_allowance_cents`."
        PRD §3.7: "*Step four — the charity's net.* From the provisional balance subtract
        the tow allowance and subtract a flat administrative fee of twenty-five dollars
        (two thousand five hundred cents)."

        Design: Difficulty/combinatorial_formula/proceeds_waterfall_tow_allowance_evaluation_order
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_towed_donation(tow_cost_cents=40_000)
        clear_title(bundle["donation"]["id"])
        venue = new_venue()
        lot = new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=50_000)

        sell_lot(lot["id"], bundle["donation"]["id"], 120_000)

        donation = read_donation(bundle["donation"]["id"])
        assert_donation_money_invariants(donation)
        assert donation["gross_proceeds_cents"] == 120_000
        assert donation["program_fee_cents"] == 14_400, "0.12 x 120000, the middle tier"
        assert donation["tow_allowance_cents"] == 26_400, (
            "0.25 x (120000 - 14400) = 26400 is less than the billed 40000"
        )
        assert donation["net_to_charity_cents"] == 76_700, "105600 - 26400 - 2500"
        assert donation["status"] == "SOLD"
        assert donation["payout_status"] == "ACCRUED"
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 76_700

    def test_the_completed_tow_cost_is_journalled_as_its_own_debit(self, api):
        """PRD §3.7: "**Second**, the accrual journals itself: a `PROCEEDS_CREDIT` entry is
        appended as a `CREDIT` for the gross, a `PROGRAM_FEE_DEBIT` as a `DEBIT` for the
        program fee, a `TOW_COST_DEBIT` as a `DEBIT` for the tow allowance — omitted
        entirely when the allowance is zero — and an `ADMIN_FEE_DEBIT` as a `DEBIT` for
        the two-thousand-five-hundred-cent administrative fee; and the beneficiary
        affiliate's `pledged_balance_cents` rises by the donation's net."
        PRD §3.7: "*Step three — the tow allowance.* Look up the tow cost actually billed:
        the `actual_tow_cost_cents` of the pickup order for this donation whose `status`
        is `COMPLETED`."

        Design: Difficulty/combinatorial_formula/proceeds_waterfall_tow_allowance_evaluation_order
        """
        set_clock("2026-07-05T00:00:00Z")
        bundle = setup_towed_donation(tow_cost_cents=40_000)
        assert read_pickup(bundle["pickup_order"]["id"])["actual_tow_cost_cents"] == 40_000
        clear_title(bundle["donation"]["id"])
        venue = new_venue()
        lot = new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=50_000)
        sell_lot(lot["id"], bundle["donation"]["id"], 120_000)

        entries = donation_ledger(bundle["donation"]["id"])

        assert len(entries) == 4
        for entry in entries:
            assert_ledger_entry(entry)
        amounts = {entry["entry_type"]: entry["amount_cents"] for entry in entries}
        assert amounts["PROCEEDS_CREDIT"] == 120_000
        assert amounts["PROGRAM_FEE_DEBIT"] == 14_400
        assert amounts["TOW_COST_DEBIT"] == 26_400
        assert amounts["ADMIN_FEE_DEBIT"] == 2_500
        directions = {entry["entry_type"]: entry["direction"] for entry in entries}
        assert directions["PROCEEDS_CREDIT"] == "CREDIT"
        assert directions["PROGRAM_FEE_DEBIT"] == "DEBIT"
        assert directions["TOW_COST_DEBIT"] == "DEBIT"
        assert directions["ADMIN_FEE_DEBIT"] == "DEBIT"
        assert signed_total(entries) == 76_700


class TestAutoBatchCascade:
    def test_a_large_sale_opens_a_remittance_batch_for_the_affiliate(self, api,
                                                                    finance_officer_headers):
        """PRD §3.7: "**Third**, that balance increase can trip an automatic sweep: when
        the affiliate's `pledged_balance_cents` reaches or exceeds five thousand dollars
        (five hundred thousand cents) and that affiliate has no remittance batch currently
        in `OPEN`, `CLOSED`, or `DISPUTED`, the system opens a batch for it with `status`
        of `OPEN`, `period_start_utc` at the current logical clock and `period_end_utc`
        thirty days later."

        Design: Difficulty/transitive_cascade/record_sale_cascades_to_auto_opened_remittance_batch_and_task
        """
        set_clock("2026-07-10T00:00:00Z")
        charity = new_charity(name="Big Wheels Trust", remittance_fee_pct=0.10)
        bundle = setup_sold_donation(
            sale_price_cents=1_000_000,
            charity=charity,
            reserve_price_cents=100_000,
            intake_channel="PARTNER",
            declared_condition="EXCELLENT",
        )

        donation = read_donation(bundle["donation"]["id"])
        assert donation["status"] == "SOLD"
        assert donation["payout_status"] == "ACCRUED"
        assert donation["program_fee_cents"] == 100_000, "0.10 above five hundred thousand cents"
        assert donation["net_to_charity_cents"] == 897_500
        assert read_charity(charity["id"])["pledged_balance_cents"] == 897_500

        batches, _ = validate_paginated(
            api.list_remittance_batches(
                finance_officer_headers, params={"charity_id": charity["id"]}
            )
        )
        assert len(batches) == 1
        batch = batches[0]
        assert batch["status"] == "OPEN"
        assert batch["period_start_utc"].startswith("2026-07-10T00:00:00")
        assert batch["period_end_utc"].startswith("2026-08-09T00:00:00")

    def test_the_auto_opened_batch_raises_a_remittance_obligation(self, api):
        """PRD §3.7: "**Fourth**, an auto-opened batch raises a follow-up obligation of
        type `REMITTANCE_PENDING`, `OPEN`, assigned to `FinanceOfficer` and due fifteen
        days after the current logical clock, recorded against the donation whose sale
        triggered the sweep."
        PRD §3.7: "**Second**, the accrual journals itself: a `PROCEEDS_CREDIT` entry is
        appended as a `CREDIT` for the gross, a `PROGRAM_FEE_DEBIT` as a `DEBIT` for the
        program fee, a `TOW_COST_DEBIT` as a `DEBIT` for the tow allowance — omitted
        entirely when the allowance is zero — and an `ADMIN_FEE_DEBIT` as a `DEBIT` for
        the two-thousand-five-hundred-cent administrative fee; and the beneficiary
        affiliate's `pledged_balance_cents` rises by the donation's net."

        Design: Difficulty/transitive_cascade/record_sale_cascades_to_auto_opened_remittance_batch_and_task
        """
        set_clock("2026-07-10T00:00:00Z")
        charity = new_charity(name="Big Wheels Trust", remittance_fee_pct=0.10)
        bundle = setup_sold_donation(
            sale_price_cents=1_000_000,
            charity=charity,
            reserve_price_cents=100_000,
            intake_channel="PARTNER",
            declared_condition="EXCELLENT",
        )

        entries = donation_ledger(bundle["donation"]["id"])
        assert len(entries) == 3, "no TOW_COST_DEBIT because the tow allowance is zero"
        assert "TOW_COST_DEBIT" not in ledger_types(entries)
        amounts = {entry["entry_type"]: entry["amount_cents"] for entry in entries}
        assert amounts == {
            "PROCEEDS_CREDIT": 1_000_000,
            "PROGRAM_FEE_DEBIT": 100_000,
            "ADMIN_FEE_DEBIT": 2_500,
        }

        tasks = donation_tasks(bundle["donation"]["id"])
        assert len(tasks) == 1
        task = tasks[0]
        assert_follow_up_task(task)
        assert task["task_type"] == "REMITTANCE_PENDING"
        assert task["status"] == "OPEN"
        assert task["assigned_role"] == "FinanceOfficer"
        assert task["due_utc"].startswith("2026-07-25T00:00:00")


class TestVoidSaleConservation:
    def test_void_sale_returns_the_affiliate_balances_to_their_pre_sale_values(
        self, api, auction_manager_headers, finance_officer_headers
    ):
        """PRD §3.7: "Voiding the sale unwinds all of it symmetrically. The donation's four
        money fields — `gross_proceeds_cents`, `program_fee_cents`, `tow_allowance_cents`,
        and `net_to_charity_cents` — return to 0, the money axis moves `ACCRUED → PENDING`,
        a single `REVERSAL` entry is appended as a `DEBIT` whose `amount_cents` equals the
        donation's net **as it stood immediately before the void**, and the affiliate's
        `pledged_balance_cents` falls by that same pre-void net."

        Design: Difficulty/compensating_invariant/sale_then_void_sale_restores_charity_accrual_total_to_zero
        """
        charity = new_charity(remittance_fee_pct=0.10)
        bundle = setup_sold_donation(
            sale_price_cents=120_000, charity=charity, reserve_price_cents=10_000
        )
        mid = validate_success(
            api.get_charity_summary(charity["id"], finance_officer_headers), 200
        )
        assert mid["pledged_balance_cents"] == 103_100
        assert mid["remitted_balance_cents"] == 0

        validate_success(
            api.void_sale(
                bundle["lot"]["id"], {"void_reason": "buyer defaulted"}, auction_manager_headers
            ),
            200,
        )

        end = validate_success(
            api.get_charity_summary(charity["id"], finance_officer_headers), 200
        )
        assert end["pledged_balance_cents"] == 0
        assert end["remitted_balance_cents"] == 0
        assert end["pledged_balance_cents"] + end["remitted_balance_cents"] == 0
        assert end["ledger_signed_total"] == 0

    def test_void_sale_journals_one_reversal_and_zeroes_the_money_fields(
        self, api, auction_manager_headers
    ):
        """PRD §3.6: "The lot moves `SOLD → VOIDED` with `void_reason` stored and both
        `sale_price_cents` and `sold_at_utc` cleared, the donation moves `SOLD → UNSOLD`,
        and the entire proceeds cascade is reversed as §3.7 describes."
        PRD §2.10: "`direction` is either `CREDIT` or `DEBIT`. `amount_cents` is always an
        unsigned magnitude of at least zero; the sign lives in `direction`, such that an
        entry's signed contribution is its `amount_cents` when the direction is `CREDIT`
        and the negative of its `amount_cents` when the direction is `DEBIT`."

        Design: Difficulty/compensating_invariant/sale_then_void_sale_restores_charity_accrual_total_to_zero
        """
        charity = new_charity(remittance_fee_pct=0.10)
        bundle = setup_sold_donation(
            sale_price_cents=120_000, charity=charity, reserve_price_cents=10_000
        )

        voided = validate_success(
            api.void_sale(
                bundle["lot"]["id"], {"void_reason": "buyer defaulted"}, auction_manager_headers
            ),
            200,
        )

        entries = donation_ledger(bundle["donation"]["id"])
        assert ledger_types(entries) == [
            "PROCEEDS_CREDIT", "PROGRAM_FEE_DEBIT", "ADMIN_FEE_DEBIT", "REVERSAL",
        ]
        assert entries[0]["amount_cents"] == 120_000 and entries[0]["direction"] == "CREDIT"
        assert entries[1]["amount_cents"] == 14_400 and entries[1]["direction"] == "DEBIT"
        assert entries[2]["amount_cents"] == 2_500 and entries[2]["direction"] == "DEBIT"
        assert entries[3]["amount_cents"] == 103_100 and entries[3]["direction"] == "DEBIT"
        assert signed_total(entries) == 0

        donation = read_donation(bundle["donation"]["id"])
        assert donation["gross_proceeds_cents"] == 0
        assert donation["program_fee_cents"] == 0
        assert donation["tow_allowance_cents"] == 0
        assert donation["net_to_charity_cents"] == 0
        assert donation["status"] == "UNSOLD"
        assert donation["payout_status"] == "PENDING"
        assert voided["status"] == "VOIDED"
        assert read_lot(bundle["lot"]["id"])["status"] == "VOIDED"


class TestProgramFeeTiers:
    def test_program_fee_tier_switches_one_cent_above_the_first_ceiling(self, api):
        """PRD §3.7: "From the gross, determine the program's tiered rate: fifteen percent
        when the gross is one thousand dollars (one hundred thousand cents) or less; twelve
        percent when the gross exceeds that but is five thousand dollars (five hundred
        thousand cents) or less; ten percent above that."

        Design: Corner/calculations/corner_program_fee_tier_switches_between_100000_and_100001
        """
        charity = new_charity(name="Tier Trust")
        donor = new_donor()
        venue = new_venue()
        low = setup_sold_donation(
            sale_price_cents=100_000,
            charity=charity,
            donor=donor,
            venue=venue,
            reserve_price_cents=10_000,
        )
        high = setup_sold_donation(
            sale_price_cents=100_001,
            charity=charity,
            donor=donor,
            venue=venue,
            reserve_price_cents=10_000,
        )

        low_donation = read_donation(low["donation"]["id"])
        high_donation = read_donation(high["donation"]["id"])
        assert low_donation["program_fee_cents"] == 15_000
        assert low_donation["net_to_charity_cents"] == 82_500
        assert high_donation["program_fee_cents"] == 12_000
        assert high_donation["net_to_charity_cents"] == 85_501
        assert (
            high_donation["net_to_charity_cents"] - low_donation["net_to_charity_cents"] == 3_001
        )
        assert read_charity(charity["id"])["pledged_balance_cents"] == 168_001

    def test_program_fee_floor_lifts_a_small_sale(self, api):
        """PRD §3.7: "*Step one — the program fee.* Multiply the gross by that rate and
        round the product half up to whole cents. The program never retains less than
        fifty dollars (five thousand cents), so if the rounded figure falls below that
        floor, the floor is used instead. It also never retains more than the sale itself
        brought in, so the result is finally capped at the gross. The outcome is written to
        `program_fee_cents`."

        Design: Corner/calculations/corner_minimum_program_fee_floor_applies_to_small_sale
        """
        charity = new_charity(name="Floor Trust")
        bundle = setup_sold_donation(
            sale_price_cents=12_000,
            charity=charity,
            venue=new_venue(name="Salvage Yard", venue_type="SALVAGE"),
            reserve_price_cents=1_000,
            declared_condition="SALVAGE",
        )

        donation = read_donation(bundle["donation"]["id"])
        assert donation["program_fee_cents"] == 5_000, "0.15 x 12000 = 1800 is lifted to the floor"
        assert donation["tow_allowance_cents"] == 0
        assert donation["net_to_charity_cents"] == 4_500, "7000 - 0 - 2500"
        assert read_charity(charity["id"])["pledged_balance_cents"] == 4_500


class TestProceedsJournal:
    def test_ledger_entries_are_immutable_journal_lines_read_oldest_first(
        self, api, finance_officer_headers
    ):
        """PRD §2.4: "Proceeds ledger entries are immutable journal lines: they carry `id`
        and `created_at` only. They have no `updated_at` and no `version`, because a ledger
        line is never edited — a mistake is corrected by appending a compensating line,
        never by amending the original."
        PRD §2.3: "The ledger listings and the follow-up-task listing also follow this
        oldest-first ordering."

        Design: Corner/entities/corner_ledger_entry_is_append_only_without_version
        """
        bundle = setup_sold_donation(sale_price_cents=60_000, reserve_price_cents=10_000)

        entries, meta = validate_paginated(
            api.list_donation_ledger_entries(bundle["donation"]["id"], finance_officer_headers)
        )

        assert len(entries) == 3 and meta["total_count"] == 3
        for entry in entries:
            assert_ledger_entry(entry)
        assert entries[0]["entry_type"] == "PROCEEDS_CREDIT"
        assert entries[0]["direction"] == "CREDIT" and entries[0]["amount_cents"] == 60_000
        assert entries[1]["entry_type"] == "PROGRAM_FEE_DEBIT"
        assert entries[1]["direction"] == "DEBIT" and entries[1]["amount_cents"] == 9_000
        assert entries[2]["entry_type"] == "ADMIN_FEE_DEBIT"
        assert entries[2]["direction"] == "DEBIT" and entries[2]["amount_cents"] == 2_500
        assert read_donation(bundle["donation"]["id"])["net_to_charity_cents"] == 48_500

    def test_charity_summary_reconciles_with_the_journal(self, api):
        """PRD §3.10: "It reports the affiliate's stored `pledged_balance_cents` and
        `remitted_balance_cents` directly; `accrued_donation_count`, the number of that
        charity's donations whose `payout_status` is `ACCRUED`; `unremitted_net_cents`,
        the sum of `net_to_charity_cents` across those same accrued donations; and
        `ledger_signed_total`, the signed sum over every ledger entry whose donation
        belongs to that charity — adding `amount_cents` for a `CREDIT` and subtracting it
        for a `DEBIT`."

        Design: Corner/calculations/corner_charity_summary_projection_matches_the_ledger
        """
        charity = new_charity(name="Report Trust", remittance_fee_pct=0.10)
        setup_sold_donation(sale_price_cents=60_000, charity=charity, reserve_price_cents=1_000)

        summary = validate_success(
            api.get_charity_summary(charity["id"], make_charity_admin_headers(charity["id"])), 200
        )

        assert summary["charity_id"] == charity["id"]
        assert summary["pledged_balance_cents"] == 48_500
        assert summary["remitted_balance_cents"] == 0
        assert summary["accrued_donation_count"] == 1
        assert summary["unremitted_net_cents"] == 48_500
        assert summary["ledger_signed_total"] == 48_500, "60000 - 9000 - 2500"
