"""Three cycles that write on records other than the one being moved.

A rework request unwinds the lap the review already ran and rewrites the one
mutable deadline in the system from the clock. A second snapshot over the same
window reaches back and supersedes its predecessor. And a fetal escalation
refuses to advance two tiers at once even when every surrounding condition on
the call is satisfied.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_fetal_assessment,
    assert_instant_equals,
    assert_instant_is_null,
    assert_newborn_review,
    assert_snapshot,
    bootstrap_unit,
    create_active_shift,
    create_assessment,
    create_encounter,
    create_review,
    create_snapshot,
    get_success_data,
    reload_encounter,
    schedule_debrief,
    set_clock,
    submit_findings,
)

CLOCK_START = "2026-08-01T06:00:00Z"
DEBRIEF_SLOT = "2026-08-02T06:00:00Z"
ORIGINAL_DUE_AT = "2026-08-04T06:00:00Z"
EXTENDED_DUE_AT = "2026-08-03T06:00:00Z"
FINDINGS = (
    "Escalation was recognised late and the bedside handoff omitted the change "
    "in fetal category."
)
FACTOR_CODES = ["COMMUNICATION", "MONITORING_INTERPRETATION"]
REWORK_REASON = "Findings omit the escalation timeline and the handoff sequence."
PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-08-01T00:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
ESCALATION_DUE_AT = "2026-08-01T06:20:00Z"

REVIEW_STAFF = {
    "facilitator": {
        "full_name": "Simone Bardot RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "charge": {
        "full_name": "Hugo Mendez RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Dr Leona Frost",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}

REPORTING_STAFF = {
    "charge": {
        "full_name": "Delphine Aubert RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Bartholomew Nkosi RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}

ESCALATION_STAFF = {
    "charge": {
        "full_name": "Yuki Tanaka RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Dr Amara Solis",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_review_sent_back_around_the_cycle():
    """A review whose findings were submitted at the booked slot and then sent
    back for rework by the officer."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=REVIEW_STAFF,
        unit_overrides={"unit_name": "Nightingale Hollow Maternity LDR"},
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-REV-1212",
        parity=0,
        gestational_age_weeks=40,
    )
    review = create_review(
        world,
        encounter,
        facilitator_key="facilitator",
        acting_key="charge",
        complication_code="APGAR5_UNDER_7",
    )
    schedule_debrief(world, review, DEBRIEF_SLOT)
    set_clock(DEBRIEF_SLOT)
    submitted = submit_findings(
        world,
        review,
        findings_summary=FINDINGS,
        contributing_factor_codes=FACTOR_CODES,
    )
    reworked = get_success_data(
        api_client.request_rework(
            review["id"], {"rework_reason": REWORK_REASON}, world.officer_headers
        )
    )
    return {
        "world": world,
        "encounter": encounter,
        "review": review,
        "submitted": submitted,
        "reworked": reworked,
    }


def test_the_rework_unwinds_everything_the_previous_lap_wrote(
    a_review_sent_back_around_the_cycle,
):
    """"It increments `rework_count` by 1, clears `findings_summary`,
    `contributing_factor_codes`, `debrief_scheduled_for_utc` and
    `debrief_held_at`, and extends `debrief_due_at` to the current instant plus 24
    hours."

    Design: Corner/state_machines/rework_request_clears_the_findings_and_extends_the_debrief_deadline_by_twenty_four_hours
    """
    setup = a_review_sent_back_around_the_cycle
    assert setup["submitted"]["status"] == "FINDINGS_SUBMITTED"
    assert_instant_equals(
        setup["submitted"]["debrief_held_at"], DEBRIEF_SLOT, "debrief_held_at"
    )
    review = setup["reworked"]
    assert_newborn_review(review)
    assert review["status"] == "REWORK_REQUESTED"
    assert review["rework_count"] == 1
    assert review["findings_summary"] is None
    assert review["contributing_factor_codes"] is None
    assert_instant_is_null(
        review["debrief_scheduled_for_utc"], "debrief_scheduled_for_utc"
    )
    assert_instant_is_null(review["debrief_held_at"], "debrief_held_at")


