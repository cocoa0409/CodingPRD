"""Derived figures whose value depends on which constant each selector picked."""

from test_helpers import (
    BalanceRecordStatus,
    BalanceState,
    ComplianceFlag,
    ComplianceResult,
    LineStatus,
    assert_liters,
    assert_pct,
    assert_psi,
    fixtures,
)

GAS_LINES = (
    {
        "line_number": 1,
        "run_length_feet": 32,
        "vertical_rise_feet": 4,
        "inner_diameter_inches": 0.375,
        "beer_style_group": "ALE",
        "average_daily_throughput_liters": 12.0,
    },
    {
        "line_number": 2,
        "run_length_feet": 32,
        "vertical_rise_feet": 4,
        "inner_diameter_inches": 0.375,
        "beer_style_group": "LAGER",
        "average_daily_throughput_liters": 12.0,
    },
    {
        "line_number": 3,
        "run_length_feet": 32,
        "vertical_rise_feet": 4,
        "inner_diameter_inches": 0.25,
        "beer_style_group": "ALE",
        "average_daily_throughput_liters": 12.0,
    },
)


def _gas_ground(api):
    return fixtures.setup_started_visit(
        api,
        venue_name="Gasworks Bar",
        lines=GAS_LINES,
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )


def _propose(api, ground, line_index, **kwargs):
    """Re-read the line first: every accepted proposal bumps the line's version."""
    line = fixtures.read_line(api, ground["lines"][line_index]["id"])
    return fixtures.propose_balance(
        api,
        ground["visit"]["id"],
        line["id"],
        line["version"],
        ground["technician"]["id"],
        **kwargs,
    )


def test_style_group_and_temperature_band_each_move_the_carbonation_target(api):
    """PRD §3.5: "The style group and band together select the target: an `ALE` line
    targets 2.4 volumes cold, 2.5 mild and 2.6 warm; a `LAGER` line targets 2.6 cold,
    2.7 mild and 2.8 warm; a `CIDER` line targets 2.8 cold, 2.9 mild and 3.0 warm."
    PRD §3.5: "at or below 38.0 degrees Fahrenheit the band is cold, above that and at
    or below 42.0 it is mild, and above 42.0 it is warm — so 38.0 is cold, 38.1 is
    mild, 42.0 is mild and 42.1 is warm."

    Design: Difficulty/combinatorial_formula/gas_balance_style_temperature_band_and_bore_each_swap_one_constant
    """
    ground = _gas_ground(api)

    mild_ale = _propose(
        api, ground, 0, measured_temp_f=40.0, proposed_applied_psi=13.6, proposed_co2_pct=59.2
    )
    cold_ale = _propose(
        api, ground, 0, measured_temp_f=38.0, proposed_applied_psi=13.6, proposed_co2_pct=48.5
    )
    mild_lager = _propose(
        api, ground, 1, measured_temp_f=40.0, proposed_applied_psi=13.6, proposed_co2_pct=67.3
    )

    assert mild_ale["target_co2_volumes"] == 2.5
    assert_psi(mild_ale["equilibrium_psi"], 8.05)
    assert_psi(mild_ale["total_restriction_psi"], 13.60)
    assert_psi(mild_ale["required_applied_psi"], 13.60)
    assert_pct(mild_ale["required_co2_pct"], 59.2)
    assert mild_ale["balance_state"] == BalanceState.RESTRICTION_HIGH

    assert cold_ale["target_co2_volumes"] == 2.4, (
        "dropping the measured temperature onto the cold-band edge lowers the target"
    )
    assert_psi(cold_ale["equilibrium_psi"], 6.60)
    assert_psi(cold_ale["total_restriction_psi"], 13.60)
    assert_pct(cold_ale["required_co2_pct"], 48.5)

    assert mild_lager["target_co2_volumes"] == 2.7, (
        "the same temperature on a lager line selects the lager column"
    )
    assert_psi(mild_lager["equilibrium_psi"], 9.15)
    assert_psi(mild_lager["total_restriction_psi"], 13.60)
    assert_pct(mild_lager["required_co2_pct"], 67.3)
    assert mild_ale["status"] == BalanceRecordStatus.PROPOSED


