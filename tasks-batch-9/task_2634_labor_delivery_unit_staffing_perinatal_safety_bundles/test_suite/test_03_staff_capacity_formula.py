"""The nested capacity formula: slot base, certification cap, offset and penalty."""

import pytest

from test_helpers import (
    activate_hypertension_bundle,
    api_client,
    bootstrap_unit,
    checklist_items_by_code,
    complete_item,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    lift_unit_off_not_ready,
    reload_activation,
    reload_encounter,
    set_clock,
)


@pytest.fixture
def charge_nurse_pushed_to_the_focus_penalty():
    """A BASIC charge nurse covering a patient who turns TIER_IV mid-shift, then
    promoted to ADVANCED."""
    world = bootstrap_unit(
        clock="2026-08-01T08:00:00Z",
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs={
            "charge": {
                "staff_role": "RN_LABOR_DELIVERY",
                "fetal_monitoring_cert_level": "BASIC",
                "credential_expires_at": "2027-06-30T00:00:00Z",
            }
        },
    )
    lift_unit_off_not_ready(world, "2026-08-01T08:00:00Z")
    shift = create_active_shift(
        world,
        staff_key="charge",
        role_slot="CHARGE",
        shift_start_utc="2026-08-01T07:00:00Z",
        shift_end_utc="2026-08-01T17:00:00Z",
    )
    encounter = create_encounter(
        world,
        parity=2,
        gestational_age_weeks=42,
        prior_cesarean=True,
        fetus_count=1,
        presentation="VERTEX",
    )
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="RATIO_SHARED"
    )
    debit_before_flip = assignment["acuity_units_consumed"]
    activation = activate_hypertension_bundle(
        world, encounter, acting_key="charge", systolic_mmhg=168, diastolic_mmhg=114
    )
    magnesium = checklist_items_by_code(world, activation, acting_key="charge")[
        "MAGNESIUM_LOADED"
    ]
    set_clock("2026-08-01T08:20:00Z")
    magnesium = complete_item(
        world,
        activation,
        magnesium,
        "2026-08-01T08:20:00Z",
        performed_key="charge",
        acting_key="charge",
    )
    promoted = get_success_data(
        api_client.patch_staff_member(
            world.staff_id("charge"),
            {"fetal_monitoring_cert_level": "ADVANCED"},
            world.charge_headers,
        )
    )
    return {
        "world": world,
        "shift": get_success_data(api_client.get_shift(shift["id"], world.charge_headers)),
        "encounter": reload_encounter(world, encounter["id"]),
        "assignment": get_success_data(
            api_client.get_care_assignment(assignment["id"], world.charge_headers)
        ),
        "activation": reload_activation(world, activation["id"], acting_key="charge"),
        "magnesium": magnesium,
        "staff": promoted,
        "debit_before_flip": debit_before_flip,
    }


def test_the_certification_promotion_cannot_raise_a_charge_nurses_capacity(
    charge_nurse_pushed_to_the_focus_penalty,
):
    """The slot base caps the raw figure, so lifting the certification ceiling
    from 3.0 to 4.0 changes nothing before the two subtractions.

    PRD 3.2: "Otherwise a raw figure is taken as the smaller of two ceilings: the
    base for the slot, which is 3.0 for `CHARGE`, 4.0 for `BEDSIDE`, 4.0 for
    `ONE_TO_ONE_FLOAT`, 2.0 for `OR_STANDBY` and 6.0 for `TRIAGE`; and the
    ceiling implied by certification, which is 4.0 for `ADVANCED`, 3.0 for
    `BASIC` and 0.0 for `EXPIRED`."

    Design: Difficulty/combinatorial_formula/charge_slot_nested_min_max_with_tier_iv_focus_penalty_yields_1_0
    """
    staff = charge_nurse_pushed_to_the_focus_penalty["staff"]
    assert staff["fetal_monitoring_cert_level"] == "ADVANCED"
    assert staff["capacity_units"] == pytest.approx(1.0, abs=0.01)


def test_both_the_admin_offset_and_the_focus_penalty_bite_at_once(
    charge_nurse_pushed_to_the_focus_penalty,
):
    """A charge nurse covering a TIER_IV patient loses 1.0 for the slot and a
    further 1.0 for the focus penalty, landing on 1.0 rather than 3.0.

    PRD 3.2: "From that raw figure an administrative offset of 1.0 is subtracted
    when the slot is `CHARGE`, and a focus penalty of 1.0 is subtracted when the
    member currently holds an `ACTIVE` care assignment on this shift covering an
    encounter whose `acuity_tier` is `TIER_IV`."

    Design: Difficulty/combinatorial_formula/charge_slot_nested_min_max_with_tier_iv_focus_penalty_yields_1_0
    """
    result = charge_nurse_pushed_to_the_focus_penalty
    assert result["encounter"]["acuity_tier"] == "TIER_IV"
    assert result["staff"]["capacity_units"] == pytest.approx(1.0, abs=0.01)


