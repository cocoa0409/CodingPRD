"""Derived calculations: the warranty gate cascade, the cycle-life conjunction,
the posture breakpoint, the pinned yield mean and the fleet-sizing walk."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import (
    assert_close,
    assert_emission_ledger,
    assert_lot_counters,
    assert_posture,
    assert_sampling_plan,
    assert_unit_axes,
    assert_warranty_settlement,
)
from test_helpers.factories import (
    adjudication_payload,
    assembly_payload,
    charger_payload,
    cycle_report_payload,
    sizing_request_payload,
    warranty_claim_payload,
    watering_log_payload,
)
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import validate_error, validate_success

# A unit shipped at the post-release clock instant of 2026-09-03T14:00:00Z is
# exactly 240 days old at this instant, so months_in_service is floor(240 / 30) = 8.
SHIPPED_AT = "2026-09-03T14:00:00Z"
CLAIM_CLOCK = "2027-05-01T14:00:00Z"
REPORTED_AT = "2027-04-25T00:00:00Z"

# The seven monthly watering visits a compliant unit receives, plus the eighth
# visit that finds the electrolyte low and therefore never counts.
WATERING_OK_DATES = [
    "2026-10-01T00:00:00Z",
    "2026-11-01T00:00:00Z",
    "2026-12-01T00:00:00Z",
    "2027-01-01T00:00:00Z",
    "2027-02-01T00:00:00Z",
    "2027-03-01T00:00:00Z",
    "2027-04-01T00:00:00Z",
]
WATERING_FAILED_DATE = "2027-04-15T00:00:00Z"
CYCLE_REPORT_DATE = "2027-04-20T00:00:00Z"


def _ship(world: World, serials):
    """Release one lot of 9 and ship the named units, then age them 240 days."""
    lot = world.released_lot("LOT-W", 9)
    units = [world.ship_unit(lot["id"], serial) for serial in serials]
    for unit in units:
        assert unit["shipped_at"].startswith("2026-09-03T14:00:00")
        assert_unit_axes(unit, C.WARRANTY_IN_SERVICE, C.CORE_DEPOSIT_HELD)
    world.set_clock(CLAIM_CLOCK)
    return units


def _log(world: World, unit_id: str, payload):
    return validate_success(
        world.api.create_maintenance_log(unit_id, payload, world.warranty), 201
    )


def _water(world: World, unit_id: str, dates, electrolyte_level_ok: bool = True):
    for date in dates:
        _log(world, unit_id, watering_log_payload(date, electrolyte_level_ok))


def _claim(world: World, unit_id: str, complaint_code: str = "CAPACITY_LOSS"):
    version = world.read_unit(unit_id)["version"]
    return validate_success(
        world.api.open_warranty_claim(
            unit_id,
            warranty_claim_payload(version, complaint_code, reported_at=REPORTED_AT),
            world.warranty,
        ),
        201,
    )


def _adjudicate(world: World, unit_id: str, finding: str):
    validate_success(
        world.api.adjudicate_warranty(
            unit_id, adjudication_payload(finding), world.warranty
        ),
        200,
    )
    return world.read_unit(unit_id)


def test_a_prorated_credit_applies_the_reduced_multiplier_once_at_the_end(world: World):
    """Eight months, seven good waterings and 600 cycles settle at 270000 cents.

    "First `usage_fraction` is recomputed as the **larger** of two independent consumption
    measures: the cycle fraction, `cycle_count` divided by the pinned design's `rated_cycles`, and
    the calendar fraction, `months_in_service` divided by the pinned design's `warranty_months`."
    The ratio side is "the smaller of 1.0 and `watering_events_ok` divided by
    `watering_events_expected`, rounded half up to four decimal places", counting only "`WATERING`
    log rows whose `electrolyte_level_ok` is true". The fifth gate then settles it: "the credit is
    `list_price_cents` multiplied by one minus `usage_fraction`, multiplied by that multiplier,
    rounded half up to a whole cent" -- 500000 times 0.6000 times 0.90.

    Design: Corner/calculations/warranty_settlement_gate_ladder_decides_four_units_in_pinned_order
    """
    (unit_a,) = _ship(world, ["BU-W-001"])
    _water(world, unit_a["id"], WATERING_OK_DATES)
    _water(world, unit_a["id"], [WATERING_FAILED_DATE], electrolyte_level_ok=False)

    cycle_row = _log(world, unit_a["id"], cycle_report_payload(CYCLE_REPORT_DATE, 600))
    assert cycle_row["resulting_cycle_count"] == 600
    assert_close(
        cycle_row["resulting_compliance_ratio"], 0.8750, "resulting_compliance_ratio", 4
    )

    _claim(world, unit_a["id"])
    opened = world.read_unit(unit_a["id"])
    assert opened["warranty_status"] == C.WARRANTY_CLAIM_OPEN
    assert opened["claim_count"] == 1
    assert opened["last_claim_at"].startswith("2027-04-25T00:00:00")
    assert opened["warranty_decision"] is None
    assert opened["warranty_credit_cents"] == 0

    settled = _adjudicate(world, unit_a["id"], C.FINDING_DEFECT_CONFIRMED)
    assert settled["months_in_service"] == 8
    assert settled["watering_events_expected"] == 8
    assert settled["watering_events_ok"] == 7
    assert_close(settled["watering_compliance_ratio"], 0.8750, "watering_compliance_ratio", 4)
    assert settled["cycle_count"] == 600
    assert_close(settled["usage_fraction"], 0.4000, "usage_fraction", 4)
    assert settled["warranty_status"] == C.WARRANTY_CLAIM_PRORATED
    assert_warranty_settlement(settled, C.DECISION_PRORATED, 270000)
    assert settled["claim_count"] == 1


def test_the_usage_gate_outranks_the_maintenance_gate_on_an_exhausted_unit(world: World):
    """A unit at 1.0000 usage is denied for usage even though its watering is worse.

    "Otherwise, when `usage_fraction` is greater than or equal to 1.0000, the decision is
    `DENIED_USAGE` with a credit of 0. Exactly 1.0000 denies -- the warranty is exhausted at the
    boundary, not just beyond it." The gate below it would also have fired: "Otherwise, when the
    unit's chemistry is `LEAD_ACID` **and** its `watering_compliance_ratio` is strictly below
    0.8000, the decision is `DENIED_MAINTENANCE` with a credit of 0." Since "the first gate that
    fires decides everything", the recorded reason separates the two units.

    Design: Corner/calculations/warranty_settlement_gate_ladder_decides_four_units_in_pinned_order
    """
    unit_b, unit_c = _ship(world, ["BU-W-002", "BU-W-003"])
    _water(world, unit_b["id"], WATERING_OK_DATES[:2])
    _log(world, unit_c["id"], cycle_report_payload(CYCLE_REPORT_DATE, 1500))

    _claim(world, unit_b["id"])
    _claim(world, unit_c["id"])

    settled_b = _adjudicate(world, unit_b["id"], C.FINDING_DEFECT_CONFIRMED)
    assert settled_b["months_in_service"] == 8
    assert settled_b["watering_events_ok"] == 2
    assert_close(settled_b["watering_compliance_ratio"], 0.2500, "watering_compliance_ratio", 4)
    assert settled_b["cycle_count"] == 0
    assert_close(settled_b["usage_fraction"], 0.1333, "usage_fraction", 4)
    assert settled_b["warranty_status"] == C.WARRANTY_CLAIM_DENIED
    assert_warranty_settlement(settled_b, C.DECISION_DENIED_MAINTENANCE, 0)

    settled_c = _adjudicate(world, unit_c["id"], C.FINDING_DEFECT_CONFIRMED)
    assert settled_c["cycle_count"] == 1500
    assert_close(settled_c["usage_fraction"], 1.0000, "usage_fraction", 4)
    assert_close(settled_c["watering_compliance_ratio"], 0.0000, "watering_compliance_ratio", 4)
    assert settled_c["warranty_status"] == C.WARRANTY_CLAIM_DENIED
    assert_warranty_settlement(settled_c, C.DECISION_DENIED_USAGE, 0)
    assert settled_c["claim_count"] == 1
    assert settled_c["last_claim_at"].startswith("2027-04-25T00:00:00")


def test_the_no_defect_gate_outranks_every_gate_below_it(world: World):
    """A no-defect finding denies first, so the poor watering never gets a say.

    "When `inspection_finding` is `NO_DEFECT_FOUND`, the decision is `DENIED_NO_DEFECT` with a
    credit of 0. This gate is first, so a no-defect finding denies the claim even on a brand-new
    battery with perfect maintenance." The unit's 0.2500 compliance ratio would have denied it one
    gate later, but "all three denial reasons collapse onto the single `CLAIM_DENIED` state while
    `warranty_decision` preserves which gate fired".

    Design: Corner/calculations/warranty_settlement_gate_ladder_decides_four_units_in_pinned_order
    """
    (unit_d,) = _ship(world, ["BU-W-004"])
    _water(world, unit_d["id"], WATERING_OK_DATES[:2])

    _claim(world, unit_d["id"], complaint_code="CASE_CRACK")
    settled = _adjudicate(world, unit_d["id"], C.FINDING_NO_DEFECT)

    assert settled["months_in_service"] == 8
    assert_close(settled["watering_compliance_ratio"], 0.2500, "watering_compliance_ratio", 4)
    assert_close(settled["usage_fraction"], 0.1333, "usage_fraction", 4)
    assert settled["warranty_status"] == C.WARRANTY_CLAIM_DENIED
    assert_warranty_settlement(settled, C.DECISION_DENIED_NO_DEFECT, 0)
    assert settled["claim_count"] == 1


def test_a_cycle_life_sample_one_cycle_short_fails_but_still_stamps_its_yield(world: World):
    """1349 cycles against a 1350 ceiling fails even sitting exactly on the fade floor.

    "A `CYCLE_LIFE` test is a two-criterion conjunction: it is a `PASS` only when
    `cycles_completed` is greater than or equal to the ceiling of the pinned design's
    `rated_cycles` multiplied by 0.90, **and** the measured capacity is greater than or equal to the
    pinned `nominal_capacity_ah` multiplied by 0.80 and rounded to one decimal place", and "Failing
    either criterion fails the test." The verdict does not suppress the ratio, because "`yield_pct`
    is the measured capacity divided by the pinned design's `nominal_capacity_ah`, multiplied by
    100, rounded half up to two decimal places, and is stored on every test regardless of verdict."
    With no passing row in the window, "When that window is empty the yield is null."

    Design: Corner/calculations/cycle_life_test_fails_one_cycle_short_of_the_ceiling_despite_end_of_life_capacity
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-C", 50)
    assembly = world.certify_assembly(lot["id"], "ASM-C1")
    chamber_id = world.add_chamber()

    plan = world.draw_plan(lot["id"])
    assert_sampling_plan(plan, sample_size=8, acceptance_number=1, revision=1)
    assert plan["process_state"] == C.LOT_TESTING

    test = world.schedule_test(
        assembly["id"], chamber_id, "2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z",
        test_type=C.TEST_TYPE_CYCLE_LIFE,
    )
    world.set_clock("2026-09-03T10:00:00Z")

    recorded = world.record_cycle_life(test["id"], 372.0, 1349)
    assert recorded["test_state"] == C.TEST_STATE_COMPLETED
    assert recorded["result"] == C.CAPACITY_RESULT_FAIL
    assert recorded["cycles_completed"] == 1349
    assert_close(recorded["measured_capacity_ah"], 372.0, "measured_capacity_ah", 1)
    assert_close(recorded["yield_pct"], 80.00, "yield_pct", 2)

    summary = validate_success(
        world.api.get_quality_summary(lot["id"], world.qa_a), 200
    )
    assert summary["completed_test_count"] == 1
    assert summary["failed_test_count"] == 1
    assert summary["passed_cycle_life_count"] == 0
    assert summary["lot_capacity_yield_pct"] is None
    assert summary["release_blocked_by"] == E.ERR_SAMPLING_INCOMPLETE

    after = world.read_lot(lot["id"])
    assert after["process_state"] == C.LOT_TESTING
    assert_lot_counters(after, completed=1, failed=1, passed_cycle_life=0)
    assert after["lot_capacity_yield_pct"] is None


