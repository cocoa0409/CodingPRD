"""Two derivations that only reveal themselves at the instant an input moves.

Advancing a phase doubles the phase multiplier, and the claim is that the
existing coverage row is re-priced in place rather than left stale or charged
twice. The tier-1 escalation window is measured in the same style: two sibling
assessments recorded at the same instant, escalated one minute apart, land on
opposite sides of an inclusive boundary.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_phase,
    assert_care_assignment,
    assert_fetal_assessment,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assign_bed,
    bootstrap_unit,
    create_active_shift,
    create_assessment,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_encounter,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
DEADLINE_INSTANT = "2026-08-01T06:20:00Z"
ONE_MINUTE_LATE = "2026-08-01T06:21:00Z"
NEXT_TIER_DUE_AT = "2026-08-01T06:35:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
CHARGE_CAPACITY = 2.0
ANTEPARTUM_DEBIT = 0.5
LATENT_DEBIT = 1.0

PRICING_STAFF = {
    "charge": {
        "full_name": "Delphine Okonkwo RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}

WINDOW_STAFF = {
    "charge": {
        "full_name": "Ingrid Vasquez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_tier_one_row_carried_from_antepartum_into_latent():
    """A RATIO_SHARED row priced at 0.5, then advanced into LATENT."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=6,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=PRICING_STAFF,
        unit_overrides={"unit_name": "Fernhollow Birth Center LDR"},
    )
    shift = create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-LATENT-2020",
        parity=1,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    before = reload_encounter(world, encounter["id"])
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="RATIO_SHARED"
    )
    advanced = advance_phase(world, encounter, "LATENT")
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "before": before,
        "assignment": assignment,
        "advanced": advanced,
    }


