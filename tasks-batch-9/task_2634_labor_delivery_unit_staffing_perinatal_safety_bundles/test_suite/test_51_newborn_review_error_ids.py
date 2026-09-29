"""Both edges of the seventy-two-hour debrief window, and the only deadline that moves.

The scheduling window is inclusive on both sides, so the triple probed here — one
second early, one hour late, and the deadline instant exactly — separates a
correct implementation from one that used a strict comparison at either end. The
two priority-9 fields are then omitted one at a time, so neither refusal can be
returned for the other's absence. Finally the window is proven mutable in exactly
one way: each rework resets the deadline to twenty-four hours from now rather
than extending the original seventy-two, and the third lap is refused outright.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_newborn_review,
    bootstrap_unit,
    create_encounter,
    get_success_data,
    reload_encounter,
    set_clock,
)

CLOCK_OPENED = "2026-08-01T06:00:00Z"
DEBRIEF_DUE_AT = "2026-08-04T06:00:00Z"
ONE_SECOND_TOO_EARLY = "2026-08-01T05:59:59Z"
ONE_HOUR_TOO_LATE = "2026-08-04T07:00:00Z"
SECOND_LAP_DUE_AT = "2026-08-05T06:00:00Z"
SECOND_LAP_SCHEDULED_FOR = "2026-08-04T12:00:00Z"
THIRD_LAP_DUE_AT = "2026-08-05T12:00:00Z"
THIRD_LAP_SCHEDULED_FOR = "2026-08-04T13:00:00Z"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
REWORK_LIMIT = 2

FIRST_FINDINGS = (
    "Cord gas review complete; the resuscitation team was present within ninety "
    "seconds of delivery."
)
SECOND_FINDINGS = (
    "Second debrief held with the monitoring technician present; timeline "
    "reconstructed from strip archive."
)
THIRD_FINDINGS = (
    "Third debrief held; anesthesia timeline reconciled against the theatre log "
    "and the monitor strip."
)
FIRST_FACTORS = ["COMMUNICATION", "MONITORING_INTERPRETATION"]
SECOND_FACTORS = ["MONITORING_INTERPRETATION"]
THIRD_FACTORS = ["MONITORING_INTERPRETATION", "STAFFING_RATIO"]
FIRST_REWORK_REASON = (
    "Factor codes do not reconcile with the fetal monitoring record; re-run the debrief."
)
SECOND_REWORK_REASON = (
    "Second submission still omits the anesthesia timeline; one further debrief is "
    "required."
)
THIRD_REWORK_REASON = (
    "A third rework is being attempted deliberately to probe the bounded rework loop."
)

SABLEWOOD_STAFF = {
    "charge": {
        "full_name": "Marisol Everdene RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "facilitator": {
        "full_name": "Hyacinth Oyelaran RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Ignatius Wolverton RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_review_pushed_through_three_debrief_laps():
    """An `ANTEPARTUM` encounter with no bed, no coverage row and no bundle at all.

    Nothing on the encounter can trip the all-bundles-closed clause of
    submit-findings, and the facilitator has never held a care assignment on it,
    so every refusal below is the one the probe was aimed at.
    """
    world = bootstrap_unit(
        clock=CLOCK_OPENED,
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=SABLEWOOD_STAFF,
        unit_overrides={"unit_name": "Sablewood Harbor Family Birth LDR"},
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-SABL-6601",
        parity=2,
        gestational_age_weeks=41,
    )
    opened = api_client.create_review(
        {
            "encounter_id": encounter["id"],
            "complication_code": "APGAR5_UNDER_7",
            "facilitator_staff_id": world.staff_id("facilitator"),
        },
        world.charge_headers,
    )
    review = get_success_data(opened)
    encounter_once_the_review_is_open = reload_encounter(world, encounter["id"])

    def _schedule(debrief_scheduled_for_utc):
        return api_client.schedule_debrief(
            review["id"],
            {"debrief_scheduled_for_utc": debrief_scheduled_for_utc},
            world.charge_headers,
        )

    def _submit(**payload):
        return api_client.submit_findings(review["id"], payload, world.charge_headers)

    def _rework(rework_reason):
        return api_client.request_rework(
            review["id"], {"rework_reason": rework_reason}, world.officer_headers
        )

    def _read():
        return get_success_data(api_client.get_review(review["id"], world.charge_headers))

    one_second_early = _schedule(ONE_SECOND_TOO_EARLY)
    one_hour_late = _schedule(ONE_HOUR_TOO_LATE)
    review_after_both_window_refusals = _read()
    on_the_deadline_instant = _schedule(DEBRIEF_DUE_AT)
    before_the_debrief_is_held = _submit(
        findings_summary=FIRST_FINDINGS, contributing_factor_codes=FIRST_FACTORS
    )
    review_after_the_not_held_refusal = _read()
    set_clock(DEBRIEF_DUE_AT)
    notes_omitted = _submit(contributing_factor_codes=FIRST_FACTORS)
    factors_omitted = _submit(findings_summary=FIRST_FINDINGS)
    review_after_both_priority_nine_refusals = _read()
    first_submission = _submit(
        findings_summary=FIRST_FINDINGS, contributing_factor_codes=FIRST_FACTORS
    )
    first_rework = _rework(FIRST_REWORK_REASON)
    second_schedule = _schedule(SECOND_LAP_SCHEDULED_FOR)
    set_clock(SECOND_LAP_SCHEDULED_FOR)
    second_submission = _submit(
        findings_summary=SECOND_FINDINGS, contributing_factor_codes=SECOND_FACTORS
    )
    second_rework = _rework(SECOND_REWORK_REASON)
    third_schedule = _schedule(THIRD_LAP_SCHEDULED_FOR)
    set_clock(THIRD_LAP_SCHEDULED_FOR)
    third_submission = _submit(
        findings_summary=THIRD_FINDINGS, contributing_factor_codes=THIRD_FACTORS
    )
    third_rework = _rework(THIRD_REWORK_REASON)
    review_after_the_rework_limit = _read()
    closed = api_client.close_review(review["id"], world.officer_headers)
    encounter_at_the_end = reload_encounter(world, encounter["id"])
    return {
        "world": world,
        "encounter": encounter,
        "opened": opened,
        "review": review,
        "encounter_once_the_review_is_open": encounter_once_the_review_is_open,
        "one_second_early": one_second_early,
        "one_hour_late": one_hour_late,
        "review_after_both_window_refusals": review_after_both_window_refusals,
        "on_the_deadline_instant": on_the_deadline_instant,
        "before_the_debrief_is_held": before_the_debrief_is_held,
        "review_after_the_not_held_refusal": review_after_the_not_held_refusal,
        "notes_omitted": notes_omitted,
        "factors_omitted": factors_omitted,
        "review_after_both_priority_nine_refusals": (
            review_after_both_priority_nine_refusals
        ),
        "first_submission": first_submission,
        "first_rework": first_rework,
        "second_schedule": second_schedule,
        "second_submission": second_submission,
        "second_rework": second_rework,
        "third_schedule": third_schedule,
        "third_submission": third_submission,
        "third_rework": third_rework,
        "review_after_the_rework_limit": review_after_the_rework_limit,
        "closed": closed,
        "encounter_at_the_end": encounter_at_the_end,
    }


def test_the_review_opens_with_a_seventy_two_hour_deadline_and_nothing_else(
    one_review_pushed_through_three_debrief_laps,
):
    """"The review opens at `OPEN` with `opened_at` at the current instant and
    `debrief_due_at` set to `opened_at` plus 72 hours, and sets the encounter's
    `review_required` to true."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    assert setup["opened"].status_code == 201
    review = setup["review"]
    assert_newborn_review(review)
    assert review["status"] == "OPEN"
    assert review["complication_code"] == "APGAR5_UNDER_7"
    assert_instant_equals(review["opened_at"], CLOCK_OPENED, "opened_at")
    assert_instant_equals(review["debrief_due_at"], DEBRIEF_DUE_AT, "debrief_due_at")
    assert review["rework_count"] == 0
    assert_instant_is_null(
        review["debrief_scheduled_for_utc"], "debrief_scheduled_for_utc"
    )
    assert_instant_is_null(review["debrief_held_at"], "debrief_held_at")
    assert review["findings_summary"] is None
    assert not review["contributing_factor_codes"]
    flagged = setup["encounter_once_the_review_is_open"]
    assert_labor_encounter(flagged)
    assert flagged["review_required"] is True


