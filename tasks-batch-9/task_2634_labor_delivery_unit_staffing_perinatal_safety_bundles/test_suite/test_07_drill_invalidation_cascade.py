"""One invalidation call propagates through four entity families in order.

Currency lapses on both participants, the unit loses its only current drill and
falls to NOT_READY, that state bumps the elective hold and only the elective
hold, and the bumped booking's bed and its own frozen minutes come back.
"""

import pytest

from test_helpers import (
    api_client,
    assert_bed,
    assert_drill,
    assert_induction_booking,
    assert_instant_is_null,
    assert_obstetric_unit,
    assert_staff_member,
    bootstrap_unit,
    confirm_booking,
    create_booking,
    get_success_data,
    hold_booking,
    reload_booking,
    setup_validated_drill,
)

INDUCTION_DAY = "2026-08-06"
INVALIDATION_REASON = (
    "Timekeeper recording device was later found to be desynchronised from the unit clock."
)

CASCADE_STAFF = {
    "ob": {
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "or_circulating_qualified": True,
    },
    "anesthesia": {"staff_role": "ANESTHESIOLOGIST", "fetal_monitoring_cert_level": "BASIC"},
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "officer": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "BASIC"},
}


@pytest.fixture
def invalidated_drill_cascade():
    """Invalidate the unit's only validated drill while two bookings are live.

    Three LDR beds keep one bed AVAILABLE while two are reserved, so the
    posture never reaches DIVERT and every hold freezes against the 45-minute
    OPEN buffer. The elective booking is held on LDR-01 at 480 + 45 = 525; the
    medically indicated booking is confirmed on LDR-02 at 600 + 45 = 645.
    """
    world = bootstrap_unit(
        clock="2026-08-05T09:00:00Z",
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("LDR-03", "LDR")],
        staff_specs=CASCADE_STAFF,
    )
    drill = setup_validated_drill(
        world,
        scheduled_for_utc="2026-08-05T09:00:00Z",
        decision_at="2026-08-05T09:00:00Z",
        incision_at="2026-08-05T09:18:00Z",
        document_clock="2026-08-05T09:30:00Z",
    )

    elective = create_booking(
        world,
        gestational_age_weeks=39,
        indication_code="GDM_CONTROLLED",
        requested_start_utc="2026-08-06T08:00:00Z",
        expected_labor_minutes=480,
    )
    medical = create_booking(
        world,
        gestational_age_weeks=38,
        indication_code="PREECLAMPSIA",
        requested_start_utc="2026-08-06T14:00:00Z",
        expected_labor_minutes=600,
    )
    elective_held = hold_booking(world, elective, bed_label="LDR-01")
    medical_held = hold_booking(world, medical, bed_label="LDR-02")
    confirm_booking(world, medical)
    unit_before = world.reload_unit()

    invalidated = get_success_data(
        api_client.invalidate_drill(
            drill["id"],
            {"invalidation_reason": INVALIDATION_REASON},
            world.officer_headers,
        )
    )

    return {
        "world": world,
        "drill_id": drill["id"],
        "drill_before": drill,
        "invalidated": invalidated,
        "elective": elective,
        "elective_held": elective_held,
        "medical": medical,
        "medical_held": medical_held,
        "unit_before": unit_before,
        "unit_after": world.reload_unit(),
    }


def test_invalidation_moves_the_drill_and_strips_its_expiry(invalidated_drill_cascade):
    """"It names an `invalidation_reason` of 10 to 500 characters and moves the
    drill from `VALIDATED` to `INVALIDATED`, nulling `expires_at`."

    Design: Difficulty/transitive_cascade/drill_invalidation_cascades_currency_to_readiness_to_elective_bump_to_bed_release
    """
    setup = invalidated_drill_cascade
    assert setup["drill_before"]["status"] == "VALIDATED"
    assert setup["drill_before"]["expires_at"] is not None

    drill = get_success_data(
        api_client.get_drill(setup["drill_id"], setup["world"].officer_headers)
    )
    assert_drill(drill)
    assert drill["status"] == "INVALIDATED"
    assert_instant_is_null(drill["expires_at"], "expires_at")


def test_both_participants_lose_currency_because_no_validated_drill_remains(
    invalidated_drill_cascade,
):
    """"First hop: each participant re-derives `last_validated_drill_at` from
    the drills that remain `VALIDATED` for them, ordered by `decision_at`
    descending with `created_at` descending as the tie-break, and any
    participant left with no other validated drill moves from `CURRENT` to
    `LAPSED`."

    Design: Difficulty/transitive_cascade/drill_invalidation_cascades_currency_to_readiness_to_elective_bump_to_bed_release
    """
    world = invalidated_drill_cascade["world"]
    for key in ("ob", "anesthesia"):
        member = get_success_data(
            api_client.get_staff_member(world.staff_id(key), world.officer_headers)
        )
        assert_staff_member(member)
        assert member["drill_currency_state"] == "LAPSED"
        assert_instant_is_null(member["last_validated_drill_at"], "last_validated_drill_at")


