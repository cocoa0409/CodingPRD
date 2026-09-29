"""The care participant is barred from the review before and after the release.

Three probes attack the facilitator gate from three different angles: at creation
while the care assignment is ACTIVE, at creation again after the same row has been
RELEASED, and at the debrief booking of a review that was clean when it opened and
acquired its defect half an hour later. The closing endpoint is then shown to hold
two independent disqualifiers — the facilitator and the released care participant
are both refused, and the identical call from an unrelated identity lands. One
probe runs the rework door for the same reason, to show the rule is not close-only.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_care_assignment,
    assert_instant_equals,
    assert_labor_encounter,
    assert_newborn_review,
    bootstrap_unit,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_encounter,
    set_clock,
)

CLOCK_OPENED = "2026-08-01T06:00:00Z"
CLOCK_DEBRIEF_HELD = "2026-08-01T06:30:00Z"
DEBRIEF_SLOT = "2026-08-01T06:30:00Z"
LATER_SLOT = "2026-08-01T07:00:00Z"
DEBRIEF_DUE_AT = "2026-08-04T06:00:00Z"
COVER_SHIFT = ("2026-08-01T06:00:00Z", "2026-08-01T14:00:00Z")
LATE_SHIFT = ("2026-08-01T06:30:00Z", "2026-08-01T14:30:00Z")
LIVE_CREDENTIAL = "2027-01-01T00:00:00Z"
TIER_ONE_ANTEPARTUM_UNITS = 0.5
FINDINGS_SUMMARY = (
    "Cord gas sampling was delayed by nine minutes and the neonatal team handoff "
    "was verbal only, with no written summary left at the bedside."
)
REWORK_REASON = "The findings omit the fetal monitoring timeline entirely."
FACTOR_CODES = ["COMMUNICATION_HANDOFF"]

HALLOWAY_STAFF = {
    "charge": {
        "full_name": "Marisol Ettinger RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "cover": {
        "full_name": "Perpetua Lindgren RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "fac_a": {
        "full_name": "Anselm Rutherglen RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "fac_b": {
        "full_name": "Theodora Winslowe MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Cordelia Vansittart RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def two_reviews_walked_past_four_facilitator_checks():
    """One encounter, one shared care row that is later released, two clean reviews.

    No bundle activation is ever opened on this encounter, so the submit-findings
    precondition that every activation be `CLOSED` or `RESCINDED` is satisfied
    vacuously and cannot be the reason for any refusal recorded here.
    """
    world = bootstrap_unit(
        clock=CLOCK_OPENED,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=HALLOWAY_STAFF,
        unit_overrides={"unit_name": "Halloway Bend Womens Hospital LDR"},
    )
    cover_shift = create_active_shift(world, "cover", "BEDSIDE", *COVER_SHIFT)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-HALL-9901",
        parity=1,
        gestational_age_weeks=39,
    )
    care_row = create_care_assignment(world, encounter, cover_shift)
    facilitate_while_active = api_client.create_review(
        {
            "encounter_id": encounter["id"],
            "complication_code": "APGAR5_UNDER_7",
            "facilitator_staff_id": world.staff_id("cover"),
        },
        world.charge_headers,
    )
    review_a = get_success_data(
        api_client.create_review(
            {
                "encounter_id": encounter["id"],
                "complication_code": "APGAR5_UNDER_7",
                "facilitator_staff_id": world.staff_id("fac_a"),
            },
            world.charge_headers,
        )
    )
    review_b = get_success_data(
        api_client.create_review(
            {
                "encounter_id": encounter["id"],
                "complication_code": "HIE_SUSPECTED",
                "facilitator_staff_id": world.staff_id("fac_b"),
            },
            world.charge_headers,
        )
    )
    released_row = get_success_data(
        api_client.release_care_assignment(care_row["id"], world.charge_headers)
    )
    facilitate_after_release = api_client.create_review(
        {
            "encounter_id": encounter["id"],
            "complication_code": "BIRTH_INJURY",
            "facilitator_staff_id": world.staff_id("cover"),
        },
        world.charge_headers,
    )
    reviews_on_the_encounter = api_client.list_reviews(
        world.charge_headers,
        params={"limit": 10, "offset": 0, "encounter_id": encounter["id"]},
    )
    scheduled_b = api_client.schedule_debrief(
        review_b["id"],
        {"debrief_scheduled_for_utc": DEBRIEF_SLOT},
        world.charge_headers,
    )
    set_clock(CLOCK_DEBRIEF_HELD)
    submitted_b = api_client.submit_findings(
        review_b["id"],
        {
            "findings_summary": FINDINGS_SUMMARY,
            "contributing_factor_codes": FACTOR_CODES,
        },
        world.charge_headers,
    )
    rework_by_the_facilitator = api_client.request_rework(
        review_b["id"],
        {"rework_reason": REWORK_REASON},
        world.officer_headers_for("fac_b"),
    )
    review_b_after_the_rework_refusal = get_success_data(
        api_client.get_review(review_b["id"], world.charge_headers)
    )
    close_by_the_facilitator = api_client.close_review(
        review_b["id"], world.officer_headers_for("fac_b")
    )
    close_by_the_released_participant = api_client.close_review(
        review_b["id"], world.officer_headers_for("cover")
    )
    close_by_a_bystander = api_client.close_review(
        review_b["id"], world.officer_headers
    )
    late_shift = create_active_shift(world, "fac_a", "BEDSIDE", *LATE_SHIFT)
    late_care_row = create_care_assignment(world, encounter, late_shift)
    schedule_by_a_freshly_conflicted_facilitator = api_client.schedule_debrief(
        review_a["id"],
        {"debrief_scheduled_for_utc": LATER_SLOT},
        world.charge_headers,
    )
    return {
        "world": world,
        "encounter": encounter,
        "care_row": care_row,
        "facilitate_while_active": facilitate_while_active,
        "review_a": review_a,
        "review_b": review_b,
        "released_row": released_row,
        "facilitate_after_release": facilitate_after_release,
        "reviews_on_the_encounter": reviews_on_the_encounter,
        "scheduled_b": scheduled_b,
        "submitted_b": submitted_b,
        "rework_by_the_facilitator": rework_by_the_facilitator,
        "review_b_after_the_rework_refusal": review_b_after_the_rework_refusal,
        "close_by_the_facilitator": close_by_the_facilitator,
        "close_by_the_released_participant": close_by_the_released_participant,
        "close_by_a_bystander": close_by_a_bystander,
        "late_care_row": late_care_row,
        "schedule_by_a_freshly_conflicted_facilitator": (
            schedule_by_a_freshly_conflicted_facilitator
        ),
        "review_a_at_the_end": get_success_data(
            api_client.get_review(review_a["id"], world.officer_headers)
        ),
        "encounter_at_the_end": reload_encounter(world, encounter["id"]),
    }


def test_the_shared_row_prices_the_antepartum_singleton_at_a_half_unit(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"A `RATIO_SHARED` row debits the product of two factors: the acuity weight, which is
    1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and 4.0 for `TIER_IV`; and the
    phase multiplier, which is 0.5 for `ANTEPARTUM`, 1.0 for `LATENT`, 1.5 for
    `ACTIVE_FIRST_STAGE`, 2.0 for `SECOND_STAGE`, 1.5 for `THIRD_STAGE_DELIVERED`, 0.5 for
    `POSTPARTUM_RECOVERY`, 0.0 for `DISCHARGED` and 0.0 for `TRANSFERRED_OUT`."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    row = setup["care_row"]
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["coverage_mode"] == "RATIO_SHARED"
    assert row["staff_id"] == setup["world"].staff_id("cover")
    assert row["acuity_units_consumed"] == pytest.approx(
        TIER_ONE_ANTEPARTUM_UNITS, abs=1e-9
    )


def test_the_nurse_at_the_bedside_cannot_facilitate_the_review(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"A `ChargeNurse` or `PerinatalSafetyOfficer` opens a newborn complication review on an
    encounter, naming `encounter_id`, a `complication_code` of `UNEXPECTED_NICU_TERM`,
    `HIE_SUSPECTED`, `APGAR5_UNDER_7`, `BIRTH_INJURY` or `UNEXPECTED_TRANSFER`, and a
    `facilitator_staff_id` who must belong to the same unit as the encounter and must never
    have held a care assignment on that encounter in any status whatsoever — not merely no
    active one — refused otherwise with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    refused = setup["facilitate_while_active"]
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
    )
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_STAFF_NOT_FOUND.value
    assert reported != ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value


def test_the_two_clean_facilitators_open_with_a_seventy_two_hour_deadline(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"The review opens at `OPEN` with `opened_at` at the current instant and
    `debrief_due_at` set to `opened_at` plus 72 hours, and sets the encounter's
    `review_required` to true."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    world = setup["world"]
    for review, facilitator, code in (
        (setup["review_a"], "fac_a", "APGAR5_UNDER_7"),
        (setup["review_b"], "fac_b", "HIE_SUSPECTED"),
    ):
        assert_newborn_review(review)
        assert review["status"] == "OPEN"
        assert review["complication_code"] == code
        assert review["facilitator_staff_id"] == world.staff_id(facilitator)
        assert_instant_equals(review["opened_at"], CLOCK_OPENED, "opened_at")
        assert_instant_equals(review["debrief_due_at"], DEBRIEF_DUE_AT, "debrief_due_at")
        assert review["rework_count"] == 0


def test_releasing_the_care_row_does_not_lift_the_facilitator_bar(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"Third, a staff member who has held a `CareAssignment` on an encounter — in any status
    whatsoever, active, released or superseded — may not be named as the facilitator of a
    newborn complication review on that encounter."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    released = setup["released_row"]
    assert_care_assignment(released)
    assert released["status"] == "RELEASED"
    validate_error(
        setup["facilitate_after_release"],
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        403,
    )


def test_neither_refused_opening_left_a_review_row_behind(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"Reviews are listed by `encounter_id`, `facilitator_staff_id`, `status` and
    `complication_code`, ordered by `opened_at` descending with `created_at` descending as
    the tie-break."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    body = setup["reviews_on_the_encounter"].json()
    assert body["meta"]["total_count"] == 2
    assert {row["id"] for row in body["data"]} == {
        setup["review_a"]["id"],
        setup["review_b"]["id"],
    }
    assert {row["complication_code"] for row in body["data"]} == {
        "APGAR5_UNDER_7",
        "HIE_SUSPECTED",
    }


def test_the_findings_land_on_the_boundary_instant_of_the_booked_slot(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"Submission requires the current instant to be at or after
    `debrief_scheduled_for_utc`, the boundary instant counting as held, refused otherwise
    with `ERR_DEBRIEF_NOT_HELD`, and requires every bundle activation on the encounter to be
    `CLOSED` or `RESCINDED`, refused otherwise with `ERR_BUNDLE_NOT_CLOSED`."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    assert setup["scheduled_b"].status_code == 200
    booked = get_success_data(setup["scheduled_b"])
    assert booked["status"] == "DEBRIEF_SCHEDULED"
    assert_instant_equals(
        booked["debrief_scheduled_for_utc"], DEBRIEF_SLOT, "debrief_scheduled_for_utc"
    )
    assert setup["submitted_b"].status_code == 200
    submitted = get_success_data(setup["submitted_b"])
    assert_newborn_review(submitted)
    assert submitted["status"] == "FINDINGS_SUBMITTED"
    assert_instant_equals(
        submitted["debrief_held_at"], CLOCK_DEBRIEF_HELD, "debrief_held_at"
    )


def test_the_facilitator_cannot_send_its_own_findings_back(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"This requires `rework_count` to be less than 2, refused otherwise with
    `ERR_REVIEW_REWORK_LIMIT_REACHED`, and the requester must not be the
    `facilitator_staff_id`, refused otherwise with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    refused = setup["rework_by_the_facilitator"]
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
    )
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_REVIEW_REWORK_LIMIT_REACHED.value
    assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value


def test_the_refused_rework_neither_counted_nor_moved_the_one_mutable_deadline(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"It increments `rework_count` by 1, clears `findings_summary`,
    `contributing_factor_codes`, `debrief_scheduled_for_utc` and `debrief_held_at`, and
    extends `debrief_due_at` to the current instant plus 24 hours." Also: "That extension is
    the only mutation of any deadline anywhere in this system; every other deadline in the
    specification is fixed at the moment it is derived."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    survivor = setup["review_b_after_the_rework_refusal"]
    assert_newborn_review(survivor)
    assert survivor["status"] == "FINDINGS_SUBMITTED"
    assert survivor["rework_count"] == 0
    assert_instant_equals(
        survivor["debrief_due_at"], DEBRIEF_DUE_AT, "debrief_due_at"
    )
    assert survivor["findings_summary"] == FINDINGS_SUMMARY
    assert survivor["contributing_factor_codes"] == FACTOR_CODES
    assert_instant_equals(
        survivor["debrief_held_at"], CLOCK_DEBRIEF_HELD, "debrief_held_at"
    )


def test_the_close_door_holds_two_independent_disqualifiers(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"The closer must be neither the `facilitator_staff_id` nor any staff member who ever
    held a care assignment on the encounter, refused otherwise with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, and `contributing_factor_codes` must still be
    non-empty."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    for refused in (
        setup["close_by_the_facilitator"],
        setup["close_by_the_released_participant"],
    ):
        validate_error(
            refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
        )


def test_an_unrelated_officer_closes_the_identical_review(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"Closing records `closed_by_user_id` as the acting user, re-derives the encounter's
    `review_required` to false once this was the last review that was not `CLOSED` and no
    cesarean event is in `REVIEW_PENDING`, unblocks discharge and makes a `REVIEW_PENDING`
    cesarean event closable."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    accepted = setup["close_by_a_bystander"]
    assert accepted.status_code == 200
    closed = get_success_data(accepted)
    assert_newborn_review(closed)
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == setup["world"].staff_id("officer")
    assert closed["contributing_factor_codes"] == FACTOR_CODES


def test_the_facilitator_check_is_re_run_at_the_debrief_booking(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"The facilitator segregation check is re-evaluated at this point." Also: "The named
    `debrief_scheduled_for_utc` must be at or after the current instant and at or before
    `debrief_due_at`, both boundaries inclusive, refused otherwise with
    `ERR_DEBRIEF_WINDOW_VIOLATION`."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    acquired = setup["late_care_row"]
    assert_care_assignment(acquired)
    assert acquired["status"] == "ACTIVE"
    assert acquired["staff_id"] == setup["world"].staff_id("fac_a")
    refused = setup["schedule_by_a_freshly_conflicted_facilitator"]
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value, 403
    )
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_DEBRIEF_WINDOW_VIOLATION.value
    )
    assert LATER_SLOT >= CLOCK_DEBRIEF_HELD
    assert LATER_SLOT <= DEBRIEF_DUE_AT


def test_the_unbookable_review_keeps_the_encounter_gated(
    two_reviews_walked_past_four_facilitator_checks,
):
    """"An open review blocks discharge and blocks the close of a `REVIEW_PENDING` cesarean
    event."

    Design: Corner/rbac/sod_3_and_sod_4_bar_every_care_participant_from_facilitating_reworking_or_closing_the_same_review
    """
    setup = two_reviews_walked_past_four_facilitator_checks
    stranded = setup["review_a_at_the_end"]
    assert_newborn_review(stranded)
    assert stranded["status"] == "OPEN"
    assert stranded["debrief_scheduled_for_utc"] is None
    encounter = setup["encounter_at_the_end"]
    assert_labor_encounter(encounter)
    assert encounter["review_required"] is True
