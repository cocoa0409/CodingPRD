"""Quality measure snapshots under their delivery and admission cohorts."""

import pytest

from test_helpers import (
    advance_phase,
    api_client,
    assign_bed,
    assert_instant_equals,
    bootstrap_unit,
    create_active_shift,
    create_assessment,
    create_care_assignment,
    create_encounter,
    create_snapshot,
    declare_cesarean,
    get_success_data,
    mobilize_cesarean,
    reload_encounter,
    set_clock,
    setup_validated_drill,
)

SHIFT_START = "2026-08-31T21:00:00Z"
SHIFT_END = "2026-09-01T08:00:00Z"

COHORT_STAFF = {
    "charge": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "bedside": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "bedside2": {"staff_role": "RN_LABOR_DELIVERY", "fetal_monitoring_cert_level": "ADVANCED"},
    "ob": {"staff_role": "OB_ATTENDING", "fetal_monitoring_cert_level": "ADVANCED"},
    "anesthesia": {
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": True,
    },
    "tech": {
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "or_circulating_qualified": True,
    },
    "neonatal": {
        "staff_role": "NEONATAL_RESUSCITATOR",
        "fetal_monitoring_cert_level": "BASIC",
    },
}


def _deliver_vaginally(world, bed_label, shift, episiotomy_performed, clocks):
    """Walk one NTSV-eligible encounter to a spontaneous vaginal delivery."""
    encounter = create_encounter(world, parity=0, gestational_age_weeks=39)
    assign_bed(world, encounter, bed_label)
    create_assessment(
        world,
        encounter,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_I",
        baseline_rate_bpm=138,
        variability="MODERATE",
        recurrent_decelerations=False,
        assessed_at=clocks["first_assessment"],
    )
    create_care_assignment(world, encounter, shift, coverage_mode="ONE_TO_ONE")
    set_clock(clocks["latent"])
    advance_phase(world, encounter, "LATENT")
    set_clock(clocks["active"])
    advance_phase(world, encounter, "ACTIVE_FIRST_STAGE")
    set_clock(clocks["second_assessment"])
    create_assessment(
        world,
        encounter,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_I",
        baseline_rate_bpm=142,
        variability="MODERATE",
        recurrent_decelerations=False,
        assessed_at=clocks["second_assessment"],
    )
    set_clock(clocks["second_stage"])
    advance_phase(world, encounter, "SECOND_STAGE")
    set_clock(clocks["delivered"])
    advance_phase(
        world,
        encounter,
        "THIRD_STAGE_DELIVERED",
        acting_key="charge",
        delivery_mode="SPONTANEOUS_VAGINAL",
        episiotomy_performed=episiotomy_performed,
    )
    return encounter


@pytest.fixture
def september_snapshot():
    """Three NTSV deliveries inside 1 September, one of them admitted in August."""
    world = bootstrap_unit(
        clock=SHIFT_START,
        ldr_beds=4,
        or_rooms=2,
        bed_specs=[
            ("LDR-01", "LDR"),
            ("LDR-02", "LDR"),
            ("LDR-03", "LDR"),
            ("OR-01", "OR"),
        ],
        staff_specs=COHORT_STAFF,
    )
    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    bed1_shift = create_active_shift(world, "bedside", "BEDSIDE", SHIFT_START, SHIFT_END)
    bed2_shift = create_active_shift(world, "bedside2", "BEDSIDE", SHIFT_START, SHIFT_END)
    for key in ("anesthesia", "tech", "neonatal"):
        create_active_shift(world, key, "TRIAGE", SHIFT_START, SHIFT_END)

    setup_validated_drill(
        world,
        scheduled_for_utc=SHIFT_START,
        decision_at="2026-08-31T21:00:00Z",
        incision_at="2026-08-31T21:18:00Z",
        documented_key="ob",
        validator_key="charge",
        participant_keys=["ob", "anesthesia"],
        document_clock="2026-08-31T21:20:00Z",
    )

    # E1 straddles the window: admitted in August, delivered in September.
    set_clock("2026-08-31T22:00:00Z")
    straddler = create_encounter(world, parity=0, gestational_age_weeks=39)
    event = declare_cesarean(world, straddler, urgency_class="CATEGORY_2_URGENT")
    set_clock("2026-08-31T22:10:00Z")
    mobilize_cesarean(
        world, event, or_bed_label="OR-01", staff_keys=["anesthesia", "tech", "neonatal"]
    )
    set_clock("2026-08-31T22:25:00Z")
    get_success_data(
        api_client.record_incision(
            event["id"], {"incision_at": "2026-08-31T22:22:00Z"}, world.ob_headers
        )
    )
    set_clock("2026-09-01T03:00:00Z")
    event = get_success_data(
        api_client.record_delivery(
            event["id"], {"delivery_at": "2026-09-01T03:00:00Z"}, world.ob_headers
        )
    )

    set_clock("2026-09-01T04:00:00Z")
    _deliver_vaginally(
        world,
        "LDR-01",
        bed1_shift,
        True,
        {
            "first_assessment": "2026-09-01T04:00:00Z",
            "latent": "2026-09-01T04:05:00Z",
            "active": "2026-09-01T04:10:00Z",
            "second_assessment": "2026-09-01T06:20:00Z",
            "second_stage": "2026-09-01T06:25:00Z",
            "delivered": "2026-09-01T06:30:00Z",
        },
    )
    set_clock("2026-09-01T06:35:00Z")
    _deliver_vaginally(
        world,
        "LDR-02",
        bed2_shift,
        False,
        {
            "first_assessment": "2026-09-01T06:35:00Z",
            "latent": "2026-09-01T06:40:00Z",
            "active": "2026-09-01T06:45:00Z",
            "second_assessment": "2026-09-01T07:10:00Z",
            "second_stage": "2026-09-01T07:15:00Z",
            "delivered": "2026-09-01T07:20:00Z",
        },
    )

    set_clock("2026-09-02T00:30:00Z")
    snapshot = create_snapshot(
        world,
        "2026-09-01T00:00:00Z",
        "2026-09-02T00:00:00Z",
        acting_key="charge",
    )
    return {
        "world": world,
        "snapshot": snapshot,
        "straddler": reload_encounter(world, straddler["id"]),
        "event": event,
    }