def test_the_frozen_shift_capacity_is_never_retro_recomputed(
    charge_nurse_pushed_to_the_focus_penalty,
):
    """The capacity snapshotted at activation stays 2.0 even after the member's
    own capacity moves to 1.0.

    PRD 2.10: "A shift's `capacity_units_effective` is snapshotted at activation
    from the staff member's capacity at that moment; later edits to that staff
    member's competency or employment status change the staff member's own
    `capacity_units` but never retro-change an already-snapshotted shift."

    Design: Difficulty/combinatorial_formula/charge_slot_nested_min_max_with_tier_iv_focus_penalty_yields_1_0
    """
    shift = charge_nurse_pushed_to_the_focus_penalty["shift"]
    assert shift["capacity_units_effective"] == pytest.approx(2.0, abs=0.01)


def test_the_tier_flip_reprices_the_shared_row_onto_the_capacity_boundary(
    charge_nurse_pushed_to_the_focus_penalty,
):
    """The shared row is re-priced from 0.8 to 2.0 and the shift's load lands
    exactly on its frozen capacity, which the inclusive capacity test admits.

    PRD 3.3: "A `RATIO_SHARED` row debits the product of two factors: the acuity
    weight, which is 1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and
    4.0 for `TIER_IV`; and the phase multiplier, which is 0.5 for `ANTEPARTUM`,
    1.0 for `LATENT`, 1.5 for `ACTIVE_FIRST_STAGE`, 2.0 for `SECOND_STAGE`, 1.5
    for `THIRD_STAGE_DELIVERED`, 0.5 for `POSTPARTUM_RECOVERY`, 0.0 for
    `DISCHARGED` and 0.0 for `TRANSFERRED_OUT`."

    Design: Difficulty/combinatorial_formula/charge_slot_nested_min_max_with_tier_iv_focus_penalty_yields_1_0
    """
    result = charge_nurse_pushed_to_the_focus_penalty
    assert result["debit_before_flip"] == pytest.approx(0.8, abs=0.01)
    assignment = result["assignment"]
    assert assignment["acuity_units_consumed"] == pytest.approx(2.0, abs=0.01)
    assert assignment["status"] == "ACTIVE"
    assert assignment["coverage_mode"] == "RATIO_SHARED"
    assert result["shift"]["assigned_acuity_load_units"] == pytest.approx(2.0, abs=0.01)


def test_the_magnesium_step_forces_one_to_one_coverage_on_the_encounter(
    charge_nurse_pushed_to_the_focus_penalty,
):
    """Loading magnesium sets the infusion flag, which forces one-to-one coverage
    and a required figure of 4.0 against the 2.0 actually assigned.

    PRD 3.6: "completing `MAGNESIUM_LOADED` on a hypertension bundle additionally
    sets `magnesium_infusion_active` to true, which forces one-to-one coverage and
    the whole cascade that follows from it."

    Design: Difficulty/combinatorial_formula/charge_slot_nested_min_max_with_tier_iv_focus_penalty_yields_1_0
    """
    result = charge_nurse_pushed_to_the_focus_penalty
    encounter = result["encounter"]
    assert encounter["magnesium_infusion_active"] is True
    assert encounter["one_to_one_required"] is True
    assert encounter["required_coverage_units"] == pytest.approx(4.0, abs=0.01)
    assert encounter["assigned_coverage_units"] == pytest.approx(2.0, abs=0.01)
    assert result["magnesium"]["status"] == "COMPLETED"
    assert result["activation"]["status"] == "STAGE_1_IN_PROGRESS"
    assert result["activation"]["highest_stage_reached"] == 1


def test_the_residual_deficit_strains_the_unit_without_freezing_it(
    charge_nurse_pushed_to_the_focus_penalty,
):
    """A deficit of 2.0 is above zero and below the freeze threshold, so the
    third posture branch is the one that fires.

    PRD 3.3: "The thresholds are exact: a deficit of 4.0 freezes inductions and a
    deficit of 3.9 does not; a deficit of 0.1 strains the unit and a deficit of
    exactly 0.0 does not."

    Design: Difficulty/combinatorial_formula/charge_slot_nested_min_max_with_tier_iv_focus_penalty_yields_1_0
    """
    world = charge_nurse_pushed_to_the_focus_penalty["world"]
    unit = world.reload_unit()
    assert unit["coverage_deficit_units"] == pytest.approx(2.0, abs=0.01)
    assert unit["staffing_posture"] == "RATIO_STRAINED"