def test_bore_moves_the_restriction_and_the_blend_share_is_clamped_after_rounding(api):
    """PRD §3.5: "Multiply `run_length_feet` by the per-foot restriction of the bore —
    2.2 psi per foot at 0.1875 inches, 0.85 at 0.25 inches and 0.30 at 0.375 inches —
    add `vertical_rise_feet` multiplied by 0.5 psi per foot of rise, add the flat
    faucet loss of 2.0 psi, and round the total half up to two decimal places."
    PRD §3.5: "divide `equilibrium_psi` by `required_applied_psi`, multiply by 100, round
    half up to one decimal place, and then — after rounding, never before — clamp the result
    to be at least 40.0 and at most 100.0, because no practical blend runs leaner than forty
    per cent carbon dioxide."

    Design: Difficulty/combinatorial_formula/gas_balance_style_temperature_band_and_bore_each_swap_one_constant
    """
    ground = _gas_ground(api)

    wide_bore = _propose(
        api, ground, 0, measured_temp_f=40.0, proposed_applied_psi=13.6, proposed_co2_pct=59.2
    )
    narrow_bore = _propose(
        api, ground, 2, measured_temp_f=40.0, proposed_applied_psi=31.2, proposed_co2_pct=40.0
    )

    assert narrow_bore["target_co2_volumes"] == 2.5, (
        "narrowing the bore leaves the carbonation target untouched"
    )
    assert_psi(narrow_bore["equilibrium_psi"], 8.05)
    # 32 ft at 0.85 psi plus 4 ft of rise plus the 2.0 psi faucet loss is 31.20.
    assert_psi(narrow_bore["total_restriction_psi"], 31.20)
    assert_psi(narrow_bore["required_applied_psi"], 31.20)
    # 8.05 over 31.20 is 25.8 per cent, which the floor lifts to 40.0.
    assert_pct(narrow_bore["required_co2_pct"], 40.0)
    assert narrow_bore["balance_state"] == BalanceState.RESTRICTION_HIGH
    assert narrow_bore["status"] == BalanceRecordStatus.PROPOSED
    assert wide_bore["total_restriction_psi"] != narrow_bore["total_restriction_psi"]


def _rounding_ground(api):
    """Three lines on a 28-day contract, all three circulated to a pass, no parts."""
    return fixtures.setup_three_line_visit_with_work(
        api,
        venue_name="Rounding Room",
        cleaning_frequency_days=28,
        third_line_cycle={
            "chemical_type": "CAUSTIC",
            "contact_minutes": 15,
            "recirculation_temp_f": 96.0,
            "concentrate_liters_used": 0.18,
        },
        replace_faucet=False,
    )


def test_the_per_line_amount_is_rounded_before_the_line_count_multiplies_it(api):
    """PRD §3.7: "The **per-line amount** is the contract's `per_line_rate_cents`
    multiplied by its `frequency_multiplier`, rounded half up to whole cents, computed
    once and then applied identically to every billable line."
    PRD §3.7: "`cleaning_subtotal_cents` is `billable_line_count` multiplied by the
    per-line amount, less the waiver withholding."

    Design: Difficulty/combinatorial_formula/visit_charge_rounds_per_line_before_summing_not_after
    """
    ground = _rounding_ground(api)

    assert ground["contract"]["frequency_multiplier"] == 1.25
    third_cycle = ground["cycles"][2]
    assert third_cycle["effective_active_pct"] == 2.025
    assert third_cycle["compliance_result"] == ComplianceResult.PASS

    visit = ground["visit"]
    assert visit["serviced_line_count"] == 3
    assert visit["parts_charge_cents"] == 0, "no inspection replaced a part on this job"
    assert visit["cleaning_subtotal_cents"] == 15657, (
        "4175 at 1.25 rounds to 5219 per line, so three lines come to 15657, got "
        f"{visit['cleaning_subtotal_cents']}"
    )
    assert visit["cleaning_subtotal_cents"] != 15656, (
        "rounding the aggregate instead of the per-line amount would have given 15656"
    )
    assert visit["provisional_charge_cents"] == 23157, (
        f"7500 base plus 15657 cleaning is 23157, got {visit['provisional_charge_cents']}"
    )


def test_the_settled_subtotal_reuses_the_same_rounded_per_line_amount(api):
    """PRD §3.7: "The charge is the contract's `visit_base_fee_cents` plus
    `cleaning_subtotal_cents` plus `parts_charge_cents`; the base fee is charged once per
    visit regardless of how many lines were billable, including when no line was billable at
    all."

    Design: Difficulty/combinatorial_formula/visit_charge_rounds_per_line_before_summing_not_after
    """
    ground = _rounding_ground(api)

    signed = fixtures.sign_visit(api, ground["visit"]["id"], ground["account"]["id"])

    assert signed["billable_line_count"] == 3, "all three lines passed their grade"
    assert signed["cleaning_subtotal_cents"] == 15657
    assert signed["settled_charge_cents"] == 23157, (
        f"the settled figure matches the provisional here, got {signed['settled_charge_cents']}"
    )
    assert signed["account_due_cents"] == 23157


