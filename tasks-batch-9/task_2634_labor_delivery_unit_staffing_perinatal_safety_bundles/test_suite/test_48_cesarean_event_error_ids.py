"""One crash cesarean probed at four rungs, with the abort door closed twice over.

The same abort call is refused for two different reasons on the same event: first
a clinical 422 because the latest tracing is CATEGORY_III, which a calmer reading
would lift, then a structural 409 because the incision is stamped, which nothing
lifts. Between the two, an incision recorded at the decision instant is rejected
outright — the measurement window is strict on its left edge and inclusive on its
right, so a zero-length interval is not a nought-minute triumph. The closing read
proves the readiness derivation consults its drill clause first: a five-minute
mean, far inside both ceilings, still leaves the unit NOT_READY.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_shift,
    assert_bed,
    assert_cesarean_event,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    assign_bed,
    bootstrap_unit,
    create_encounter,
    create_shift,
    get_success_data,
    reload_encounter,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
CLOCK_AFTER_THE_INCISION = "2026-08-01T06:10:00Z"
INCISION_INSTANT = "2026-08-01T06:05:00Z"
SHIFT_WINDOW = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
CRASH_TARGET_MINUTES = 15
MEASURED_MINUTES = 5
MEAN_D2I = 5.0
ONE_TO_ONE_UNITS = 4.0
STRAINED_BUFFER = 75

MARROWSTONE_STAFF = {
    "charge": {
        "full_name": "Thandiwe Okonkwo RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Solveig Aumonier MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "anesthesia": {
        "full_name": "Casimir Lindqvist MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "tech": {
        "full_name": "Ruthanne Villasenor ST",
        "staff_role": "SURGICAL_TECH",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "neonatal": {
        "full_name": "Obadiah Fenwick NNP",
        "staff_role": "NEONATAL_RESUSCITATOR",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_crash_event_probed_at_four_rungs():
    """Four ACTIVE TRIAGE-and-CHARGE entries, one bedded encounter, no drill at all.

    The theatre trio sit on `TRIAGE` rather than `OR_STANDBY` deliberately: with
    no validated drill on this unit nobody is drill-current, and mobilisation only
    asks for an `ACTIVE` roster entry of any slot.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=2,
        bed_specs=[
            ("LDR-01", "LDR"),
            ("LDR-02", "LDR"),
            ("OR-01", "OR"),
            ("OR-02", "OR"),
        ],
        staff_specs=MARROWSTONE_STAFF,
        unit_overrides={"unit_name": "Marrowstone Island Birthing Unit LDR"},
    )
    for staff_key, role_slot in (
        ("charge", "CHARGE"),
        ("anesthesia", "TRIAGE"),
        ("tech", "TRIAGE"),
        ("neonatal", "TRIAGE"),
    ):
        activate_shift(
            world, create_shift(world, staff_key, role_slot, *SHIFT_WINDOW)
        )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-MARR-3301",
        parity=0,
        gestational_age_weeks=39,
    )
    assign_bed(world, encounter, "LDR-01")
    assessment = get_success_data(
        api_client.create_assessment(
            {
                "encounter_id": encounter["id"],
                "interpreted_by_staff_id": world.staff_id("charge"),
                "category": "CATEGORY_III",
                "baseline_rate_bpm": 108,
                "variability": "ABSENT",
                "recurrent_decelerations": True,
            },
            world.charge_headers,
        )
    )
    declared = api_client.create_cesarean(
        {
            "encounter_id": encounter["id"],
            "urgency_class": "CATEGORY_1_CRASH",
            "triggering_assessment_id": assessment["id"],
        },
        world.ob_headers,
    )
    event = get_success_data(declared)
    second_declaration = api_client.create_cesarean(
        {"encounter_id": encounter["id"], "urgency_class": "CATEGORY_2_URGENT"},
        world.ob_headers,
    )
    only_one_event = api_client.list_cesareans(
        world.ob_headers, params={"limit": 10, "encounter_id": encounter["id"]}
    )
    category_three_abort = api_client.abort_to_vaginal(event["id"], {}, world.ob_headers)
    unit_before_mobilising = world.reload_unit()
    mobilised = api_client.mobilize_team(
        event["id"],
        {
            "or_bed_id": world.bed_id("OR-01"),
            "staff_ids": [
                world.staff_id("anesthesia"),
                world.staff_id("tech"),
                world.staff_id("neonatal"),
            ],
        },
        world.ob_headers,
    )
    zero_length = api_client.record_incision(
        event["id"], {"incision_at": CLOCK_START}, world.ob_headers
    )
    still_mobilised = get_success_data(
        api_client.get_cesarean(event["id"], world.ob_headers)
    )
    set_clock(CLOCK_AFTER_THE_INCISION)
    incised = api_client.record_incision(
        event["id"], {"incision_at": INCISION_INSTANT}, world.ob_headers
    )
    already_incised_abort = api_client.abort_to_vaginal(
        event["id"], {}, world.ob_headers
    )
    after_the_second_abort = get_success_data(
        api_client.get_cesarean(event["id"], world.ob_headers)
    )
    unit_at_the_end = world.reload_unit()
    coverage_report = api_client.get_coverage_report(
        world.unit_id, world.charge_headers, params={"limit": 10, "offset": 0}
    )
    return {
        "world": world,
        "encounter": encounter,
        "assessment": assessment,
        "declared": declared,
        "event": event,
        "second_declaration": second_declaration,
        "only_one_event": only_one_event,
        "category_three_abort": category_three_abort,
        "unit_before_mobilising": unit_before_mobilising,
        "mobilised": mobilised,
        "zero_length": zero_length,
        "still_mobilised": still_mobilised,
        "incised": incised,
        "already_incised_abort": already_incised_abort,
        "after_the_second_abort": after_the_second_abort,
        "unit_at_the_end": unit_at_the_end,
        "coverage_report": coverage_report,
    }