def test_both_edges_of_the_window_answer_with_the_same_identifier(
    one_review_pushed_through_three_debrief_laps,
):
    """"**14.2** windows and deadlines, yielding `ERR_ESCALATION_WINDOW_EXPIRED`,
    `ERR_DEBRIEF_WINDOW_VIOLATION`, `ERR_DEBRIEF_NOT_HELD`, `ERR_DRILL_NOT_DUE`,
    `ERR_INDUCTION_ADMIT_TOO_EARLY`, `ERR_BOOKING_START_IN_PAST` or
    `ERR_MEASURE_PERIOD_INVALID`, all at HTTP 422, on fetal escalation, review debrief
    scheduling, review findings submission, drill start, induction booking creation,
    induction admission and snapshot creation."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    for refused in (setup["one_second_early"], setup["one_hour_late"]):
        validate_error(refused, ApiErrorId.ERR_DEBRIEF_WINDOW_VIOLATION.value, 422)
    still_open = setup["review_after_both_window_refusals"]
    assert_newborn_review(still_open)
    assert still_open["status"] == "OPEN"
    assert_instant_is_null(
        still_open["debrief_scheduled_for_utc"], "debrief_scheduled_for_utc"
    )


def test_the_deadline_instant_itself_is_a_legal_slot(
    one_review_pushed_through_three_debrief_laps,
):
    """"The named `debrief_scheduled_for_utc` must be at or after the current instant and
    at or before `debrief_due_at`, both boundaries inclusive, refused otherwise with
    `ERR_DEBRIEF_WINDOW_VIOLATION`."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    assert setup["on_the_deadline_instant"].status_code == 200
    booked = get_success_data(setup["on_the_deadline_instant"])
    assert_newborn_review(booked)
    assert booked["status"] == "DEBRIEF_SCHEDULED"
    assert_instant_equals(
        booked["debrief_scheduled_for_utc"], DEBRIEF_DUE_AT, "debrief_scheduled_for_utc"
    )
    assert_instant_equals(booked["debrief_due_at"], DEBRIEF_DUE_AT, "debrief_due_at")
    assert_instant_is_null(booked["debrief_held_at"], "debrief_held_at")


