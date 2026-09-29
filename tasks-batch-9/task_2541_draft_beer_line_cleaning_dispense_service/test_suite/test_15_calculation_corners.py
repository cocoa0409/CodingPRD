"""Corner cases inside the money and score calculations: which rows are in the inclusion
set, where a withholding lands, and where each rounding step happens."""

from test_helpers import (
    ActionTaken,
    AUDITOR_HEADERS,
    ComponentType,
    ConditionGrade,
    GlycolStatus,
    LineStatus,
    ReadingSource,
    SettlementState,
    VerificationStatus,
    assert_instant,
    assert_liters,
    assert_score,
    fixtures,
    get_success_data,
    make_venue_manager_headers,
)

_LINE_ONE = {
    "line_number": 1,
    "run_length_feet": 32,
    "vertical_rise_feet": 4,
    "inner_diameter_inches": 0.375,
    "beer_style_group": "ALE",
    "average_daily_throughput_liters": 12.0,
}
_LINE_TWO = {
    "line_number": 2,
    "run_length_feet": 32,
    "vertical_rise_feet": 4,
    "inner_diameter_inches": 0.375,
    "beer_style_group": "LAGER",
    "average_daily_throughput_liters": 10.0,
}


def _two_line_job(api, **kwargs):
    """A started two-line job with one caustic lot on the van."""
    return fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        lines=(_LINE_ONE, _LINE_TWO),
        lot_specs=({"lot_code": "C-2001"},),
        **kwargs,
    )