def test_the_declared_crash_event_opens_unmeasured(
    one_crash_event_probed_at_four_rungs,
):
    """"Both routes produce an identical row: status `DECISION_DECLARED` with
    `decision_at` at the current instant, the two triggering references left null on a
    clinician declaration unless supplied."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    assert setup["declared"].status_code == 201
    event = setup["event"]
    assert_cesarean_event(event)
    assert event["status"] == "DECISION_DECLARED"
    assert event["urgency_class"] == "CATEGORY_1_CRASH"
    assert_instant_equals(event["decision_at"], CLOCK_START, "decision_at")
    assert event["triggering_assessment_id"] == setup["assessment"]["id"]
    assert event["triggering_activation_id"] is None
    assert_instant_is_null(event["incision_at"], "incision_at")
    assert event["decision_to_incision_minutes"] is None
    assert event["met_target"] is None
    assert event["or_bed_id"] is None


def test_a_second_declaration_is_refused_while_the_first_is_live(
    one_crash_event_probed_at_four_rungs,
):
    """"At most one event per encounter may sit in a non-terminal status."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    validate_error(
        setup["second_declaration"],
        ApiErrorId.ERR_CESAREAN_EVENT_IN_PROGRESS.value,
        409,
    )
    body = setup["only_one_event"].json()
    assert body["meta"]["total_count"] == 1
    assert [row["id"] for row in body["data"]] == [setup["event"]["id"]]
    assert body["data"][0]["urgency_class"] == "CATEGORY_1_CRASH"


def test_a_category_three_tracing_holds_the_abort_door_shut(
    one_crash_event_probed_at_four_rungs,
):
    """"It requires `incision_at` to still be null, refused otherwise with
    `ERR_CESAREAN_ALREADY_INCISED`, and requires the latest assessment on the encounter
    to be `CATEGORY_I` or `CATEGORY_II`, since a `CATEGORY_III` tracing does not support
    abandoning the operation, refused otherwise with `ERR_FETAL_CATEGORY_BLOCKS_ABORT`."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    refused = setup["category_three_abort"]
    validate_error(refused, ApiErrorId.ERR_FETAL_CATEGORY_BLOCKS_ABORT.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_CESAREAN_ALREADY_INCISED.value
    )
    assert setup["assessment"]["category"] == "CATEGORY_III"


def test_a_crash_section_is_mobilised_despite_an_unready_unit(
    one_crash_event_probed_at_four_rungs,
):
    """"For a `CATEGORY_2_URGENT` event the unit's `cesarean_readiness_state` must not be
    `NOT_READY`, refused otherwise with `ERR_CESAREAN_READINESS_NOT_MET`; a
    `CATEGORY_1_CRASH` event bypasses that check entirely, because a crash section is
    never refused for a paperwork lapse."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    assert setup["unit_before_mobilising"]["cesarean_readiness_state"] == "NOT_READY"
    assert setup["mobilised"].status_code == 200
    mobilised = get_success_data(setup["mobilised"])
    assert_cesarean_event(mobilised)
    assert mobilised["status"] == "TEAM_MOBILIZED"
    assert mobilised["urgency_class"] == "CATEGORY_1_CRASH"
    assert mobilised["decision_to_incision_minutes"] is None
    assert setup["unit_before_mobilising"]["mean_d2i_minutes"] is None