def test_a_ratio_landing_exactly_on_0_8500_restricts_the_plant_and_blocks_the_start(make_world):
    """255.00 g reserved against a 300.00 g permit is exactly 0.8500, which already restricts.

    "the sum of `emission_reserved_g` and `emission_consumed_g` is divided by
    `monthly_lead_emission_permit_g` and the quotient is rounded half up to four decimal places",
    then "Otherwise the plant is `RESTRICTED` if its `open_medical_removal_count` is exactly one, or
    its utilization ratio is at least 0.8500", and "Both ratio breakpoints are inclusive: a ratio of
    exactly 0.8500 restricts the plant, and a ratio of exactly 1.0000 freezes it." The restriction is
    narrow: "Becoming `RESTRICTED` blocks two things and only two things: no lot may enter
    `FORMATION`, and no `SCHEDULED` formation run may be started."

    Design: Corner/calculations/emission_posture_flips_to_restricted_at_exactly_the_0_8500_utilization_ratio
    """
    world = make_world(plant_overrides={"monthly_lead_emission_permit_g": 300.00})
    bay_id = world.add_bay()
    lot = world.lot_in_state(C.LOT_FORMATION, "LOT-E", 9)
    assert_posture(world.read_plant(), C.POSTURE_OPEN)

    run = world.schedule_run(lot["id"], bay_id)
    assert_close(run["estimated_energy_kwh"], 102.00, "estimated_energy_kwh", 2)
    assert_close(run["reserved_emission_g"], 255.00, "reserved_emission_g", 2)
    assert run["run_state"] == C.RUN_STATE_SCHEDULED

    ledger = world.read_ledger()
    assert_emission_ledger(ledger, reserved_g=255.00, consumed_g=0.00, ratio=0.8500)
    assert ledger["compliance_posture"] == C.POSTURE_RESTRICTED

    world.set_clock("2026-09-02T06:00:00Z")
    validate_error(
        world.api.start_formation_run(run["id"], world.sup_a), E.ERR_PLANT_RESTRICTED
    )
    assert world.read_run(run["id"])["run_state"] == C.RUN_STATE_SCHEDULED

    plant = world.read_plant()
    assert_posture(plant, C.POSTURE_RESTRICTED)
    assert plant["open_medical_removal_count"] == 0

    # Posture is not what refuses an assembly on a FORMATION lot: state legality is tier 11 and
    # ERR_PLANT_RESTRICTED does not guard POST /battery-assemblies at all.
    validate_error(
        world.api.create_battery_assembly(
            assembly_payload(lot["id"], "ASM-E1"), world.sup_a
        ),
        E.ERR_LOT_STATE_INVALID,
    )