def test_a_perfectly_valid_submission_is_still_early(
    one_review_pushed_through_three_debrief_laps,
):
    """"Submission requires the current instant to be at or after
    `debrief_scheduled_for_utc`, the boundary instant counting as held, refused otherwise
    with `ERR_DEBRIEF_NOT_HELD`, and requires every bundle activation on the encounter to
    be `CLOSED` or `RESCINDED`, refused otherwise with `ERR_BUNDLE_NOT_CLOSED`."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    refused = setup["before_the_debrief_is_held"]
    validate_error(refused, ApiErrorId.ERR_DEBRIEF_NOT_HELD.value, 422)
    assert (
        refused.json()["data"]["error_id"] != ApiErrorId.ERR_BUNDLE_NOT_CLOSED.value
    )
    unheld = setup["review_after_the_not_held_refusal"]
    assert_newborn_review(unheld)
    assert unheld["status"] == "DEBRIEF_SCHEDULED"
    assert_instant_is_null(unheld["debrief_held_at"], "debrief_held_at")
    assert unheld["findings_summary"] is None


def test_omitting_the_notes_names_the_notes(
    one_review_pushed_through_three_debrief_laps,
):
    """"The same `ChargeNurse` role then submits findings, moving the review from
    `DEBRIEF_SCHEDULED` to `FINDINGS_SUBMITTED`, naming `findings_summary` of 40 to 2000
    characters, refused otherwise with `ERR_DEBRIEF_NOTES_REQUIRED`, and
    `contributing_factor_codes`, a non-empty array of 1 to 10 entries."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    refused = setup["notes_omitted"]
    validate_error(refused, ApiErrorId.ERR_DEBRIEF_NOTES_REQUIRED.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_CONTRIBUTING_FACTORS_REQUIRED.value
    )
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_DEBRIEF_NOT_HELD.value