def test_the_mobilised_roster_keeps_its_payload_order_and_takes_the_theatre(
    one_crash_event_probed_at_four_rungs,
):
    """"It names `or_bed_id`, which must be a bed of `bed_type` `OR` on the encounter's
    own unit whose `status` is `AVAILABLE`, refused otherwise with
    `ERR_OR_BED_UNAVAILABLE`, and `staff_ids`, an array of 3 to 12 staff identifiers
    whose payload order is preserved verbatim in `mobilized_staff_ids`."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    world = setup["world"]
    mobilised = get_success_data(setup["mobilised"])
    assert mobilised["or_bed_id"] == world.bed_id("OR-01")
    assert mobilised["mobilized_staff_ids"] == [
        world.staff_id("anesthesia"),
        world.staff_id("tech"),
        world.staff_id("neonatal"),
    ]
    theatre = get_success_data(
        api_client.get_bed(world.bed_id("OR-01"), world.charge_headers)
    )
    assert_bed(theatre)
    assert theatre["status"] == "OCCUPIED"
    in_theatre = reload_encounter(world, setup["encounter"]["id"])
    assert_labor_encounter(in_theatre)
    assert in_theatre["one_to_one_required"] is True


def test_an_incision_at_the_decision_instant_fails_the_strict_left_bound(
    one_crash_event_probed_at_four_rungs,
):
    """"The request names `incision_at`, which must be strictly after `decision_at` and
    at or before the current instant, refused otherwise with
    `ERR_CESAREAN_TIMESTAMP_OUT_OF_RANGE`."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    validate_error(
        setup["zero_length"], ApiErrorId.ERR_CESAREAN_TIMESTAMP_OUT_OF_RANGE.value, 400
    )
    unmoved = setup["still_mobilised"]
    assert_cesarean_event(unmoved)
    assert unmoved["status"] == "TEAM_MOBILIZED"
    assert_instant_is_null(unmoved["incision_at"], "incision_at")
    assert unmoved["decision_to_incision_minutes"] is None
    assert unmoved["met_target"] is None