def _tier_ground(api):
    """Two lines of identical geometry, one lot of 45.0 per cent caustic."""
    return fixtures.setup_started_visit(
        api,
        venue_name="Tier Test Taproom",
        lines=(
            dict(fixtures.DEFAULT_LINE, line_number=1),
            dict(fixtures.DEFAULT_LINE, line_number=2),
        ),
        lot_specs=({"lot_code": "C-4001", "concentration_pct_stock": 45.0, "liters_initial": 20.0},),
        scheduled_end_minute=720,
    )


def test_the_contact_tier_follows_the_achieved_strength_not_the_prescribed_dose(api):
    """PRD §3.4: "**`required_contact_minutes`** — the dwell time the achieved strength
    demands. This tier is selected from the **achieved** strength, never from the
    prescribed dose: a weaker solution must sit in the line longer. For a `CAUSTIC`
    cycle, an `effective_active_pct` of at least 2.0 requires 15 minutes, at least 1.5
    requires 20 minutes, and anything weaker requires 30 minutes."
    PRD §3.4: "Rounding up rather than to nearest matters: a holdup of 2.214 liters
    gives a product of 6.642, which becomes 7 liters, not 6."

    Design: Difficulty/combinatorial_formula/caustic_contact_tier_selected_by_achieved_strength_not_prescribed_dose
    """
    ground = _tier_ground(api)

    cycle = fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["lines"][0]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        chemical_type="CAUSTIC",
        contact_minutes=20,
        recirculation_temp_f=96.0,
        concentrate_liters_used=0.31,
    )

    assert_liters(cycle["line_volume_liters"], 2.214)
    assert cycle["total_solution_liters"] == 7
    assert_liters(cycle["prescribed_concentrate_liters"], 0.31)
    assert cycle["effective_active_pct"] == 1.993, (
        "0.31 litres of 45.0 per cent stock in 7 litres achieves 1.993 per cent, got "
        f"{cycle['effective_active_pct']}"
    )
    assert cycle["required_contact_minutes"] == 20, (
        "an achievement just under the 2.0 tier edge demands 20 minutes, not 15"
    )
    assert cycle["compliance_result"] == ComplianceResult.PASS
    line = fixtures.read_line(api, ground["lines"][0]["id"])
    assert line["status"] == LineStatus.IN_SERVICE


def test_dwelling_one_minute_short_of_the_achieved_tier_fails_the_grade(api):
    """PRD §3.4: "Otherwise, if `contact_minutes` is below `required_contact_minutes`,
    the grade is `FAIL_CONTACT_TIME`."
    PRD §3.4: "Hop one takes the line `IN_SERVICE → OUT_OF_SERVICE` with
    `compliance_flag` set to `NON_COMPLIANT`, moves every balance record on that line
    whose status is `APPLIED` to `SUPERSEDED`, and increments the line's `version` by 1."

    Design: Difficulty/combinatorial_formula/caustic_contact_tier_selected_by_achieved_strength_not_prescribed_dose
    """
    ground = _tier_ground(api)
    dose = {
        "chemical_type": "CAUSTIC",
        "recirculation_temp_f": 96.0,
        "concentrate_liters_used": 0.31,
    }
    fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["lines"][0]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        contact_minutes=20,
        **dose,
    )

    short = fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["lines"][1]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        contact_minutes=19,
        **dose,
    )

    assert short["effective_active_pct"] == 1.993
    assert short["required_contact_minutes"] == 20
    assert short["compliance_result"] == ComplianceResult.FAIL_CONTACT_TIME, (
        f"19 minutes against a 20-minute demand must fail, got {short['compliance_result']}"
    )
    lot = fixtures.read_lot(api, ground["lot"]["id"])
    assert_liters(lot["liters_remaining"], 19.380), "both draws of 0.31 litres came off the lot"
    second_line = fixtures.read_line(api, ground["lines"][1]["id"])
    assert second_line["status"] == LineStatus.OUT_OF_SERVICE
    assert second_line["compliance_flag"] == ComplianceFlag.NON_COMPLIANT
    account = fixtures.read_account(api, ground["account"]["id"])
    assert account["lines_out_of_service_count"] == 1
    assert account["status"] == "ACTIVE", (
        "one line out of four contracted lines is below the doubling threshold"
    )
