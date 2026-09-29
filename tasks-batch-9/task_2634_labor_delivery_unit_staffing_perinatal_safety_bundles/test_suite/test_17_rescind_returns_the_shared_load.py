"""Undoing a bundle on a shared nurse is not the same as resetting her ledger.

One bedside nurse carries two ratio-shared patients, priced 0.5 and 0.8, so her
load is 1.3. Loading magnesium on the first patient re-prices only that patient's
row, taking her to 2.8 and straining the unit. Rescinding the bundle has to put
her back on 1.3 exactly — the second patient's 0.8 was never the bundle's to give
back, and the first patient's row must be re-priced in place rather than
released.
"""

import pytest

from test_helpers import (
    activate_hypertension_bundle,
    api_client,
    assert_bundle_activation,
    assert_care_assignment,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    bootstrap_unit,
    checklist_items,
    checklist_items_by_code,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    lift_unit_off_not_ready,
    reload_encounter,
    set_clock,
)

CLOCK_START = "2026-08-24T08:00:00Z"
CLOCK_ACTIVATION = "2026-08-24T09:00:00Z"
CLOCK_COMPLETION = "2026-08-24T09:20:00Z"
SHIFT_START = "2026-08-24T08:00:00Z"
SHIFT_END = "2026-08-24T18:00:00Z"

BASELINE_LOAD = 1.3
STRAINED_LOAD = 2.8
E1_RATIO_PRICE = 0.5
E2_RATIO_PRICE = 0.8
MAGNESIUM_PRICE = 2.0
SHIFT_CAPACITY = 4.0

RESCIND_REASON = (
    "Repeat cuff on the correct arm read 132/84; the severe-range entry was a "
    "documentation error and the bundle is withdrawn."
)