def test_the_authoritative_cohort_is_keyed_on_the_delivery_instant(september_snapshot):
    """The August-admitted, September-delivered patient counts in the September
    authoritative cohort, so the NTSV denominator is 3 and the numerator 1.

    PRD 3.9: "The authoritative figures use `delivery_recorded_at` as the
    attribution instant; `attribution_basis` is always `DELIVERY_COHORT`, and
    these are the figures certification freezes and any external submission
    reports."

    Design: Difficulty/dual_variant_calc/september_snapshot_delivery_cohort_33_3333_vs_admission_shadow_0_0000
    """
    snapshot = september_snapshot["snapshot"]
    assert snapshot["attribution_basis"] == "DELIVERY_COHORT"
    assert snapshot["status"] == "DRAFT"
    assert snapshot["ntsv_cesarean_denominator"] == 3
    assert snapshot["ntsv_cesarean_numerator"] == 1
    assert snapshot["ntsv_cesarean_rate_pct"] == pytest.approx(33.3333, abs=0.00005)


def test_the_shadow_rate_excludes_the_patient_the_authoritative_rate_counts(
    september_snapshot,
):
    """The advisory variant keys the same window on the admission instant, so the
    only cesarean falls out of it and the two rates disagree.

    PRD 3.9: "a patient admitted at 2026-08-31T22:00:00Z who delivers by
    cesarean at 2026-09-01T03:00:00Z belongs to the August admission cohort and
    to the September delivery cohort, so the August snapshot's authoritative NTSV
    rate excludes her while its shadow rate includes her."

    Design: Difficulty/dual_variant_calc/september_snapshot_delivery_cohort_33_3333_vs_admission_shadow_0_0000
    """
    snapshot = september_snapshot["snapshot"]
    assert snapshot["shadow_ntsv_rate_pct"] == pytest.approx(0.0000, abs=0.00005)
    assert snapshot["shadow_ntsv_rate_pct"] != snapshot["ntsv_cesarean_rate_pct"]


def test_the_episiotomy_measure_carries_its_own_denominator(september_snapshot):
    """Only the two vaginal deliveries enter the episiotomy denominator, and only
    the one with an episiotomy enters its numerator.

    PRD 3.9: "The `episiotomy_denominator` counts cohort encounters whose
    `delivery_mode` is `SPONTANEOUS_VAGINAL` or `OPERATIVE_VAGINAL`, and the
    `episiotomy_numerator` counts those same encounters whose
    `episiotomy_performed` is additionally true."

    Design: Difficulty/dual_variant_calc/september_snapshot_delivery_cohort_33_3333_vs_admission_shadow_0_0000
    """
    snapshot = september_snapshot["snapshot"]
    assert snapshot["episiotomy_denominator"] == 2
    assert snapshot["episiotomy_numerator"] == 1
    assert snapshot["episiotomy_rate_pct"] == pytest.approx(50.0000, abs=0.00005)


def test_the_composite_index_averages_the_already_rounded_components(september_snapshot):
    """The composite is the mean of the two four-decimal rates rounded to two
    places, not the mean of the unrounded quotients.

    PRD 3.9: "The order here is pinned: the two component rates are rounded to 4
    decimal places first and it is those already-rounded values that are averaged
    and then rounded to 2 places."

    Design: Difficulty/dual_variant_calc/september_snapshot_delivery_cohort_33_3333_vs_admission_shadow_0_0000
    """
    snapshot = september_snapshot["snapshot"]
    assert snapshot["composite_quality_index"] == pytest.approx(41.67, abs=0.005)


def test_the_straddling_encounter_records_both_instants_and_its_ntsv_flag(
    september_snapshot,
):
    """The cesarean delivery writes the mode the system chooses and the delivery
    instant, while the admission instant stays in August.

    PRD 3.8: "the encounter's `delivery_mode` becomes `CESAREAN_REPEAT` when its
    `prior_cesarean` is true and `CESAREAN_PRIMARY` otherwise, and
    `delivery_recorded_at` is set to `delivery_at`."

    Design: Difficulty/dual_variant_calc/september_snapshot_delivery_cohort_33_3333_vs_admission_shadow_0_0000
    """
    straddler = september_snapshot["straddler"]
    assert_instant_equals(straddler["admitted_at"], "2026-08-31T22:00:00Z", "admitted_at")
    assert_instant_equals(
        straddler["delivery_recorded_at"], "2026-09-01T03:00:00Z", "delivery_recorded_at"
    )
    assert straddler["delivery_mode"] == "CESAREAN_PRIMARY"
    assert straddler["is_ntsv"] is True


def test_a_category_two_event_that_meets_its_target_closes_without_review(
    september_snapshot,
):
    """The measured interval truncates to whole minutes, meets the 30-minute
    urgent target, and routes the event straight to closure.

    PRD 3.8: "and straight to `CLOSED` when `met_target` is true and the
    `urgency_class` is `CATEGORY_2_URGENT`."

    Design: Difficulty/dual_variant_calc/september_snapshot_delivery_cohort_33_3333_vs_admission_shadow_0_0000
    """
    event = september_snapshot["event"]
    assert event["decision_to_incision_minutes"] == 22
    assert event["met_target"] is True
    assert event["status"] == "CLOSED"
