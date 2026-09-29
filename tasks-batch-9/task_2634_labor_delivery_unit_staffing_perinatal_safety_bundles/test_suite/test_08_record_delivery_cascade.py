"""One record-delivery call reaches a DRAFT snapshot the caller never names.

The event self-advances past DELIVERED because the target was missed, the
encounter receives a server-chosen delivery mode, the snapshot inside whose
window the delivery instant falls is recomputed in place, and the operating-room
bed is released against the unit's current turnover buffer.
"""

import pytest

from test_helpers import (
    api_client,
    assert_bed,
    assert_cesarean_event,
    assert_instant_equals,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_snapshot,
    bootstrap_unit,
    create_active_shift,
    create_encounter,
    create_snapshot,
    declare_cesarean,
    get_success_data,
    mobilize_cesarean,
    reload_encounter,
    setup_validated_drill,
    set_clock,
)

SHIFT_START = "2026-09-02T08:00:00Z"
SHIFT_END = "2026-09-02T18:00:00Z"
PERIOD_START = "2026-09-01T00:00:00Z"
PERIOD_END = "2026-10-01T00:00:00Z"
DELIVERY_AT = "2026-09-02T08:55:00Z"

THEATRE_STAFF = {
    "ob": {
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "or_circulating_qualified": True,
    },
    "anesthesia": {"staff_role": "ANESTHESIOLOGIST", "fetal_monitoring_cert_level": "BASIC"},
    "tech": {
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": True,
    },
    "neonatal": {"staff_role": "NEONATAL_RESUSCITATOR", "fetal_monitoring_cert_level": "BASIC"},
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "officer": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "BASIC"},
}


@pytest.fixture
def missed_target_cesarean_delivered_into_a_draft_snapshot():
    """Record a delivery on a CATEGORY_2_URGENT event that missed its target.

    A validated drill measured at 14 minutes leaves readiness DEGRADED, which
    is what mobilisation of a CATEGORY_2_URGENT event demands. The three
    mobilised clinicians hold ACTIVE roster entries. The encounter is
    NTSV-eligible and is deliberately left with no bed and no care assignment,
    so nothing but the cascade can move. The September snapshot is taken before
    the delivery, so its stored pre-cascade figures are on record.
    """
    world = bootstrap_unit(
        clock="2026-09-02T08:00:00Z",
        ldr_beds=2,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("OR-01", "OR")],
        staff_specs=THEATRE_STAFF,
    )
    setup_validated_drill(
        world,
        scheduled_for_utc="2026-09-02T08:00:00Z",
        decision_at="2026-09-02T08:00:00Z",
        incision_at="2026-09-02T08:14:00Z",
        document_clock="2026-09-02T08:15:00Z",
    )
    for key in ("anesthesia", "tech", "neonatal"):
        create_active_shift(world, key, "BEDSIDE", SHIFT_START, SHIFT_END)

    encounter = create_encounter(
        world,
        parity=0,
        gestational_age_weeks=39,
        prior_cesarean=False,
        fetus_count=1,
        presentation="VERTEX",
    )
    snapshot_before = create_snapshot(world, PERIOD_START, PERIOD_END)

    event = declare_cesarean(world, encounter, urgency_class="CATEGORY_2_URGENT")
    mobilize_cesarean(
        world, event, or_bed_label="OR-01", staff_keys=["anesthesia", "tech", "neonatal"]
    )

    set_clock("2026-09-02T09:00:00Z")
    incised = get_success_data(
        api_client.record_incision(
            event["id"], {"incision_at": "2026-09-02T08:49:00Z"}, world.ob_headers
        )
    )
    delivered = get_success_data(
        api_client.record_delivery(
            event["id"], {"delivery_at": DELIVERY_AT}, world.ob_headers
        )
    )

    return {
        "world": world,
        "encounter_id": encounter["id"],
        "encounter_before": encounter,
        "event_id": event["id"],
        "incised": incised,
        "delivered": delivered,
        "snapshot_before": snapshot_before,
        "snapshot_after": get_success_data(
            api_client.get_snapshot(snapshot_before["id"], world.officer_headers)
        ),
    }