SHARED_STAFF = {
    "charge": {
        "full_name": "Marguerite Adeyinka RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "bedside": {
        "full_name": "Solveig Bergkamp RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Anselm Kirchhoffer MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_shared_ledger_walked_out_and_back():
    """Two ratio-shared patients on one nurse, a magnesium excursion on the first,
    then the rescission that has to undo exactly that excursion."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=SHARED_STAFF,
        unit_overrides={"unit_name": "Halverstock Perinatal Institute"},
    )
    lift_unit_off_not_ready(world, CLOCK_START)
    shift = create_active_shift(world, "bedside", "BEDSIDE", SHIFT_START, SHIFT_END)
    e1 = create_encounter(
        world,
        patient_record_code="PRC-WALK-9051",
        parity=1,
        gestational_age_weeks=39,
        prior_cesarean=False,
        fetus_count=1,
        presentation="VERTEX",
    )
    e2 = create_encounter(
        world,
        patient_record_code="PRC-WALK-9052",
        parity=2,
        gestational_age_weeks=39,
        prior_cesarean=True,
        fetus_count=1,
        presentation="VERTEX",
    )
    row_1 = create_care_assignment(world, e1, shift, coverage_mode="RATIO_SHARED")
    row_2 = create_care_assignment(world, e2, shift, coverage_mode="RATIO_SHARED")
    shift_before = get_success_data(
        api_client.get_shift(shift["id"], world.charge_headers)
    )
    unit_before = world.reload_unit()

    set_clock(CLOCK_ACTIVATION)
    activation = activate_hypertension_bundle(
        world, e1, acting_key="ob", systolic_mmhg=168, diastolic_mmhg=114
    )
    magnesium = checklist_items_by_code(world, activation, acting_key="ob")[
        "MAGNESIUM_LOADED"
    ]
    set_clock(CLOCK_COMPLETION)
    completed = get_success_data(
        api_client.complete_checklist_item(
            activation["id"],
            magnesium["id"],
            {
                "completed_at": CLOCK_COMPLETION,
                "performed_by_staff_id": world.staff_id("bedside"),
            },
            world.bedside_headers,
        )
    )
    shift_during = get_success_data(
        api_client.get_shift(shift["id"], world.charge_headers)
    )
    e1_during = reload_encounter(world, e1["id"])
    unit_during = world.reload_unit()
    activation_during = get_success_data(
        api_client.get_activation(activation["id"], world.ob_headers)
    )

    rescinded = get_success_data(
        api_client.rescind_activation(
            activation["id"],
            {
                "rescind_reason": RESCIND_REASON,
                "expected_activation_version": activation_during["version"],
            },
            world.ob_headers,
        )
    )
    return {
        "world": world,
        "shift": shift,
        "e1": e1,
        "e2": e2,
        "row_1": row_1,
        "row_2": row_2,
        "activation": activation,
        "magnesium": magnesium,
        "completed": completed,
        "shift_before": shift_before,
        "unit_before": unit_before,
        "shift_during": shift_during,
        "e1_during": e1_during,
        "unit_during": unit_during,
        "activation_during": activation_during,
        "rescinded": rescinded,
    }


def test_the_two_shared_rows_are_priced_one_at_a_time(
    a_shared_ledger_walked_out_and_back,
):
    """"A `RATIO_SHARED` row debits the product of two factors: the acuity weight,
    which is 1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and 4.0 for
    `TIER_IV`; and the phase multiplier, which is 0.5 for `ANTEPARTUM`" — and
    "The price of a row is computed at one decimal place with halves rounded away from
    zero.", so 1.5 * 0.5 rounds to 0.8 on the row, giving a sum of 1.3.

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    assert_care_assignment(setup["row_1"])
    assert_care_assignment(setup["row_2"])
    assert setup["row_1"]["acuity_units_consumed"] == pytest.approx(
        E1_RATIO_PRICE, abs=1e-9
    )
    assert setup["row_2"]["acuity_units_consumed"] == pytest.approx(
        E2_RATIO_PRICE, abs=1e-9
    )
    shift = setup["shift_before"]
    assert_shift_assignment(shift)
    assert shift["capacity_units_effective"] == pytest.approx(SHIFT_CAPACITY, abs=1e-9)
    assert shift["assigned_acuity_load_units"] == pytest.approx(BASELINE_LOAD, abs=1e-9)
    unit = setup["unit_before"]
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["turnover_buffer_minutes"] == 45


def test_loading_magnesium_re_prices_only_the_one_row(
    a_shared_ledger_walked_out_and_back,
):
    """"`TIER_IV` fires when an activation is in `STAGE_2_ESCALATED` or
    `STAGE_3_MASSIVE_TRANSFUSION`, or `magnesium_infusion_active` is true" — so
    the first patient's row is re-priced to 4.0 * 0.5 and the nurse's total moves
    to 2.8, while the second patient's 0.8 is untouched.

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    assert setup["completed"]["status"] == "COMPLETED"
    e1 = setup["e1_during"]
    assert e1["magnesium_infusion_active"] is True
    assert e1["acuity_tier"] == "TIER_IV"
    assert e1["one_to_one_required"] is True
    assert e1["required_coverage_units"] == pytest.approx(SHIFT_CAPACITY, abs=1e-9)
    assert e1["assigned_coverage_units"] == pytest.approx(MAGNESIUM_PRICE, abs=1e-9)
    assert e1["staffing_state"] == "COVERAGE_BREACH"
    shift = setup["shift_during"]
    assert shift["assigned_acuity_load_units"] == pytest.approx(STRAINED_LOAD, abs=1e-9)
    assert shift["capacity_units_effective"] == pytest.approx(SHIFT_CAPACITY, abs=1e-9)
    assert setup["unit_during"]["coverage_deficit_units"] == pytest.approx(
        2.0, abs=1e-9
    )


def test_the_excursion_was_rescindable_at_stage_one(
    a_shared_ledger_walked_out_and_back,
):
    """"Rescission is the compensating exit, available to an
    `ObstetricianAttending` only before stage 2, that is, while
    `highest_stage_reached` is 1 or less, moving the activation from `ACTIVATED`
    or `STAGE_1_IN_PROGRESS` to `RESCINDED`."

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    during = setup["activation_during"]
    assert during["status"] == "STAGE_1_IN_PROGRESS"
    assert during["highest_stage_reached"] == 1
    rescinded = setup["rescinded"]
    assert_bundle_activation(rescinded)
    assert rescinded["status"] == "RESCINDED"


def test_the_nurse_lands_back_on_one_point_three(
    a_shared_ledger_walked_out_and_back,
):
    """Rescission "restores the encounter's `required_coverage_units`, every
    affected roster entry's `assigned_acuity_load_units` and the unit's
    `coverage_deficit_units` to exactly their pre-activation values by crediting
    the new price and debiting the old" — so the shared sum returns to its
    baseline rather than to zero and rather than staying at its excursion value.

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["assigned_acuity_load_units"] == pytest.approx(BASELINE_LOAD, abs=1e-9)
    assert shift["capacity_units_effective"] == pytest.approx(SHIFT_CAPACITY, abs=1e-9)


def test_both_rows_survive_the_rescission_at_their_own_prices(
    a_shared_ledger_walked_out_and_back,
):
    """The conserved total holds row by row: "the covering entry is credited back
    exactly `acuity_units_consumed`" is what a release does, and no release
    happened here — the first row is re-priced in place back to 0.5 while the
    second still carries the 0.8 that was never the bundle's to give back.

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    world = setup["world"]
    row_1 = get_success_data(
        api_client.get_care_assignment(setup["row_1"]["id"], world.charge_headers)
    )
    row_2 = get_success_data(
        api_client.get_care_assignment(setup["row_2"]["id"], world.charge_headers)
    )
    assert row_1["status"] == "ACTIVE"
    assert row_1["acuity_units_consumed"] == pytest.approx(E1_RATIO_PRICE, abs=1e-9)
    assert row_2["status"] == "ACTIVE"
    assert row_2["acuity_units_consumed"] == pytest.approx(E2_RATIO_PRICE, abs=1e-9)
    total = row_1["acuity_units_consumed"] + row_2["acuity_units_consumed"]
    assert total == pytest.approx(BASELINE_LOAD, abs=1e-9)


def test_the_first_patient_comes_back_to_ratio_covered(
    a_shared_ledger_walked_out_and_back,
):
    """Rescission "clears `magnesium_infusion_active`", "which may return the
    encounter from `COVERAGE_BREACH` to `RATIO_COVERED` or
    `ONE_TO_ONE_COVERED`" — and with no clause left firing, "When no clause fires the tier is `TIER_I`.".

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    e1 = reload_encounter(setup["world"], setup["e1"]["id"])
    assert_labor_encounter(e1)
    assert e1["magnesium_infusion_active"] is False
    assert e1["acuity_tier"] == "TIER_I"
    assert e1["one_to_one_required"] is False
    assert e1["required_coverage_units"] == pytest.approx(E1_RATIO_PRICE, abs=1e-9)
    assert e1["assigned_coverage_units"] == pytest.approx(E1_RATIO_PRICE, abs=1e-9)
    assert e1["staffing_state"] == "RATIO_COVERED"
    assert e1["labor_phase"] == "ANTEPARTUM"


def test_the_second_patient_was_never_part_of_the_bundle(
    a_shared_ledger_walked_out_and_back,
):
    """"`TIER_II` fires when `gestational_age_weeks` is below 37, or `fetus_count` is above
    1, or `presentation` is anything other than `VERTEX`, or `prior_cesarean` is
    true, or `labor_phase` is `ACTIVE_FIRST_STAGE` or `THIRD_STAGE_DELIVERED`.", which is the second
    patient's own reason for costing 0.8, and it is unaffected by anything the
    bundle did to her neighbour.

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    e2 = reload_encounter(setup["world"], setup["e2"]["id"])
    assert_labor_encounter(e2)
    assert e2["acuity_tier"] == "TIER_II"
    assert e2["required_coverage_units"] == pytest.approx(E2_RATIO_PRICE, abs=1e-9)
    assert e2["assigned_coverage_units"] == pytest.approx(E2_RATIO_PRICE, abs=1e-9)
    assert e2["staffing_state"] == "RATIO_COVERED"


def test_every_item_is_voided_and_every_counter_reset(
    a_shared_ledger_walked_out_and_back,
):
    """"Rescission voids every checklist item to `NOT_APPLICABLE` irrespective of its prior
    status, resets `on_time_step_count`, `late_step_count` and `missed_step_count`
    to 0, leaves both scores null forever, clears `magnesium_infusion_active`, and
    restores the encounter's `required_coverage_units`, every affected roster
    entry's `assigned_acuity_load_units` and the unit's `coverage_deficit_units` to
    exactly their pre-activation values by crediting the new price and debiting the
    old, which may return the encounter from `COVERAGE_BREACH` to `RATIO_COVERED` or
    `ONE_TO_ONE_COVERED`."

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    setup = a_shared_ledger_walked_out_and_back
    activation = setup["rescinded"]
    assert activation["on_time_step_count"] == 0
    assert activation["late_step_count"] == 0
    assert activation["missed_step_count"] == 0
    assert activation["timeliness_score"] is None
    assert activation["sequence_adjusted_score"] is None
    items = checklist_items(setup["world"], setup["activation"], acting_key="ob")
    assert len(items) == 4
    assert [item["status"] for item in items] == ["NOT_APPLICABLE"] * 4
    codes = sorted(item["step_code"] for item in items)
    assert codes == [
        "ANTIHYPERTENSIVE_GIVEN",
        "MAGNESIUM_LOADED",
        "OB_AT_BEDSIDE",
        "REPEAT_BP",
    ]


def test_the_unit_returns_to_open_with_the_short_buffer(
    a_shared_ledger_walked_out_and_back,
):
    """"After the posture is settled, and only then, `turnover_buffer_minutes` is
    set to 45 when the posture is `OPEN` and 75 otherwise" — and "The unit's `bundle_breach_count` is left untouched by a rescission.".

    Design: Difficulty/compensating_invariant/bundle_rescind_returns_the_shared_shift_load_to_1_3_not_to_zero_and_not_to_2_8
    """
    unit = a_shared_ledger_walked_out_and_back["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["staffing_posture"] == "OPEN"
    assert unit["turnover_buffer_minutes"] == 45
    assert unit["bundle_breach_count"] == 0