def test_omitting_the_factor_codes_names_the_factor_codes(
    one_review_pushed_through_three_debrief_laps,
):
    """"**Priority 9** — context-required fields and their length bounds, at HTTP 422:
    `ERR_RESCIND_REASON_REQUIRED`, `ERR_INVALIDATION_REASON_REQUIRED`,
    `ERR_DEBRIEF_NOTES_REQUIRED`, `ERR_CONTRIBUTING_FACTORS_REQUIRED` and
    `ERR_DELIVERY_MODE_REQUIRED`, on bundle rescission, bundle debrief closure, drill
    invalidation, review findings submission, review closure and phase advance."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    refused = setup["factors_omitted"]
    validate_error(refused, ApiErrorId.ERR_CONTRIBUTING_FACTORS_REQUIRED.value, 422)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_DEBRIEF_NOTES_REQUIRED.value
    )
    unmoved = setup["review_after_both_priority_nine_refusals"]
    assert_newborn_review(unmoved)
    assert unmoved["status"] == "DEBRIEF_SCHEDULED"
    assert unmoved["findings_summary"] is None
    assert not unmoved["contributing_factor_codes"]


def test_the_boundary_instant_counts_as_held_and_lateness_is_not_punished(
    one_review_pushed_through_three_debrief_laps,
):
    """"Note the deliberate asymmetry with the scheduling gate: findings may be submitted
    after `debrief_due_at` has already passed, since only the scheduling was bounded and
    lateness is not blocked here."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    assert setup["first_submission"].status_code == 200
    submitted = get_success_data(setup["first_submission"])
    assert_newborn_review(submitted)
    assert submitted["status"] == "FINDINGS_SUBMITTED"
    assert_instant_equals(submitted["debrief_held_at"], DEBRIEF_DUE_AT, "debrief_held_at")
    assert submitted["findings_summary"] == FIRST_FINDINGS
    assert set(submitted["contributing_factor_codes"]) == set(FIRST_FACTORS)
    assert len(submitted["contributing_factor_codes"]) == len(FIRST_FACTORS)


def test_the_first_rework_wipes_the_lap_and_moves_the_deadline(
    one_review_pushed_through_three_debrief_laps,
):
    """"It increments `rework_count` by 1, clears `findings_summary`,
    `contributing_factor_codes`, `debrief_scheduled_for_utc` and `debrief_held_at`, and
    extends `debrief_due_at` to the current instant plus 24 hours."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    assert setup["first_rework"].status_code == 200
    sent_back = get_success_data(setup["first_rework"])
    assert_newborn_review(sent_back)
    assert sent_back["status"] == "REWORK_REQUESTED"
    assert sent_back["rework_count"] == 1
    assert_instant_equals(
        sent_back["debrief_due_at"], SECOND_LAP_DUE_AT, "debrief_due_at"
    )
    assert sent_back["findings_summary"] is None
    assert not sent_back["contributing_factor_codes"]
    assert_instant_is_null(
        sent_back["debrief_scheduled_for_utc"], "debrief_scheduled_for_utc"
    )
    assert_instant_is_null(sent_back["debrief_held_at"], "debrief_held_at")


def test_a_slot_beyond_the_original_deadline_becomes_legal_after_the_rework(
    one_review_pushed_through_three_debrief_laps,
):
    """"On a reworked review the value compared against is the extended `debrief_due_at`,
    so a slot that was rejected before the rework can become legal after it."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    assert setup["second_schedule"].status_code == 200
    rebooked = get_success_data(setup["second_schedule"])
    assert_newborn_review(rebooked)
    assert rebooked["status"] == "DEBRIEF_SCHEDULED"
    assert_instant_equals(
        rebooked["debrief_scheduled_for_utc"],
        SECOND_LAP_SCHEDULED_FOR,
        "debrief_scheduled_for_utc",
    )
    assert SECOND_LAP_SCHEDULED_FOR > ONE_HOUR_TOO_LATE
    assert setup["second_submission"].status_code == 200
    assert get_success_data(setup["second_submission"])["status"] == "FINDINGS_SUBMITTED"