def test_a_voided_cycle_and_an_uncharged_inspection_leave_the_inclusion_sets(api):
    """PRD §3.7: "`serviced_line_count` is the number of distinct lines that have a cycle
    record still `POSTED` on this visit."
    PRD §3.7: "`parts_charge_cents` is the sum of `part_charge_cents` across the visit's
    inspections whose `action_taken` was `REPLACED`, and is 0 when nothing was replaced."
    PRD §3.7: "Voided cycles are excluded from both line counts, so voiding the only passing
    cycle on a line drops that line out of the settled inclusion set entirely."
    PRD §3.6: "A replacement consumes a unit and generates a charge: `part_charge_cents` is
    stamped from the catalogue part's `unit_price_cents` and the part's `stock_on_hand` is
    reduced by 1. For any other action, `part_charge_cents` is 0 and no stock moves."
    PRD §3.7: "The charge is the contract's `visit_base_fee_cents` plus
    `cleaning_subtotal_cents` plus `parts_charge_cents`; the base fee is charged once per visit
    regardless of how many lines were billable, including when no line was billable at all."

    Design: Corner/calculations/corner_charge_inclusion_set_skips_voided_cycles_and_unreplaced_parts
    """
    ground = _two_line_job(
        api,
        part_specs=(
            {
                "sku": "FAUCET-88",
                "component_type": "FAUCET",
                "unit_price_cents": 3195,
                "stock_on_hand": 5,
                "brewer_funded_eligible": True,
            },
            {
                "sku": "COUPLER-12",
                "component_type": "COUPLER",
                "unit_price_cents": 1450,
                "stock_on_hand": 5,
                "brewer_funded_eligible": True,
            },
        ),
    )
    visit_id = ground["visit"]["id"]
    technician_id = ground["technician"]["id"]
    line_one, line_two = ground["lines"]
    faucet, coupler = ground["parts"]

    first_cycle = fixtures.log_cleaning_cycle(
        api, visit_id, line_one["id"], ground["lot"]["id"], technician_id,
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    second_cycle = fixtures.log_cleaning_cycle(
        api, visit_id, line_two["id"], ground["lot"]["id"], technician_id,
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    assert first_cycle["compliance_result"] == "PASS"
    voided = fixtures.void_cycle(api, second_cycle["id"], "Logged against the wrong stop.")
    assert voided["record_status"] == "VOIDED"

    looked = fixtures.log_inspection(
        api, visit_id, line_one["id"], technician_id,
        component_type=ComponentType.FAUCET,
        condition_grade=ConditionGrade.GOOD,
        action_taken=ActionTaken.NONE,
    )
    cleaned = fixtures.log_inspection(
        api, visit_id, line_one["id"], technician_id,
        component_type=ComponentType.FAUCET,
        condition_grade=ConditionGrade.WORN,
        action_taken=ActionTaken.CLEANED,
    )
    replaced = fixtures.log_inspection(
        api, visit_id, line_one["id"], technician_id,
        component_type=ComponentType.COUPLER,
        condition_grade=ConditionGrade.WORN,
        action_taken=ActionTaken.REPLACED,
        part_sku_id=coupler["id"],
    )
    assert looked["part_charge_cents"] == 0
    assert cleaned["part_charge_cents"] == 0
    assert replaced["part_charge_cents"] == 1450

    fixtures.set_clock(api, "2026-08-05T10:00:00Z")
    closed = fixtures.complete_work_on(api, visit_id, technician_id)

    # The voided cycle removes line two from both counts.
    assert closed["serviced_line_count"] == 1
    assert closed["billable_line_count"] == 1
    assert closed["cleaning_subtotal_cents"] == 4593
    assert closed["parts_charge_cents"] == 1450
    assert closed["provisional_charge_cents"] == 13543
    # Only the REPLACED row consumed stock.
    assert fixtures.read_part(api, faucet["id"])["stock_on_hand"] == 5
    assert fixtures.read_part(api, coupler["id"])["stock_on_hand"] == 4
    assert_liters(fixtures.read_lot(api, ground["lot"]["id"])["liters_remaining"], 19.690)
    replayed_line_two = fixtures.read_line(api, line_two["id"])
    assert replayed_line_two["last_cleaned_at"] is None
    assert replayed_line_two["status"] == LineStatus.IN_SERVICE


def test_the_waiver_withholding_docks_the_line_total_and_never_the_base_fee(api):
    """PRD §3.7: "On the waiver path only, a withholding is subtracted: take
    `billable_line_count` multiplied by the per-line amount, take ten per cent of that
    pre-withholding line total (a withholding of 1000 basis points), and truncate downward to
    whole cents so the rounding cent favours the venue."
    PRD §3.7: "`cleaning_subtotal_cents` is `billable_line_count` multiplied by the per-line
    amount, less the waiver withholding."
    PRD §3.7: "The charge is the contract's `visit_base_fee_cents` plus
    `cleaning_subtotal_cents` plus `parts_charge_cents`; the base fee is charged once per visit
    regardless of how many lines were billable, including when no line was billable at all."
    PRD §3.7: "If the contract names no `brewer_program_id`, or its `funding_status` is
    anything other than `BREWER_FUNDED`, or the programme's status is anything other than
    `ACTIVE`, then `brewer_funded_cents` is 0, `account_due_cents` is the whole
    `settled_charge_cents`, and the waterfall stops there."

    Design: Corner/calculations/corner_waiver_withhold_docks_exactly_one_thousand_bps_of_the_line_total
    """
    ground = _two_line_job(api)
    visit_id = ground["visit"]["id"]
    technician_id = ground["technician"]["id"]
    for line in ground["lines"]:
        fixtures.log_cleaning_cycle(
            api, visit_id, line["id"], ground["lot"]["id"], technician_id,
            **fixtures.PASSING_CAUSTIC_CYCLE,
        )

    fixtures.set_clock(api, "2026-08-05T10:00:00Z")
    closed = fixtures.complete_work_on(api, visit_id, technician_id)
    assert closed["cleaning_subtotal_cents"] == 9186
    assert closed["provisional_charge_cents"] == 16686

    fixtures.set_clock(api, "2026-08-09T10:00:00Z")
    waived = fixtures.waive_verification(
        api, visit_id, "Venue manager unreachable for four days."
    )

    assert waived["verification_status"] == VerificationStatus.WAIVED
    assert waived["settlement_state"] == SettlementState.SETTLED
    # Ten per cent of 9186 truncates to 918, not 919.
    assert waived["cleaning_subtotal_cents"] == 8268
    assert waived["settled_charge_cents"] == 15768
    assert waived["brewer_funded_cents"] == 0
    assert waived["account_due_cents"] == 15768
    # The provisional figure is not retro-docked, and no signature was captured.
    assert waived["provisional_charge_cents"] == 16686
    assert waived["signer_name"] is None
    assert waived["signed_at"] is None


def test_each_glycol_penalty_is_rounded_before_it_is_subtracted(api):
    """PRD §3.9: "When the window is empty, `window_avg_cooler_temp_f` is null and the
    temperature penalty is zero; otherwise `window_avg_cooler_temp_f` is the mean of the
    window's `cooler_temp_f` values rounded half up to two decimal places."
    PRD §3.9: "The **temperature penalty** is the amount by which `window_avg_cooler_temp_f`
    exceeds the target of 38.0 degrees, multiplied by 8.0 points per degree, and floored at
    zero — a cooler running colder than target earns no credit."
    PRD §3.9: "Subtract all four penalties from 100.0, clamp the result into the range 0.0
    through 100.0, and round half up to two decimal places once more to obtain `health_score`."
    PRD §3.9: "A loop with no readings and its factory bath figures scores exactly 100.00."

    Design: Corner/calculations/corner_glycol_penalties_are_each_rounded_before_they_are_subtracted
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    account = fixtures.create_account(
        api, venue_name="Chiller House", glycol_system_present=True
    )
    loop = fixtures.read_glycol_loop_of(api, account["id"])
    assert_score(loop["health_score"], 100.00)

    readings = fixtures.post_cooler_readings(
        api,
        loop["id"],
        (38.0, 39.0, 39.5),
        make_venue_manager_headers(account["id"]),
        glycol_supply_temp_f=30.0,
    )

    # The source is derived from the caller's role, never supplied.
    assert readings[0]["source"] == ReadingSource.VENUE_MANUAL
    scored = get_success_data(api.get_glycol_loop(loop["id"], AUDITOR_HEADERS))
    # 38.8333... is stored as 38.83 and the penalty is taken from the stored figure.
    assert scored["window_avg_cooler_temp_f"] == 38.83
    # 100.00 - 6.64 = 93.36, not the 93.33 an unrounded average would give.
    assert_score(scored["health_score"], 93.36)
    assert scored["status"] == GlycolStatus.NORMAL
    # No glycol, pump or service penalty contributed.
    assert scored["glycol_pct"] == 35.0
    assert scored["pump_psi"] == 12.0
    assert_instant(scored["last_serviced_at"], scored["created_at"], label="last_serviced_at")


def test_an_ineligible_sku_bills_the_venue_but_never_the_brewer(api):
    """PRD §3.7: "The `PARTS` bucket is the sum of `part_charge_cents` over the visit's
    `REPLACED` inspections whose catalogue part carries `brewer_funded_eligible` set true — a
    part that is not eligible is billed to the venue even under the widest scope, inflating
    `settled_charge_cents` while contributing nothing to this bucket."
    PRD §3.7: "For each bucket in turn, an ineligible bucket is skipped; otherwise the
    brewer's share of that bucket is the bucket amount multiplied by the eligible proportion —
    that is, ten thousand basis points less the programme's `co_pay_bps`, divided by ten
    thousand — truncated downward to whole cents so the brewer never over-funds a bucket by a
    rounding cent."
    PRD §3.7: "The running total becomes the visit's `brewer_funded_cents`, and
    `account_due_cents` is `settled_charge_cents` less that total. The programme's ledger is
    then synchronised: `consumed_cents` rises by the granted amount and `remaining_cents` is
    recomputed as the cap less the consumed figure."

    Design: Corner/calculations/corner_brewer_parts_bucket_excludes_the_ineligible_sku_that_still_bills
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    program = fixtures.create_brewer_program(
        api,
        brewer_name="Kestrel Brewing",
        funded_scope="FULL",
        co_pay_bps=2000,
        funding_cap_cents=100000,
    )
    assert program["remaining_cents"] == 100000
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Alehouse",
        brewer_program_id=program["id"],
        lines=(_LINE_ONE,),
        lot_specs=({"lot_code": "C-2001"},),
        part_specs=(
            {
                "sku": "COUPLER-12",
                "component_type": "COUPLER",
                "unit_price_cents": 1450,
                "stock_on_hand": 5,
                "brewer_funded_eligible": True,
            },
            {
                "sku": "FOB-70",
                "component_type": "FOB",
                "unit_price_cents": 2600,
                "stock_on_hand": 3,
                "brewer_funded_eligible": False,
            },
        ),
    )
    assert ground["contract"]["funding_status"] == "BREWER_FUNDED"
    assert ground["account"]["billing_mode"] == "PROGRAM_BILL"
    visit_id = ground["visit"]["id"]
    technician_id = ground["technician"]["id"]
    coupler, fob = ground["parts"]
    fixtures.log_cleaning_cycle(
        api, visit_id, ground["line"]["id"], ground["lot"]["id"], technician_id,
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    fixtures.log_inspection(
        api, visit_id, ground["line"]["id"], technician_id,
        component_type=ComponentType.COUPLER,
        condition_grade=ConditionGrade.WORN,
        action_taken=ActionTaken.REPLACED,
        part_sku_id=coupler["id"],
    )
    fixtures.log_inspection(
        api, visit_id, ground["line"]["id"], technician_id,
        component_type=ComponentType.FOB,
        condition_grade=ConditionGrade.WORN,
        action_taken=ActionTaken.REPLACED,
        part_sku_id=fob["id"],
    )
    fixtures.set_clock(api, "2026-08-05T10:00:00Z")
    closed = fixtures.complete_work_on(api, visit_id, technician_id)
    assert closed["parts_charge_cents"] == 4050
    assert closed["provisional_charge_cents"] == 16143

    fixtures.set_clock(api, "2026-08-05T11:00:00Z")
    signed = fixtures.sign_visit(
        api, visit_id, ground["account"]["id"], signer_name="Ana Ortiz"
    )

    # The ineligible FOB inflates the charge but contributes nothing to the parts bucket.
    assert signed["settled_charge_cents"] == 16143
    # 3674 of cleaning plus 1160 of eligible parts plus 6000 of base fee.
    assert signed["brewer_funded_cents"] == 10834
    assert signed["account_due_cents"] == 5309
    ledger = fixtures.read_program(api, program["id"])
    assert ledger["consumed_cents"] == 10834
    assert ledger["remaining_cents"] == 89166
    assert ledger["status"] == "ACTIVE"
    # The ineligible part is still consumed and still billed.
    assert fixtures.read_part(api, fob["id"])["stock_on_hand"] == 2
