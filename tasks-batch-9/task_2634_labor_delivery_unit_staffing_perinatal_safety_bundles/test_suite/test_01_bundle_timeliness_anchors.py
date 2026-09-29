"""Bundle timeliness under its two anchoring conventions."""

import pytest

from test_helpers import (
    activate_hypertension_bundle,
    api_client,
    assert_instant_equals,
    bootstrap_unit,
    checklist_items,
    complete_item,
    create_active_shift,
    create_encounter,
    get_success_data,
    reload_activation,
    set_clock,
)

ACTIVATED_AT = "2026-08-01T06:00:00Z"


@pytest.fixture
def hypertension_bundle_walked_to_resolution():
    """A four-step hypertension bundle whose second step lands inside its
    cumulative allowance but outside its chained allowance."""
    world = bootstrap_unit(
        clock=ACTIVATED_AT,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs={
            "charge": {
                "staff_role": "RN_LABOR_DELIVERY",
                "fetal_monitoring_cert_level": "ADVANCED",
                "credential_expires_at": "2027-06-30T00:00:00Z",
            }
        },
    )
    create_active_shift(
        world,
        staff_key="charge",
        role_slot="CHARGE",
        shift_start_utc="2026-08-01T05:00:00Z",
        shift_end_utc="2026-08-01T15:00:00Z",
    )
    encounter = create_encounter(
        world, parity=1, gestational_age_weeks=38, presentation="VERTEX"
    )
    activation = activate_hypertension_bundle(
        world, encounter, acting_key="charge", systolic_mmhg=166, diastolic_mmhg=112
    )
    items = checklist_items(world, activation, acting_key="charge")

    set_clock("2026-08-01T06:25:00Z")
    complete_item(
        world,
        activation,
        items[0],
        "2026-08-01T06:25:00Z",
        performed_key="charge",
        acting_key="charge",
    )
    set_clock("2026-08-01T07:28:00Z")
    complete_item(
        world,
        activation,
        items[1],
        "2026-08-01T07:28:00Z",
        performed_key="charge",
        acting_key="charge",
    )
    set_clock("2026-08-01T07:30:00Z")
    get_success_data(
        api_client.escalate_stage(
            activation["id"],
            {"target_stage": 2, "systolic_mmhg": 168, "diastolic_mmhg": 114},
            world.ob_headers_for("charge"),
        )
    )
    set_clock("2026-08-01T07:40:00Z")
    complete_item(
        world,
        activation,
        items[2],
        "2026-08-01T07:40:00Z",
        performed_key="charge",
        acting_key="charge",
    )
    set_clock("2026-08-01T07:58:00Z")
    complete_item(
        world,
        activation,
        items[3],
        "2026-08-01T07:58:00Z",
        performed_key="charge",
        acting_key="charge",
    )
    set_clock("2026-08-01T08:00:00Z")
    resolved = get_success_data(
        api_client.resolve_activation(activation["id"], {}, world.ob_headers_for("charge"))
    )
    return {
        "world": world,
        "encounter": encounter,
        "activation": resolved,
        "items": checklist_items(world, activation, acting_key="charge"),
    }


def test_the_two_timeliness_variants_disagree_on_the_same_four_rows(
    hypertension_bundle_walked_to_resolution,
):
    """The authoritative score reads the cumulative deadline and the advisory
    score reads the chained deadline, so identical completions score differently.

    PRD 3.6: "The same data yields different numbers: with an activation at
    instant T, item 1 completed at T plus 2 minutes and item 2 completed at T
    plus 20 minutes, the activation-anchored dates are T plus 10 and T plus 25
    minutes, so both are on time and the authoritative score over 4 applicable
    items is 100.00, while the sequence-anchored dates are T plus 10 and T plus
    17 minutes, making item 2 late for an advisory score of 87.50."

    Design: Difficulty/dual_variant_calc/hypertension_bundle_activation_anchored_100_vs_sequence_anchored_87_50
    """
    activation = hypertension_bundle_walked_to_resolution["activation"]
    assert activation["timeliness_score"] == pytest.approx(100.00, abs=0.01)
    assert activation["sequence_adjusted_score"] == pytest.approx(87.50, abs=0.01)