def test_each_lap_resets_the_deadline_rather_than_stretching_the_original(
    one_review_pushed_through_three_debrief_laps,
):
    """"That extension is the only mutation of any deadline anywhere in this system; every
    other deadline in the specification is fixed at the moment it is derived."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    assert setup["second_rework"].status_code == 200
    second_lap = get_success_data(setup["second_rework"])
    assert_newborn_review(second_lap)
    assert second_lap["status"] == "REWORK_REQUESTED"
    assert second_lap["rework_count"] == REWORK_LIMIT
    assert_instant_equals(
        second_lap["debrief_due_at"], THIRD_LAP_DUE_AT, "debrief_due_at"
    )
    assert_instant_equals(setup["review"]["debrief_due_at"], DEBRIEF_DUE_AT, "opened due")
    assert setup["third_schedule"].status_code == 200
    assert setup["third_submission"].status_code == 200


def test_the_third_rework_is_refused_by_the_counter_not_by_the_edge(
    one_review_pushed_through_three_debrief_laps,
):
    """"This requires `rework_count` to be less than 2, refused otherwise with
    `ERR_REVIEW_REWORK_LIMIT_REACHED`, and the requester must not be the
    `facilitator_staff_id`, refused otherwise with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    refused = setup["third_rework"]
    validate_error(refused, ApiErrorId.ERR_REVIEW_REWORK_LIMIT_REACHED.value, 409)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    assert reported != ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value
    stalled = setup["review_after_the_rework_limit"]
    assert_newborn_review(stalled)
    assert stalled["status"] == "FINDINGS_SUBMITTED"
    assert stalled["rework_count"] == REWORK_LIMIT
    assert_instant_equals(stalled["debrief_due_at"], THIRD_LAP_DUE_AT, "debrief_due_at")


def test_closing_the_last_open_review_clears_the_encounter_flag(
    one_review_pushed_through_three_debrief_laps,
):
    """"Closing records `closed_by_user_id` as the acting user, re-derives the encounter's
    `review_required` to false once this was the last review that was not `CLOSED` and no
    cesarean event is in `REVIEW_PENDING`, unblocks discharge and makes a `REVIEW_PENDING`
    cesarean event closable."

    Design: Corner/errors/five_newborn_review_ids_from_both_edges_of_the_seventy_two_hour_window_to_the_second_rework_lap
    """
    setup = one_review_pushed_through_three_debrief_laps
    world = setup["world"]
    assert setup["closed"].status_code == 200
    shut = get_success_data(setup["closed"])
    assert_newborn_review(shut)
    assert shut["status"] == "CLOSED"
    assert shut["closed_by_user_id"] == world.staff_id("officer")
    assert shut["closed_by_user_id"] != shut["facilitator_staff_id"]
    assert shut["contributing_factor_codes"]
    cleared = setup["encounter_at_the_end"]
    assert_labor_encounter(cleared)
    assert cleared["review_required"] is False