def test_the_extended_deadline_is_measured_from_the_clock(
    a_review_sent_back_around_the_cycle,
):
    """"The review opens at `OPEN` with `opened_at` at the current instant and
    `debrief_due_at` set to `opened_at` plus 72 hours, and sets the encounter's
    `review_required` to true." The rework rewrites that deadline from the clock,
    so the new value lands 24 hours after 06:00 on the second — earlier than the
    72-hour original.

    Design: Corner/state_machines/rework_request_clears_the_findings_and_extends_the_debrief_deadline_by_twenty_four_hours
    """
    setup = a_review_sent_back_around_the_cycle
    assert_instant_equals(
        setup["review"]["opened_at"], CLOCK_START, "opened_at"
    )
    assert_instant_equals(
        setup["review"]["debrief_due_at"], ORIGINAL_DUE_AT, "debrief_due_at"
    )
    review = setup["reworked"]
    assert_instant_equals(review["debrief_due_at"], EXTENDED_DUE_AT, "debrief_due_at")
    assert_instant_equals(review["opened_at"], CLOCK_START, "opened_at")
    assert review["complication_code"] == "APGAR5_UNDER_7"
    assert review["facilitator_staff_id"] == setup["world"].staff_id("facilitator")
    encounter = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert encounter["review_required"] is True


@pytest.fixture
def two_snapshots_over_one_window():
    """Two snapshots computed over the byte-identical window on an empty unit."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[],
        staff_specs=REPORTING_STAFF,
        unit_overrides={"unit_name": "Heronwood Reporting Unit LDR"},
    )
    version_before_first = world.unit_version()
    first = create_snapshot(
        world, PERIOD_START, PERIOD_END, expected_unit_version=version_before_first
    )
    version_before_second = world.unit_version()
    second = create_snapshot(
        world, PERIOD_START, PERIOD_END, expected_unit_version=version_before_second
    )
    return {
        "world": world,
        "first": first,
        "second": second,
        "version_before_first": version_before_first,
        "version_before_second": version_before_second,
    }


def test_the_predecessor_is_the_row_that_carries_the_link(two_snapshots_over_one_window):
    """"The snapshot opens at `DRAFT`, and creating a snapshot for an identical
    window supersedes every existing row for that window, whether `DRAFT` or
    `CERTIFIED`, moving each to the terminal `SUPERSEDED` and writing the new
    snapshot's identifier into each predecessor's `superseded_by_snapshot_id`; a
    certified predecessor keeps its frozen counts for audit and is never
    recomputed."

    Design: Corner/state_machines/an_identical_window_snapshot_supersedes_its_predecessor_and_back_links_the_successor_id
    """
    setup = two_snapshots_over_one_window
    world = setup["world"]
    assert setup["first"]["status"] == "DRAFT"
    assert setup["first"]["superseded_by_snapshot_id"] is None
    predecessor = get_success_data(
        api_client.get_snapshot(setup["first"]["id"], world.officer_headers)
    )
    assert_snapshot(predecessor)
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by_snapshot_id"] == setup["second"]["id"]
    successor = setup["second"]
    assert_snapshot(successor)
    assert successor["status"] == "DRAFT"
    assert successor["superseded_by_snapshot_id"] is None
    assert successor["attribution_basis"] == "DELIVERY_COHORT"
    assert setup["version_before_second"] > setup["version_before_first"]


def test_an_empty_cohort_leaves_every_rate_null(two_snapshots_over_one_window):
    """"Each rate — `ntsv_cesarean_rate_pct` and `episiotomy_rate_pct` — is null
    when its own denominator is 0 — never 0.0 — and otherwise is 100.0 multiplied
    by that numerator and divided by that denominator, rounded to 4 decimal places
    half-up." With no delivered encounter in the unit both denominators are 0, and
    "The `composite_quality_index` is null when either rate is null".

    Design: Corner/state_machines/an_identical_window_snapshot_supersedes_its_predecessor_and_back_links_the_successor_id
    """
    snapshot = two_snapshots_over_one_window["second"]
    assert_snapshot(snapshot)
    assert snapshot["ntsv_cesarean_denominator"] == 0
    assert snapshot["ntsv_cesarean_numerator"] == 0
    assert snapshot["ntsv_cesarean_rate_pct"] is None
    assert snapshot["episiotomy_denominator"] == 0
    assert snapshot["episiotomy_numerator"] == 0
    assert snapshot["episiotomy_rate_pct"] is None
    assert snapshot["shadow_ntsv_rate_pct"] is None
    assert snapshot["composite_quality_index"] is None


@pytest.fixture
def an_escalation_that_skips_tier_one():
    """A fresh CATEGORY_II chain asked to jump straight to tier 2, with an
    eligible target and time still on the clock."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=ESCALATION_STAFF,
        unit_overrides={"unit_name": "Silverthorn Perinatal LDR"},
    )
    create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    create_active_shift(world, "ob", "BEDSIDE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-ESC-1313",
        parity=0,
        gestational_age_weeks=39,
    )
    assessment = create_assessment(
        world,
        encounter,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_II",
        baseline_rate_bpm=140,
        variability="MODERATE",
        recurrent_decelerations=True,
    )
    refused = api_client.escalate_assessment(
        assessment["id"],
        {"target_tier": 2, "notified_staff_id": world.staff_id("ob")},
        world.charge_headers,
    )
    return {"world": world, "assessment": assessment, "refused": refused}


