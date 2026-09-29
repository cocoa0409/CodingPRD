"""Undo paths that must leave the graph they touched exactly as they found it."""

from test_helpers import (
    BillingMode,
    ComplianceFlag,
    ComplianceResult,
    FundingStatus,
    LineStatus,
    LotStatus,
    ProgramStatus,
    RecordStatus,
    SettlementState,
    VerificationStatus,
    WorkStatus,
    assert_liters,
    assert_line_projection,
    assert_money_fields_zeroed,
    assert_program_ledger,
    fixtures,
)

ACID_CYCLE = {
    "chemical_type": "ACID",
    "contact_minutes": 15,
    "recirculation_temp_f": 80.0,
    "concentrate_liters_used": 0.23,
}
ACID_LOT = {
    "chemical_type": "ACID",
    "lot_code": "A-2001",
    "concentration_pct_stock": 30.0,
    "liters_initial": 10.0,
}


def _signature_that_drained_the_cap(api):
    """A signed visit whose settlement emptied an 8000-cent programme."""
    program = fixtures.create_brewer_program(
        api, funded_scope="CLEANING_AND_PARTS", co_pay_bps=2000, funding_cap_cents=8000
    )
    serviced = fixtures.setup_three_line_visit_with_work(
        api, venue_name="Harbor Taproom", brewer_program_id=program["id"]
    )
    untouched = fixtures.onboard_venue(
        api,
        venue_name="Dockside Cantina",
        access_window=(600, 1200),
        cleaning_frequency_days=14,
        contracted_line_count=2,
        per_line_rate_cents=3000,
        visit_base_fee_cents=5000,
        brewer_program_id=program["id"],
        lines=(),
    )
    assert serviced["visit"]["provisional_charge_cents"] == 24474
    signed = fixtures.sign_visit(api, serviced["visit"]["id"], serviced["account"]["id"])
    assert signed["brewer_funded_cents"] == 8000
    return program, serviced, untouched, signed


def test_a_dispute_rewinds_the_brewer_ledger_to_its_pre_signature_figures(api):
    """PRD §3.7: "The brewer programme is credited back the exact `brewer_funded_cents` that
    this visit posted at settlement, its `consumed_cents` falls by that amount and its
    `remaining_cents` is recomputed; if that brings `consumed_cents` back below the
    `funding_cap_cents` and the programme was `EXHAUSTED`, it returns to `ACTIVE`, whereupon
    every contract naming it recomputes its `funding_status` to `BREWER_FUNDED` and each of
    those accounts recomputes its `billing_mode` to `PROGRAM_BILL` — the funding cascade of
    §3.1 run in reverse."

    Design: Difficulty/compensating_invariant/disputing_a_signature_rewinds_the_exhausted_program_and_both_accounts_billing_modes
    """
    program, serviced, _untouched, _signed = _signature_that_drained_the_cap(api)

    reversed_visit = fixtures.dispute_visit(
        api, serviced["visit"]["id"], serviced["account"]["id"]
    )

    assert reversed_visit["settlement_state"] == SettlementState.REVERSED
    assert reversed_visit["verification_status"] == VerificationStatus.DISPUTED
    assert_money_fields_zeroed(reversed_visit)
    ledger = fixtures.read_program(api, program["id"])
    assert_program_ledger(ledger, 0, 8000, ProgramStatus.ACTIVE)
    # The cap itself is never touched by a credit back.
    assert ledger["funding_cap_cents"] == 8000


def test_the_reversal_spares_the_counts_and_reprices_both_venues(api):
    """PRD §3.7: "The visit's `settlement_state` becomes `REVERSED` and its
    `settled_charge_cents`, `brewer_funded_cents`, `account_due_cents` and
    `cleaning_subtotal_cents` are all reset to 0."
    PRD §3.7: "`signed_at` is deliberately left untouched, so the dispute window stays
    anchored to the original signature and a disputed visit cannot be re-disputed
    indefinitely on a rolling clock."

    Design: Difficulty/compensating_invariant/disputing_a_signature_rewinds_the_exhausted_program_and_both_accounts_billing_modes
    """
    _program, serviced, untouched, signed = _signature_that_drained_the_cap(api)

    reversed_visit = fixtures.dispute_visit(
        api, serviced["visit"]["id"], serviced["account"]["id"]
    )

    assert reversed_visit["provisional_charge_cents"] == 24474, (
        "the provisional variant is not part of the reversal"
    )
    assert reversed_visit["serviced_line_count"] == 3
    assert reversed_visit["billable_line_count"] == 2
    assert reversed_visit["signed_at"] == signed["signed_at"]
    assert reversed_visit["signed_at"] is not None
    assert reversed_visit["work_status"] == WorkStatus.WORK_COMPLETE

    for contract_id in (serviced["contract"]["id"], untouched["contract"]["id"]):
        contract = fixtures.read_contract(api, contract_id)
        assert contract["funding_status"] == FundingStatus.BREWER_FUNDED
    for account_id in (serviced["account"]["id"], untouched["account"]["id"]):
        account = fixtures.read_account(api, account_id)
        assert account["billing_mode"] == BillingMode.PROGRAM_BILL, (
            "the venue that never had a visit is repriced along with the one that did"
        )