def test_a_missed_target_event_walks_on_to_review_pending_in_the_same_request(
    missed_target_cesarean_delivered_into_a_draft_snapshot,
):
    """"Then, at the end of that same request, the event moves on from
    `DELIVERED` without a second call: to `REVIEW_PENDING` when `met_target` is
    false or the `urgency_class` is `CATEGORY_1_CRASH`, also setting the
    encounter's `review_required` to true; and straight to `CLOSED` when
    `met_target` is true and the `urgency_class` is `CATEGORY_2_URGENT`." The
    branch is decided by a measurement taken one call earlier.

    Design: Difficulty/transitive_cascade/record_delivery_cascades_event_status_to_delivery_mode_to_draft_snapshot_rates_to_or_bed_turnover
    """
    setup = missed_target_cesarean_delivered_into_a_draft_snapshot
    assert setup["incised"]["decision_to_incision_minutes"] == 34
    assert setup["incised"]["met_target"] is False

    delivered = setup["delivered"]
    assert_cesarean_event(delivered)
    assert delivered["status"] == "REVIEW_PENDING"
    assert delivered["urgency_class"] == "CATEGORY_2_URGENT"
    assert_instant_equals(delivered["delivery_at"], DELIVERY_AT, "delivery_at")


def test_the_server_chooses_the_delivery_mode_from_the_encounters_own_history(
    missed_target_cesarean_delivered_into_a_draft_snapshot,
):
    """"The system, not the caller, chooses the delivery mode: the encounter's
    `delivery_mode` becomes `CESAREAN_REPEAT` when its `prior_cesarean` is true
    and `CESAREAN_PRIMARY` otherwise, and `delivery_recorded_at` is set to
    `delivery_at`." The phase ladder is untouched, so the encounter is still
    ANTEPARTUM when the mode lands on it.

    Design: Difficulty/transitive_cascade/record_delivery_cascades_event_status_to_delivery_mode_to_draft_snapshot_rates_to_or_bed_turnover
    """
    setup = missed_target_cesarean_delivered_into_a_draft_snapshot
    assert setup["encounter_before"]["delivery_mode"] is None
    encounter = reload_encounter(setup["world"], setup["encounter_id"])
    assert_labor_encounter(encounter)
    assert encounter["delivery_mode"] == "CESAREAN_PRIMARY"
    assert_instant_equals(
        encounter["delivery_recorded_at"], DELIVERY_AT, "delivery_recorded_at"
    )
    assert encounter["review_required"] is True
    assert encounter["is_ntsv"] is True
    assert encounter["labor_phase"] == "ANTEPARTUM"


def test_the_draft_snapshot_is_recomputed_in_place(
    missed_target_cesarean_delivered_into_a_draft_snapshot,
):
    """"Every `DRAFT` quality snapshot whose window contains
    `delivery_recorded_at` is recomputed, in both its authoritative and its
    shadow variant; a `CERTIFIED` snapshot is never retro-mutated." The caller
    never names the snapshot, and no second POST is needed to refresh it.

    Design: Difficulty/transitive_cascade/record_delivery_cascades_event_status_to_delivery_mode_to_draft_snapshot_rates_to_or_bed_turnover
    """
    setup = missed_target_cesarean_delivered_into_a_draft_snapshot
    before = setup["snapshot_before"]
    assert before["ntsv_cesarean_denominator"] == 0
    assert before["ntsv_cesarean_numerator"] == 0
    assert before["ntsv_cesarean_rate_pct"] is None

    after = setup["snapshot_after"]
    assert_snapshot(after)
    assert after["status"] == "DRAFT"
    assert after["attribution_basis"] == "DELIVERY_COHORT"
    assert after["ntsv_cesarean_denominator"] == 1
    assert after["ntsv_cesarean_numerator"] == 1
    assert after["ntsv_cesarean_rate_pct"] == pytest.approx(100.0000, abs=1e-4)