def test_the_lot_yield_is_the_mean_of_the_rounded_pass_yields_only(world: World):
    """95.01 and 95.08 average to 95.05, and the failing 94.99 never enters the window.

    "The window is the set of tests belonging to assemblies of this lot whose `test_state` is
    `COMPLETED`, whose `result` is `PASS`", and within it "each test's `yield_pct` was already
    rounded half up to two decimal places when its result was recorded, and the lot figure is the
    arithmetic mean of those already-rounded values, rounded half up to two decimal places again."
    The rival arithmetic is named and refused: "The pooled alternative -- summing raw measured
    capacities and dividing by the sample count times nominal capacity -- is explicitly **rejected**
    and produces a different number." The verdicts come from the threshold rule, "greater than or
    equal to the pinned `nominal_capacity_ah` multiplied by 0.95 and **rounded to one decimal place
    before the comparison**", which is 441.8 Ah.

    Design: Corner/calculations/lot_capacity_yield_averages_the_already_rounded_pass_yields_and_drops_the_failure
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-Y", 50)
    assembly = world.certify_assembly(lot["id"], "ASM-Y1")
    chamber_id = world.add_chamber()

    plan = world.draw_plan(lot["id"])
    assert_sampling_plan(plan, sample_size=8, acceptance_number=1, revision=1)

    windows = [
        ("2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z"),
        ("2026-09-03T10:00:00Z", "2026-09-03T12:00:00Z"),
        ("2026-09-03T12:00:00Z", "2026-09-03T14:00:00Z"),
    ]
    tests = [
        world.schedule_test(assembly["id"], chamber_id, start, end)
        for start, end in windows
    ]
    world.set_clock("2026-09-03T14:00:00Z")

    first = world.record_capacity(tests[0]["id"], 441.8)
    assert first["result"] == C.CAPACITY_RESULT_PASS
    assert_close(first["yield_pct"], 95.01, "yield_pct", 2)

    second = world.record_capacity(tests[1]["id"], 442.1)
    assert second["result"] == C.CAPACITY_RESULT_PASS
    assert_close(second["yield_pct"], 95.08, "yield_pct", 2)

    third = world.record_capacity(tests[2]["id"], 441.7)
    assert third["result"] == C.CAPACITY_RESULT_FAIL
    assert_close(third["yield_pct"], 94.99, "yield_pct", 2)

    summary = validate_success(world.api.get_quality_summary(lot["id"], world.qa_a), 200)
    assert summary["completed_test_count"] == 3
    assert summary["failed_test_count"] == 1
    assert_close(summary["lot_capacity_yield_pct"], 95.05, "lot_capacity_yield_pct", 2)

    after = world.read_lot(lot["id"])
    assert after["process_state"] == C.LOT_TESTING
    assert_close(after["lot_capacity_yield_pct"], 95.05, "lot_capacity_yield_pct", 2)
    assert_lot_counters(after, completed=3, failed=1, passed_cycle_life=0)


def test_the_selector_takes_the_smallest_feasible_pack_then_the_cheapest_charger(make_world):
    """465 Ah beats 600 Ah on capacity ascending, and 250000 cents beats 50 amps on price.

    "the pool is ordered by `nominal_capacity_ah` ascending, then by `pack_weight_kg` ascending,
    then by `created_at` ascending. The smallest sufficient pack wins: this is a least-cost-fit
    policy, not a largest-capacity policy." Inside that pack, "`selected_charger_id` to the cheapest
    feasible charger ordered by `price_cents` ascending then `output_amps` ascending then
    `created_at` ascending", where recharge time is the capacity "multiplied by the depth-of-discharge
    cap for its chemistry ... multiplied by the sizing charge factor for that chemistry, which is
    1.15 for `LEAD_ACID` ... then divided by the charger's `output_amps` and rounded half up to two
    decimal places". The quote is inert until decided: "The request is created with `request_state`
    `MATCHED`."

    Design: Corner/calculations/fleet_sizing_picks_the_smallest_feasible_pack_then_the_cheapest_matching_charger
    """
    world = make_world(with_design=False)
    small_id = world.approved_lead_design()
    big_id = world.approved_lead_design(
        "CD-LEAD-600",
        nominal_capacity_ah=600.0,
        pack_weight_kg=950.0,
        lead_content_kg=380.000,
        list_price_cents=700000,
    )
    assert small_id != big_id

    fast = validate_success(
        world.api.create_charger(
            charger_payload(
                "CH-A50",
                chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
                output_voltage_v=24.0,
                output_amps=50.0,
                price_cents=300000,
                charge_profile="FERRO",
            ),
            world.fleet,
        ),
        201,
    )
    cheap = validate_success(
        world.api.create_charger(
            charger_payload(
                "CH-B60",
                chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
                output_voltage_v=24.0,
                output_amps=60.0,
                price_cents=250000,
                charge_profile="HF_MODULAR",
            ),
            world.fleet,
        ),
        201,
    )

    quote = validate_success(
        world.api.create_sizing_request(
            sizing_request_payload(
                world.plant_id,
                application_name="Aisle Pickers",
                forklift_class="CLASS_II",
                forklift_count=4,
                shifts_per_day=1,
                shift_energy_kwh_per_shift=8.00,
                required_voltage_v=24.0,
                ambient_temp_c=25.0,
                compartment_max_kg=1000.0,
                charge_window_hours=9.00,
                chemistry_preference=C.CHEMISTRY_PREFERENCE_ANY,
            ),
            world.fleet,
        ),
        201,
    )

    assert_close(quote["daily_energy_kwh"], 8.00, "daily_energy_kwh", 2)
    assert_close(quote["temp_derate_factor"], 1.0000, "temp_derate_factor", 4)
    assert_close(quote["reserve_factor"], 1.05, "reserve_factor", 2)
    assert quote["required_ah"] == 438
    assert quote["evaluated_design_count"] == 2
    assert quote["selected_cell_design_id"] == small_id
    assert quote["selected_charger_id"] == cheap["id"]
    assert quote["selected_charger_id"] != fast["id"]
    assert_close(quote["selected_charge_hours"], 7.13, "selected_charge_hours", 2)
    assert quote["recommended_battery_count"] == 4
    assert quote["recommended_charger_count"] == 2
    assert quote["fleet_capital_cents"] == 2500000
    assert quote["request_state"] == C.SIZING_MATCHED

    analysis = validate_success(
        world.api.get_fleet_analysis(world.plant_id, world.admin), 200
    )
    assert analysis["accepted_request_count"] == 0
    assert analysis["fleet_capital_cents"] == 0