def test_the_chain_refuses_to_advance_two_tiers_at_once(
    an_escalation_that_skips_tier_one,
):
    """"`target_tier` must equal `escalation_tier_high_water` plus 1, and the
    current `escalation_status` must be the chain step that precedes that tier —
    `ESCALATION_DUE` for tier 1, `TIER_1_NOTIFIED` for tier 2, `TIER_2_NOTIFIED`
    for tier 3 — refused otherwise with `ERR_ESCALATION_TIER_SKIPPED`."

    Design: Corner/state_machines/fetal_escalation_cannot_jump_to_tier_two_before_tier_one_has_been_notified
    """
    setup = an_escalation_that_skips_tier_one
    assessment = setup["assessment"]
    assert_fetal_assessment(assessment)
    assert assessment["escalation_status"] == "ESCALATION_DUE"
    assert_instant_equals(
        assessment["escalation_due_at"], ESCALATION_DUE_AT, "escalation_due_at"
    )
    validate_error(
        setup["refused"], ApiErrorId.ERR_ESCALATION_TIER_SKIPPED.value, 409
    )


def test_the_refused_escalation_leaves_the_chain_where_it_stood(
    an_escalation_that_skips_tier_one,
):
    """"A successful escalation sets `escalation_tier_high_water` to `target_tier`
    and moves `escalation_status` to `TIER_1_NOTIFIED`, `TIER_2_NOTIFIED` or
    `TIER_3_ACTIVATED`." No success, no write: the high-water mark stays 0 and
    nothing downstream of it is stamped.

    Design: Corner/state_machines/fetal_escalation_cannot_jump_to_tier_two_before_tier_one_has_been_notified
    """
    setup = an_escalation_that_skips_tier_one
    assessment = get_success_data(
        api_client.get_assessment(
            setup["assessment"]["id"], setup["world"].charge_headers
        )
    )
    assert_fetal_assessment(assessment)
    assert assessment["escalation_status"] == "ESCALATION_DUE"
    assert assessment["escalation_tier_high_water"] == 0
    assert_instant_is_null(assessment["next_tier_due_at"], "next_tier_due_at")
    assert_instant_is_null(assessment["reassessment_due_at"], "reassessment_due_at")
    assert assessment["version"] == 1