@pytest.fixture
def two_sibling_chains_escalated_a_minute_apart():
    """Two CATEGORY_II assessments assessed at 06:00, escalated at 06:20 and 06:21."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=5,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=WINDOW_STAFF,
        unit_overrides={"unit_name": "Willowmere Maternity LDR"},
    )
    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter_a = create_encounter(
        world, patient_record_code="PRC-ESCW-A-2121", parity=1, gestational_age_weeks=40
    )
    encounter_b = create_encounter(
        world, patient_record_code="PRC-ESCW-B-2222", parity=1, gestational_age_weeks=40
    )
    assessment_a = create_assessment(
        world,
        encounter_a,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_II",
        baseline_rate_bpm=145,
        variability="MINIMAL",
    )
    assessment_b = create_assessment(
        world,
        encounter_b,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_II",
        baseline_rate_bpm=148,
        variability="MINIMAL",
    )
    set_clock(DEADLINE_INSTANT)
    on_the_boundary = get_success_data(
        api_client.escalate_assessment(
            assessment_a["id"],
            {"target_tier": 1, "notified_staff_id": world.staff_id("charge")},
            world.charge_headers,
        )
    )
    set_clock(ONE_MINUTE_LATE)
    past_the_boundary = api_client.escalate_assessment(
        assessment_b["id"],
        {"target_tier": 1, "notified_staff_id": world.staff_id("charge")},
        world.charge_headers,
    )
    return {
        "world": world,
        "assessment_a": assessment_a,
        "assessment_b": assessment_b,
        "on_the_boundary": on_the_boundary,
        "past_the_boundary": past_the_boundary,
    }


def test_the_phase_multiplier_doubles_the_debit_in_place(
    a_tier_one_row_carried_from_antepartum_into_latent,
):
    """"A `RATIO_SHARED` row debits the product of two factors: the acuity weight,
    which is 1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and 4.0 for
    `TIER_IV`; and the phase multiplier, which is 0.5 for `ANTEPARTUM`, 1.0 for
    `LATENT`, 1.5 for `ACTIVE_FIRST_STAGE`, 2.0 for `SECOND_STAGE`, 1.5 for
    `THIRD_STAGE_DELIVERED`, 0.5 for `POSTPARTUM_RECOVERY`, 0.0 for `DISCHARGED`
    and 0.0 for `TRANSFERRED_OUT`."

    Design: Corner/calculations/latent_advance_reprices_the_ratio_shared_debit_in_place_from_0_5_to_1_0
    """
    setup = a_tier_one_row_carried_from_antepartum_into_latent
    world = setup["world"]
    assert setup["before"]["required_coverage_units"] == pytest.approx(
        ANTEPARTUM_DEBIT, abs=1e-9
    )
    assert setup["assignment"]["acuity_units_consumed"] == pytest.approx(
        ANTEPARTUM_DEBIT, abs=1e-9
    )
    row = get_success_data(
        api_client.get_care_assignment(setup["assignment"]["id"], world.charge_headers)
    )
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["acuity_units_consumed"] == pytest.approx(LATENT_DEBIT, abs=1e-9)
    encounter = setup["advanced"]
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "LATENT"
    assert encounter["acuity_tier"] == "TIER_I"
    assert encounter["required_coverage_units"] == pytest.approx(LATENT_DEBIT, abs=1e-9)
    assert encounter["assigned_coverage_units"] == pytest.approx(LATENT_DEBIT, abs=1e-9)
    assert encounter["staffing_state"] == "RATIO_COVERED"


def test_the_ledger_follows_the_reprice_without_stacking_a_second_charge(
    a_tier_one_row_carried_from_antepartum_into_latent,
):
    """"Whenever a tier or a phase changes, every affected row is re-priced in
    place, and the order of the two ledger movements is fixed: the old value is
    credited back first and the new value debited second, never the reverse."

    Design: Corner/calculations/latent_advance_reprices_the_ratio_shared_debit_in_place_from_0_5_to_1_0
    """
    setup = a_tier_one_row_carried_from_antepartum_into_latent
    world = setup["world"]
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["capacity_units_effective"] == pytest.approx(
        CHARGE_CAPACITY, abs=1e-9
    )
    assert shift["assigned_acuity_load_units"] == pytest.approx(LATENT_DEBIT, abs=1e-9)
    rows = api_client.list_care_assignments(
        world.charge_headers,
        params={"encounter_id": setup["encounter"]["id"], "limit": 100},
    ).json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == setup["assignment"]["id"]
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_boundary_instant_is_still_in_time(
    two_sibling_chains_escalated_a_minute_apart,
):
    """"A tier-1 call must arrive at or before `escalation_due_at`, the boundary
    instant still being in time, refused otherwise with
    `ERR_ESCALATION_WINDOW_EXPIRED`."

    Design: Corner/calculations/escalation_window_admits_the_exact_twenty_minute_instant_and_refuses_it_one_minute_later
    """
    setup = two_sibling_chains_escalated_a_minute_apart
    opened = setup["assessment_a"]
    assert_fetal_assessment(opened)
    assert opened["escalation_status"] == "ESCALATION_DUE"
    assert_instant_equals(
        opened["escalation_due_at"], DEADLINE_INSTANT, "escalation_due_at"
    )
    assert_instant_equals(
        setup["assessment_b"]["escalation_due_at"],
        DEADLINE_INSTANT,
        "escalation_due_at",
    )
    notified = setup["on_the_boundary"]
    assert_fetal_assessment(notified)
    assert notified["escalation_status"] == "TIER_1_NOTIFIED"
    assert notified["escalation_tier_high_water"] == 1


def test_the_next_deadline_runs_from_the_notification_not_the_reading(
    two_sibling_chains_escalated_a_minute_apart,
):
    """"For tiers 1 and 2 it sets `next_tier_due_at` to the instant of that notification
    plus 15 minutes for a `CATEGORY_II` assessment or 5 minutes for a `CATEGORY_III`
    assessment; at tier 3 `next_tier_due_at` becomes null, because there is no
    fourth tier."

    Design: Corner/calculations/escalation_window_admits_the_exact_twenty_minute_instant_and_refuses_it_one_minute_later
    """
    notified = two_sibling_chains_escalated_a_minute_apart["on_the_boundary"]
    assert notified["category"] == "CATEGORY_II"
    assert_instant_equals(
        notified["next_tier_due_at"], NEXT_TIER_DUE_AT, "next_tier_due_at"
    )
    assert_instant_equals(notified["assessed_at"], CLOCK_START, "assessed_at")


def test_one_minute_past_the_deadline_is_refused_at_call_time(
    two_sibling_chains_escalated_a_minute_apart,
):
    """"**14.2** windows and deadlines, yielding `ERR_ESCALATION_WINDOW_EXPIRED`,
    `ERR_DEBRIEF_WINDOW_VIOLATION`, `ERR_DEBRIEF_NOT_HELD`, `ERR_DRILL_NOT_DUE`,
    `ERR_INDUCTION_ADMIT_TOO_EARLY`, `ERR_BOOKING_START_IN_PAST` or
    `ERR_MEASURE_PERIOD_INVALID`, all at HTTP 422, on fetal escalation, review
    debrief scheduling, review findings submission, drill start, induction booking
    creation, induction admission and snapshot creation."

    Design: Corner/calculations/escalation_window_admits_the_exact_twenty_minute_instant_and_refuses_it_one_minute_later
    """
    setup = two_sibling_chains_escalated_a_minute_apart
    validate_error(
        setup["past_the_boundary"],
        ApiErrorId.ERR_ESCALATION_WINDOW_EXPIRED.value,
        422,
    )
    assert (
        setup["past_the_boundary"].json()["data"]["error_id"]
        != ApiErrorId.ERR_ESCALATION_TIER_SKIPPED.value
    )


def test_the_refused_chain_is_left_waiting_rather_than_breached(
    two_sibling_chains_escalated_a_minute_apart,
):
    """"`target_tier` must equal `escalation_tier_high_water` plus 1, and the
    current `escalation_status` must be the chain step that precedes that tier —
    `ESCALATION_DUE` for tier 1, `TIER_1_NOTIFIED` for tier 2, `TIER_2_NOTIFIED`
    for tier 3 — refused otherwise with `ERR_ESCALATION_TIER_SKIPPED`." No sweep
    has run, so the refused chain is still sitting at its first step.

    Design: Corner/calculations/escalation_window_admits_the_exact_twenty_minute_instant_and_refuses_it_one_minute_later
    """
    setup = two_sibling_chains_escalated_a_minute_apart
    world = setup["world"]
    stale = get_success_data(
        api_client.get_assessment(setup["assessment_b"]["id"], world.charge_headers)
    )
    assert_fetal_assessment(stale)
    assert stale["escalation_status"] == "ESCALATION_DUE"
    assert stale["escalation_tier_high_water"] == 0
    assert_instant_is_null(stale["next_tier_due_at"], "next_tier_due_at")