def test_the_authoritative_counters_follow_the_activation_anchor(
    hypertension_bundle_walked_to_resolution,
):
    """The step counters carried on the activation follow the authoritative run,
    so the step that only the chained anchor calls late is still counted on time.

    PRD 3.6: "the counters `on_time_step_count` and `late_step_count` on the
    activation always follow this authoritative run, and it is the only figure
    any gate or report consumes."

    Design: Difficulty/dual_variant_calc/hypertension_bundle_activation_anchored_100_vs_sequence_anchored_87_50
    """
    activation = hypertension_bundle_walked_to_resolution["activation"]
    assert activation["on_time_step_count"] == 4
    assert activation["late_step_count"] == 0
    assert activation["missed_step_count"] == 0
    assert activation["highest_stage_reached"] == 2
    assert activation["status"] == "DEBRIEF_PENDING"


def test_the_magnesium_step_lands_completed_because_only_the_authoritative_date_governs(
    hypertension_bundle_walked_to_resolution,
):
    """A step completed after its chained deadline but inside its cumulative
    deadline is COMPLETED, and both due dates are published side by side.

    PRD 3.6: "The landing state is decided by the authoritative date alone:
    `completed_at` at or before `due_at_activation_anchored` yields `COMPLETED`
    and increments `on_time_step_count`, and the boundary instant counts as on
    time; `completed_at` strictly after it yields `LATE_COMPLETED` and increments
    `late_step_count`."

    Design: Difficulty/dual_variant_calc/hypertension_bundle_activation_anchored_100_vs_sequence_anchored_87_50
    """
    items = hypertension_bundle_walked_to_resolution["items"]
    magnesium = items[1]
    assert magnesium["step_code"] == "MAGNESIUM_LOADED"
    assert magnesium["status"] == "COMPLETED"
    assert_instant_equals(
        magnesium["due_at_activation_anchored"],
        "2026-08-01T07:30:00Z",
        "due_at_activation_anchored",
    )
    assert_instant_equals(
        magnesium["due_at_sequence_anchored"],
        "2026-08-01T07:25:00Z",
        "due_at_sequence_anchored",
    )
    assert magnesium["minutes_from_activation"] == 88


def test_the_last_step_carries_the_cumulative_and_the_chained_deadline(
    hypertension_bundle_walked_to_resolution,
):
    """The fourth item's authoritative date is the sum of every allowance up to
    it, while its advisory date chains off its predecessor's completion.

    PRD 3.6: "`due_at_sequence_anchored`, the advisory date, is instead the
    predecessor item's `completed_at` plus this item's own
    `required_within_minutes`; for the first item it is `activated_at` plus that
    item's own allowance, and for any item whose predecessor has not been
    completed it is null."

    Design: Difficulty/dual_variant_calc/hypertension_bundle_activation_anchored_100_vs_sequence_anchored_87_50
    """
    items = hypertension_bundle_walked_to_resolution["items"]
    last = items[3]
    assert last["step_code"] == "OB_AT_BEDSIDE"
    assert_instant_equals(
        last["due_at_activation_anchored"],
        "2026-08-01T08:05:00Z",
        "due_at_activation_anchored",
    )
    assert_instant_equals(
        last["due_at_sequence_anchored"],
        "2026-08-01T08:00:00Z",
        "due_at_sequence_anchored",
    )


def test_a_bundle_with_no_missed_step_leaves_the_unit_breach_counter_alone(
    hypertension_bundle_walked_to_resolution,
):
    """Reaching stage 2 sends the activation to DEBRIEF_PENDING, but only a
    missed step raises the unit's bundle breach counter.

    PRD 3.6: "Only the first of those three conditions, a `missed_step_count` of
    1 or more, also increments the unit's `bundle_breach_count`, and it
    increments it by exactly 1 on that edge."

    Design: Difficulty/dual_variant_calc/hypertension_bundle_activation_anchored_100_vs_sequence_anchored_87_50
    """
    world = hypertension_bundle_walked_to_resolution["world"]
    unit = world.reload_unit()
    assert unit["bundle_breach_count"] == 0


def test_the_resolved_activation_is_readable_with_both_scores(
    hypertension_bundle_walked_to_resolution,
):
    """Both scores stay null until CONTROLLED is reached and are then published
    together on the activation read.

    PRD 3.6: "Both scores stay null until the activation reaches `CONTROLLED`,
    and a timeliness report read exposes the two variants side by side with the
    per-item on-time and late classification under each anchoring."

    Design: Difficulty/dual_variant_calc/hypertension_bundle_activation_anchored_100_vs_sequence_anchored_87_50
    """
    world = hypertension_bundle_walked_to_resolution["world"]
    activation = hypertension_bundle_walked_to_resolution["activation"]
    fetched = reload_activation(world, activation["id"], acting_key="charge")
    assert fetched["timeliness_score"] == pytest.approx(100.00, abs=0.01)
    assert fetched["sequence_adjusted_score"] == pytest.approx(87.50, abs=0.01)