def test_an_empty_episiotomy_denominator_nulls_its_rate_and_the_composite(
    missed_target_cesarean_delivered_into_a_draft_snapshot,
):
    """"Each rate — `ntsv_cesarean_rate_pct` and `episiotomy_rate_pct` — is null
    when its own denominator is 0 — never 0.0", and "The
    `composite_quality_index` is null when either rate is null, and otherwise is
    the sum of the two rates divided by 2.0, rounded to 2 decimal places
    half-up." The only cohort member delivered by cesarean, so the vaginal
    denominator stays empty.

    Design: Difficulty/transitive_cascade/record_delivery_cascades_event_status_to_delivery_mode_to_draft_snapshot_rates_to_or_bed_turnover
    """
    after = missed_target_cesarean_delivered_into_a_draft_snapshot["snapshot_after"]
    assert after["episiotomy_denominator"] == 0
    assert after["episiotomy_numerator"] == 0
    assert after["episiotomy_rate_pct"] is None
    assert after["composite_quality_index"] is None


def test_the_shadow_variant_is_recomputed_alongside_the_authoritative_one(
    missed_target_cesarean_delivered_into_a_draft_snapshot,
):
    """"The advisory figures use `admitted_at` instead and are written into
    `shadow_ntsv_rate_pct` for internal trending only; they are never certified
    and never gate anything." This patient was admitted inside the same window
    she delivered in, so both variants agree at 100.0000.

    Design: Difficulty/transitive_cascade/record_delivery_cascades_event_status_to_delivery_mode_to_draft_snapshot_rates_to_or_bed_turnover
    """
    setup = missed_target_cesarean_delivered_into_a_draft_snapshot
    assert setup["snapshot_before"]["shadow_ntsv_rate_pct"] is None
    assert setup["snapshot_after"]["shadow_ntsv_rate_pct"] == pytest.approx(
        100.0000, abs=1e-4
    )


def test_the_operating_room_bed_clears_against_the_current_turnover_buffer(
    missed_target_cesarean_delivered_into_a_draft_snapshot,
):
    """"The OR bed moves from `OCCUPIED` to `TURNOVER` with `turnover_clear_at`
    set to the current instant plus the unit's `turnover_buffer_minutes`."
    Mobilisation forced one-to-one coverage on an uncovered encounter, so the
    buffer in force is 75 rather than 45: 09:00 plus 75 minutes is 10:15.

    Design: Difficulty/transitive_cascade/record_delivery_cascades_event_status_to_delivery_mode_to_draft_snapshot_rates_to_or_bed_turnover
    """
    setup = missed_target_cesarean_delivered_into_a_draft_snapshot
    world = setup["world"]
    unit = world.reload_unit()
    assert_obstetric_unit(unit)
    # The exact deficit and posture left behind by the REVIEW_PENDING walk-on are
    # not derivable from the PRD: "`TIER_IV` fires when ... a cesarean event on
    # the encounter is in `DECISION_DECLARED`, `TEAM_MOBILIZED` or
    # `INCISION_RECORDED`" with "`one_to_one_required` ... false otherwise" makes
    # the deficit fall to 0.5 the moment the event leaves theatre, while
    # "Closing ... drops the encounter from the in-theatre clause of the posture
    # derivation" makes 4.0 survive until the event is CLOSED. The recording
    # paragraph never says which, so only the figure both readings agree on --
    # a non-OPEN posture, hence a 75-minute buffer -- is asserted here.
    assert unit["turnover_buffer_minutes"] == 75
    assert unit["staffing_posture"] != "OPEN"

    or_bed = get_success_data(
        api_client.get_bed(world.bed_id("OR-01"), world.charge_headers)
    )
    assert_bed(or_bed)
    assert or_bed["status"] == "TURNOVER"
    assert_instant_equals(
        or_bed["turnover_clear_at"], "2026-09-02T10:15:00Z", "turnover_clear_at"
    )