def test_the_unit_loses_its_only_current_drill_and_falls_to_not_ready(
    invalidated_drill_cascade,
):
    """"Second hop: if this was the unit's only current drill,
    `cesarean_readiness_state` becomes `NOT_READY` with `readiness_reason`
    `NO_CURRENT_DRILL`." The state before the call was DEGRADED, so the drop is
    caused by the emptied drill set rather than by anything in the payload.

    Design: Difficulty/transitive_cascade/drill_invalidation_cascades_currency_to_readiness_to_elective_bump_to_bed_release
    """
    setup = invalidated_drill_cascade
    assert setup["unit_before"]["cesarean_readiness_state"] == "DEGRADED"

    unit = setup["unit_after"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["readiness_reason"] == "NO_CURRENT_DRILL"
    assert unit["current_drill_id"] is None


def test_only_the_elective_class_booking_is_bumped(invalidated_drill_cascade):
    """"Third hop: a `NOT_READY` unit bumps every booking in `CAPACITY_HELD` or
    `CONFIRMED` whose `priority_class` is `ELECTIVE_39_WEEK` or
    `PATIENT_REQUEST`, moving each to `BUMPED` and incrementing its
    `bump_count`." The medically indicated booking on the next bed is outside
    that filter and must not move.

    Design: Difficulty/transitive_cascade/drill_invalidation_cascades_currency_to_readiness_to_elective_bump_to_bed_release
    """
    setup = invalidated_drill_cascade
    world = setup["world"]
    assert setup["elective"]["priority_class"] == "ELECTIVE_39_WEEK"
    assert setup["medical"]["priority_class"] == "MEDICALLY_INDICATED"

    elective = reload_booking(world, setup["elective"]["id"])
    assert_induction_booking(elective)
    assert elective["status"] == "BUMPED"
    assert elective["bump_count"] == 1
    assert elective["bed_id"] is None
    assert_instant_is_null(elective["hold_expires_at"], "hold_expires_at")

    medical = reload_booking(world, setup["medical"]["id"])
    assert medical["status"] == "CONFIRMED"
    assert medical["bump_count"] == 0


def test_the_credit_back_is_the_frozen_projection_not_a_recomputed_one(
    invalidated_drill_cascade,
):
    """"Fourth hop: each bumped booking releases its bed from `HELD` to
    `AVAILABLE` and returns to the day's budget exactly the frozen
    `projected_occupancy_minutes` it had reserved, never a recomputed figure,
    after which the day's capacity projection is re-run." The buffer in force at
    the freeze was 45, and the new 75 never retro-applies.

    Design: Difficulty/transitive_cascade/drill_invalidation_cascades_currency_to_readiness_to_elective_bump_to_bed_release
    """
    setup = invalidated_drill_cascade
    world = setup["world"]
    assert setup["elective_held"]["projected_occupancy_minutes"] == 525
    assert setup["medical_held"]["projected_occupancy_minutes"] == 645
    assert setup["unit_before"]["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 525
    assert setup["unit_before"]["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 645

    unit = setup["unit_after"]
    assert unit["held_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 0
    assert unit["committed_bed_minutes_by_day"].get(INDUCTION_DAY, 0) == 645
    assert reload_booking(world, setup["elective"]["id"])[
        "projected_occupancy_minutes"
    ] == 525


def test_the_freed_bed_returns_while_the_untouched_hold_keeps_its_bed(
    invalidated_drill_cascade,
):
    """The bumped booking's bed goes back to AVAILABLE while the untouched
    booking's bed stays `HELD`, and readiness rewrites the posture: a unit is
    `INDUCTION_FROZEN` when "`cesarean_readiness_state` is `NOT_READY`", after
    which "`turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and
    75 otherwise."

    Design: Difficulty/transitive_cascade/drill_invalidation_cascades_currency_to_readiness_to_elective_bump_to_bed_release
    """
    setup = invalidated_drill_cascade
    world = setup["world"]
    freed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    assert_bed(freed)
    assert freed["status"] == "AVAILABLE"
    assert freed["held_booking_id"] is None

    retained = get_success_data(
        api_client.get_bed(world.bed_id("LDR-02"), world.charge_headers)
    )
    assert retained["status"] == "HELD"
    assert retained["held_booking_id"] == setup["medical"]["id"]

    unit = setup["unit_after"]
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert unit["turnover_buffer_minutes"] == 75
    assert setup["unit_before"]["staffing_posture"] == "OPEN"
    assert setup["unit_before"]["turnover_buffer_minutes"] == 45