def test_the_five_minute_interval_truncates_and_meets_the_crash_target(
    one_crash_event_probed_at_four_rungs,
):
    """"`met_target` is true when that figure is less than or equal to the event's
    target, the boundary counting as met: a measurement of exactly 15 on a
    `CATEGORY_1_CRASH` meets its target, and an interval of 30 minutes and 1 second
    measures 30 whole minutes and still meets a 30-minute target, so only 31 whole
    minutes fails."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    assert setup["incised"].status_code == 200
    incised = get_success_data(setup["incised"])
    assert_cesarean_event(incised)
    assert incised["status"] == "INCISION_RECORDED"
    assert_instant_equals(incised["incision_at"], INCISION_INSTANT, "incision_at")
    assert incised["decision_to_incision_minutes"] == MEASURED_MINUTES
    assert MEASURED_MINUTES <= CRASH_TARGET_MINUTES
    assert incised["met_target"] is True


def test_the_stamped_incision_locks_the_abort_door_for_good(
    one_crash_event_probed_at_four_rungs,
):
    """"**8.10** escalation and attempt-limit guards, yielding
    `ERR_ESCALATION_TIER_SKIPPED`, `ERR_ESCALATION_NOT_STARTED`,
    `ERR_CESAREAN_ALREADY_INCISED`, `ERR_DRILL_NOT_ABANDONABLE`,
    `ERR_BUNDLE_STAGE_BLOCKS_RESCIND`, `ERR_REVIEW_REWORK_LIMIT_REACHED`,
    `ERR_DRILL_REVISION_LIMIT_REACHED` or `ERR_SUPPORT_REENTRY_LIMIT_REACHED`, on fetal
    escalation, fetal escalation stand-down, cesarean abort, drill abandonment, drill
    documentation, bundle rescission, review rework request and support pass check-in."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    refused = setup["already_incised_abort"]
    assert refused.status_code == 409
    validate_error_is_one_of(
        refused,
        [
            ApiErrorId.ERR_CESAREAN_ALREADY_INCISED.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_FETAL_CATEGORY_BLOCKS_ABORT.value
    )


def test_the_locked_event_keeps_its_theatre_and_its_measurement(
    one_crash_event_probed_at_four_rungs,
):
    """"If an OR bed was held it moves from `OCCUPIED` to `TURNOVER` and `or_bed_id` is
    cleared to null." The refused abort ran none of that, so the theatre is still taken.

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    world = setup["world"]
    survivor = setup["after_the_second_abort"]
    assert_cesarean_event(survivor)
    assert survivor["status"] == "INCISION_RECORDED"
    assert survivor["or_bed_id"] == world.bed_id("OR-01")
    assert survivor["decision_to_incision_minutes"] == MEASURED_MINUTES
    theatre = get_success_data(
        api_client.get_bed(world.bed_id("OR-01"), world.charge_headers)
    )
    assert_bed(theatre)
    assert theatre["status"] == "OCCUPIED"


def test_the_drill_clause_outranks_a_five_minute_mean(
    one_crash_event_probed_at_four_rungs,
):
    """"The state is then decided by the first matching branch: `NOT_READY` when the current
    drill is null, or when the mean is non-null and strictly greater than 45.00;
    otherwise `DEGRADED` when the standby test is not satisfied, or when the mean is
    non-null and strictly greater than 30.00; otherwise `READY`."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    unit = setup["unit_at_the_end"]
    assert_obstetric_unit(unit)
    assert unit["mean_d2i_minutes"] == pytest.approx(MEAN_D2I, abs=1e-9)
    assert unit["current_drill_id"] is None
    assert unit["cesarean_readiness_state"] == "NOT_READY"


def test_the_uncovered_theatre_patient_freezes_the_unit_on_its_deficit(
    one_crash_event_probed_at_four_rungs,
):
    """"The thresholds are exact: a deficit of 4.0 freezes inductions and a deficit of
    3.9 does not; a deficit of 0.1 strains the unit and a deficit of exactly 0.0 does
    not."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    unit = setup["unit_at_the_end"]
    assert unit["coverage_deficit_units"] == pytest.approx(ONE_TO_ONE_UNITS, abs=1e-9)
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER
    uncovered = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(uncovered)
    assert uncovered["acuity_tier"] == "TIER_IV"
    assert uncovered["required_coverage_units"] == pytest.approx(
        ONE_TO_ONE_UNITS, abs=1e-9
    )
    assert uncovered["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_coverage_report_names_the_deficit_branch_that_fired(
    one_crash_event_probed_at_four_rungs,
):
    """"A unit's coverage report exposes this whole derivation: one row per non-terminal
    encounter with its required units, its assigned units and its own contribution to
    the deficit, ordered by `created_at` ascending and paginated by `limit` and `offset`,
    together with the rolled-up `coverage_deficit_units` and the reason code for the
    branch that fired — `DIVERT_DEFICIT`, `NO_AVAILABLE_LDR_BED`, `STAGE_3_BUNDLE`,
    `FREEZE_DEFICIT`, `ESCALATION_BREACH`, `BUNDLE_BREACH`, `READINESS_NOT_READY`,
    `STAGE_2_WITH_DEFICIT`, `DEFICIT_POSITIVE`, `BREACHED_ENCOUNTER` or `NONE`."

    Design: Corner/errors/four_cesarean_event_ids_from_a_duplicate_declaration_through_a_zero_length_incision_to_a_locked_abort
    """
    setup = one_crash_event_probed_at_four_rungs
    assert setup["coverage_report"].status_code == 200
    report = get_success_data(setup["coverage_report"])
    assert report["staffing_posture"] == "INDUCTION_FROZEN"
    assert report["posture_reason"] == "FREEZE_DEFICIT"
    assert report["coverage_deficit_units"] == pytest.approx(
        ONE_TO_ONE_UNITS, abs=1e-9
    )
    rows = report["encounters"]
    assert len(rows) == 1
    assert rows[0]["encounter_id"] == setup["encounter"]["id"]
    assert rows[0]["deficit_units"] == pytest.approx(ONE_TO_ONE_UNITS, abs=1e-9)
