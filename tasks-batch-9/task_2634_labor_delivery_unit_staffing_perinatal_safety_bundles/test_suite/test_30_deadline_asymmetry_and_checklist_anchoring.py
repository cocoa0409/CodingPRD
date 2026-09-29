"""Two mintings whose arithmetic is deliberately not uniform.

The escalation clock is armed from a table with no `CATEGORY_I` row, so two
readings recorded at the same instant on sibling encounters produce a
five-minute deadline and no deadline at all. The hemorrhage checklist is minted
server-side with cumulative deadlines, so the fourth item's allowance of 10
minutes lands 55 minutes after activation rather than 10.
"""

import pytest

from test_helpers import (
    api_client,
    activate_hemorrhage_bundle,
    assert_bundle_activation,
    assert_checklist_item,
    assert_fetal_assessment,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    bootstrap_unit,
    checklist_items,
    create_active_shift,
    create_assessment,
    create_encounter,
    get_success_data,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
CATEGORY_III_DUE_AT = "2026-08-01T06:05:00Z"
STEP_DUE_AT = (
    "2026-08-01T06:10:00Z",
    "2026-08-01T06:25:00Z",
    "2026-08-01T06:45:00Z",
    "2026-08-01T06:55:00Z",
)
STEP_CODES = (
    "QBL_MEASURE",
    "UTEROTONIC_GIVEN",
    "TYPE_AND_SCREEN",
    "MTP_ACTIVATED",
)
STEP_ALLOWANCES = (10, 15, 20, 10)
STEP_GATES = (1, 1, 2, 3)

ASYMMETRY_STAFF = {
    "charge": {
        "full_name": "Marisol Quintero RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}

BUNDLE_STAFF = {
    "charge": {
        "full_name": "Solveig Brandt RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Ignatius Oyelaran MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": True,
    },
}


@pytest.fixture
def two_readings_recorded_at_the_same_instant():
    """A CATEGORY_III and a CATEGORY_I assessment, both assessed at 06:00."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=5,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=ASYMMETRY_STAFF,
        unit_overrides={"unit_name": "Hallowvale Perinatal Center LDR"},
    )
    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter_three = create_encounter(
        world, patient_record_code="PRC-CAT3-2525", parity=1, gestational_age_weeks=40
    )
    encounter_one = create_encounter(
        world, patient_record_code="PRC-CAT1-2626", parity=1, gestational_age_weeks=40
    )
    category_three = create_assessment(
        world,
        encounter_three,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_III",
        baseline_rate_bpm=90,
        variability="ABSENT",
        recurrent_decelerations=True,
    )
    category_one = create_assessment(
        world,
        encounter_one,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_I",
        baseline_rate_bpm=138,
        variability="MODERATE",
        recurrent_decelerations=False,
    )
    return {
        "world": world,
        "encounter_three": encounter_three,
        "encounter_one": encounter_one,
        "category_three": category_three,
        "category_one": category_one,
    }


@pytest.fixture
def a_hemorrhage_checklist_minted_at_six():
    """An OBSTETRIC_HEMORRHAGE activation and the four items it mints."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=BUNDLE_STAFF,
        unit_overrides={"unit_name": "Emberlyn Regional Maternity LDR"},
    )
    encounter = create_encounter(
        world, patient_record_code="PRC-QBL-2727", parity=2, gestational_age_weeks=40
    )
    activation = activate_hemorrhage_bundle(
        world,
        encounter,
        activation_trigger="QBL_THRESHOLD",
        quantitative_blood_loss_ml=1000,
    )
    items = checklist_items(world, activation)
    return {
        "world": world,
        "encounter": encounter,
        "activation": activation,
        "items": items,
    }


def test_the_category_three_reading_arms_a_five_minute_clock(
    two_readings_recorded_at_the_same_instant,
):
    """"When the `category` is not `CATEGORY_I`, `escalation_due_at` is set to
    `assessed_at` plus 20 minutes for a `CATEGORY_II` reading and plus 5 minutes
    for a `CATEGORY_III` reading."

    Design: Corner/calculations/category_iii_derives_a_five_minute_deadline_while_category_i_derives_none_at_all
    """
    reading = two_readings_recorded_at_the_same_instant["category_three"]
    assert_fetal_assessment(reading)
    assert reading["category"] == "CATEGORY_III"
    assert_instant_equals(reading["assessed_at"], CLOCK_START, "assessed_at")
    assert reading["escalation_status"] == "ESCALATION_DUE"
    assert_instant_equals(
        reading["escalation_due_at"], CATEGORY_III_DUE_AT, "escalation_due_at"
    )
    assert reading["escalation_tier_high_water"] == 0
    assert_instant_is_null(reading["next_tier_due_at"], "next_tier_due_at")


def test_the_category_one_reading_arms_nothing_at_all(
    two_readings_recorded_at_the_same_instant,
):
    """"The new row's `escalation_status` starts at `NOT_REQUIRED` when the
    `category` is `CATEGORY_I` and at `ESCALATION_DUE` otherwise, and
    `supersedes_assessment_id` is set to the immediately prior assessment on the
    same encounter, chosen as the one with the greatest `assessed_at` and, where
    two share that instant, the later `created_at`."

    Design: Corner/calculations/category_iii_derives_a_five_minute_deadline_while_category_i_derives_none_at_all
    """
    setup = two_readings_recorded_at_the_same_instant
    reading = setup["category_one"]
    assert_fetal_assessment(reading)
    assert reading["category"] == "CATEGORY_I"
    assert_instant_equals(reading["assessed_at"], CLOCK_START, "assessed_at")
    assert reading["escalation_status"] == "NOT_REQUIRED"
    assert_instant_is_null(reading["escalation_due_at"], "escalation_due_at")
    stored = get_success_data(
        api_client.get_assessment(reading["id"], setup["world"].charge_headers)
    )
    assert_instant_is_null(stored["escalation_due_at"], "escalation_due_at")


def test_the_two_chains_pull_the_encounters_to_opposite_tiers(
    two_readings_recorded_at_the_same_instant,
):
    """"An unresolved `CATEGORY_II` chain lifts the encounter's acuity floor to
    `TIER_III` and a `CATEGORY_III` chain to `TIER_IV`, with the coverage and
    posture consequences of section 3.3."

    Design: Corner/calculations/category_iii_derives_a_five_minute_deadline_while_category_i_derives_none_at_all
    """
    setup = two_readings_recorded_at_the_same_instant
    world = setup["world"]
    escalating = reload_encounter(world, setup["encounter_three"]["id"])
    assert_labor_encounter(escalating)
    assert escalating["acuity_tier"] == "TIER_IV"
    assert escalating["one_to_one_required"] is True
    assert escalating["required_coverage_units"] == pytest.approx(4.0, abs=1e-9)
    quiet = reload_encounter(world, setup["encounter_one"]["id"])
    assert_labor_encounter(quiet)
    assert quiet["acuity_tier"] == "TIER_I"
    assert quiet["required_coverage_units"] == pytest.approx(0.5, abs=1e-9)
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(4.5, abs=1e-9)


def test_the_four_items_are_minted_from_the_hemorrhage_template(
    a_hemorrhage_checklist_minted_at_six,
):
    """"An `OBSTETRIC_HEMORRHAGE` bundle receives four items: `step_sequence` 1,
    `step_code` `QBL_MEASURE`, `stage_gate` 1, `required_within_minutes` 10;
    sequence 2, `UTEROTONIC_GIVEN`, gate 1, 15 minutes; sequence 3,
    `TYPE_AND_SCREEN`, gate 2, 20 minutes; sequence 4, `MTP_ACTIVATED`, gate 3, 10
    minutes."

    Design: Corner/calculations/hemorrhage_activation_mints_four_items_whose_authoritative_due_dates_accumulate_to_fifty_five_minutes
    """
    items = a_hemorrhage_checklist_minted_at_six["items"]
    assert len(items) == 4
    assert [item["step_sequence"] for item in items] == [1, 2, 3, 4]
    assert tuple(item["step_code"] for item in items) == STEP_CODES
    assert tuple(item["required_within_minutes"] for item in items) == STEP_ALLOWANCES
    assert tuple(item["stage_gate"] for item in items) == STEP_GATES
    for item in items:
        assert_checklist_item(item)


def test_the_authoritative_deadlines_accumulate_across_the_steps(
    a_hemorrhage_checklist_minted_at_six,
):
    """"`due_at_activation_anchored`, the authoritative date, is `activated_at`
    plus the sum of `required_within_minutes` across every item whose
    `step_sequence` is less than or equal to this item's. For a hemorrhage bundle
    that yields offsets of 10, 25, 45 and 55 minutes from activation."

    Design: Corner/calculations/hemorrhage_activation_mints_four_items_whose_authoritative_due_dates_accumulate_to_fifty_five_minutes
    """
    setup = a_hemorrhage_checklist_minted_at_six
    assert_instant_equals(
        setup["activation"]["activated_at"], CLOCK_START, "activated_at"
    )
    for item, expected in zip(setup["items"], STEP_DUE_AT):
        assert_instant_equals(
            item["due_at_activation_anchored"],
            expected,
            f"due_at_activation_anchored for {item['step_code']}",
        )
    last = setup["items"][3]
    assert last["required_within_minutes"] == setup["items"][0][
        "required_within_minutes"
    ]
    assert last["due_at_activation_anchored"] != setup["items"][0][
        "due_at_activation_anchored"
    ]


def test_only_the_first_advisory_date_can_be_computed_at_activation(
    a_hemorrhage_checklist_minted_at_six,
):
    """"`due_at_sequence_anchored`, the advisory date, is instead the predecessor
    item's `completed_at` plus this item's own `required_within_minutes`; for the
    first item it is `activated_at` plus that item's own allowance, and for any item
    whose predecessor has not been completed it is null."

    Design: Corner/calculations/hemorrhage_activation_mints_four_items_whose_authoritative_due_dates_accumulate_to_fifty_five_minutes
    """
    items = a_hemorrhage_checklist_minted_at_six["items"]
    assert_instant_equals(
        items[0]["due_at_sequence_anchored"],
        STEP_DUE_AT[0],
        "due_at_sequence_anchored",
    )
    for item in items[1:]:
        assert_instant_is_null(
            item["due_at_sequence_anchored"],
            f"due_at_sequence_anchored for {item['step_code']}",
        )


def test_every_minted_item_opens_pending_with_the_activation_uncounted(
    a_hemorrhage_checklist_minted_at_six,
):
    """"Every item opens `PENDING` with `completed_at`, `performed_by_staff_id` and
    `minutes_from_activation` null."

    Design: Corner/calculations/hemorrhage_activation_mints_four_items_whose_authoritative_due_dates_accumulate_to_fifty_five_minutes
    """
    setup = a_hemorrhage_checklist_minted_at_six
    for item in setup["items"]:
        assert item["status"] == "PENDING"
        assert item["completed_at"] is None
        assert item["performed_by_staff_id"] is None
        assert item["minutes_from_activation"] is None
    activation = setup["activation"]
    assert_bundle_activation(activation)
    assert activation["status"] == "ACTIVATED"
    assert activation["highest_stage_reached"] == 0
    assert activation["on_time_step_count"] == 0
    assert activation["late_step_count"] == 0
    assert activation["missed_step_count"] == 0
    assert activation["timeliness_score"] is None