def _two_cycles_three_weeks_apart(api):
    """One line cleaned with caustic on the 5th and with acid on the 25th."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    ground = fixtures.setup_started_visit(
        api, venue_name="Millpond Alehouse", lot_specs=({}, ACID_LOT)
    )
    caustic_cycle = fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["line"]["id"],
        ground["lots"][0]["id"],
        ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    second_visit = fixtures.book_visit(
        api,
        ground["account"]["id"],
        ground["technician"]["id"],
        scheduled_date="2026-08-25",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    fixtures.set_clock(api, "2026-08-25T09:00:00Z")
    fixtures.start_visit(api, second_visit["id"], ground["technician"]["id"])
    acid_cycle = fixtures.log_cleaning_cycle(
        api,
        second_visit["id"],
        ground["line"]["id"],
        ground["lots"][1]["id"],
        ground["technician"]["id"],
        **ACID_CYCLE,
    )
    assert acid_cycle["compliance_result"] == ComplianceResult.PASS
    return ground, caustic_cycle, acid_cycle


def test_voiding_a_cycle_gives_back_only_the_volume_that_cycle_drew(api):
    """PRD §3.4: "A void advances the record `POSTED → VOIDED`, stores the `void_reason`, and
    gives back the chemistry: the lot's `liters_remaining` is increased by
    `concentrate_liters_used`, held to three decimal places, and a `DEPLETED` lot climbs back
    to `AVAILABLE` when the restored volume reaches 0.05 liters."

    Design: Difficulty/compensating_invariant/voiding_the_newest_cycle_restores_lot_volume_and_replays_the_lines_due_projection
    """
    ground, caustic_cycle, acid_cycle = _two_cycles_three_weeks_apart(api)
    reason = "Logged against the wrong line by the crew."

    voided = fixtures.void_cycle(api, acid_cycle["id"], reason)

    assert voided["record_status"] == RecordStatus.VOIDED
    assert voided["void_reason"] == reason
    assert fixtures.read_cycle(api, caustic_cycle["id"])["record_status"] == RecordStatus.POSTED
    acid_lot = fixtures.read_lot(api, ground["lots"][1]["id"])
    assert_liters(acid_lot["liters_remaining"], 10.000)
    assert acid_lot["status"] == LotStatus.AVAILABLE
    # The caustic ledger is not touched by an acid void.
    assert_liters(fixtures.read_lot(api, ground["lots"][0]["id"])["liters_remaining"], 19.690)


def test_voiding_replays_the_due_projection_from_the_surviving_cycle(api):
    """PRD §3.4: "The line's `last_chemical_type`, `last_cleaned_at`, `next_due_at`,
    `days_overdue` and `compliance_flag` are then replayed from the cycles that remain
    `POSTED`, which can roll `last_cleaned_at` back to an earlier passing cycle or to null,
    pull `next_due_at` earlier, and push `days_overdue` past the three-day grace inside the
    very same request."

    Design: Difficulty/compensating_invariant/voiding_the_newest_cycle_restores_lot_volume_and_replays_the_lines_due_projection
    """
    ground, _caustic_cycle, acid_cycle = _two_cycles_three_weeks_apart(api)

    fixtures.void_cycle(api, acid_cycle["id"], "Logged against the wrong line by the crew.")

    replayed = fixtures.read_line(api, ground["line"]["id"])
    assert_line_projection(
        replayed,
        last_chemical_type="CAUSTIC",
        last_cleaned_at="2026-08-05T09:00:00Z",
        next_due_at="2026-08-26T09:00:00Z",
        days_overdue=0,
        compliance_flag=ComplianceFlag.COMPLIANT,
        status=LineStatus.IN_SERVICE,
    )
    assert fixtures.read_account(api, ground["account"]["id"])["lines_out_of_service_count"] == 0
