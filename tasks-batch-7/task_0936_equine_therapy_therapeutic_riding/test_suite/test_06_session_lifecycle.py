"""Booking through delivery: the quoted fee, the ridden fee, and cancellation."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID_A,
    UNKNOWN_UUID_B,
    allocation_total,
    allocations_for_charge,
    allocations_of,
    assert_same_instant,
    book_session,
    charges_for_session,
    make_horse,
    make_instructor,
    make_rider,
    make_instructor_headers,
    only_charge_for_session,
    read_session,
    set_clock,
    setup_active_rider,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, INTAKE


def test_quoted_fee_is_booked_minutes_and_the_charge_is_ridden_minutes(api):
    """PRD 3.6: "The quoted fee is `duration_minutes` multiplied by the
    per-minute rate of the `activity_type`, in whole cents, with no rounding
    needed because both operands are integers. `THERAPEUTIC_RIDING` bills 150
    cents a minute — so an hour of therapeutic riding quotes 9000 cents, ninety
    dollars."
    PRD 3.6: "A `SESSION_FEE` charge is created whose gross amount is billed on
    the minutes **actually ridden**, not the minutes booked: a 60-minute
    `THERAPEUTIC_RIDING` booking ridden for 45 minutes quotes 9000 cents on the
    session and bills 6750 cents on the charge, from identical stored data."

    Design: Difficulty/dual_variant_calc/session_fee_quoted_at_scheduling_vs_billed_at_completion
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    assert session["quoted_fee_cents"] == 9000
    validate_success(api.confirm_session(session["id"], scenario["instructor_headers"]))

    completed = validate_success(
        api.complete_session(
            session["id"], {"mounted_minutes": 45}, scenario["instructor_headers"]
        )
    )
    assert completed["quoted_fee_cents"] == 9000

    charge = only_charge_for_session(session["id"])
    assert charge["amount_cents"] == 6750
    assert charge["charge_type"] == "SESSION_FEE"
    assert charge["amount_cents"] != completed["quoted_fee_cents"], (
        "The quoted fee and the billed fee diverge from identical stored data"
    )


def test_completion_recomputes_service_hours_from_mounted_minutes(api):
    """PRD 3.6: "The session moves `CONFIRMED → COMPLETED`, `mounted_minutes` is
    stored, and `service_hours` is recomputed as the mounted minutes divided by
    60 and rounded half-up to 2 decimal places."
    PRD 3.6: "the session's `billing_status` becomes `FUNDED` when the resulting
    charge's `balance_due_cents` is 0 and `CHARGED` otherwise."

    Design: Difficulty/dual_variant_calc/session_fee_quoted_at_scheduling_vs_billed_at_completion
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    validate_success(api.confirm_session(session["id"], scenario["instructor_headers"]))

    completed = validate_success(
        api.complete_session(
            session["id"], {"mounted_minutes": 45}, scenario["instructor_headers"]
        )
    )
    assert completed["schedule_status"] == "COMPLETED"
    assert completed["mounted_minutes"] == 45
    assert completed["service_hours"] == pytest.approx(0.75, abs=0.001)

    charge = only_charge_for_session(session["id"])
    assert charge["balance_due_cents"] == 6750, (
        "BAND_D with payer 0 and no restricted money leaves the whole fee private"
    )
    assert read_session(session["id"])["billing_status"] == "CHARGED"


def test_second_confirm_is_refused_and_performs_no_mutation(api):
    """PRD 2.7 rung 19: "The target resource is in a from-state that the
    requested transition declares — otherwise `ERR_INVALID_STATE` (409). Applies
    to every action endpoint. This rung is what rejects a second confirmation of
    a confirmed session, a cancellation of an already-cancelled session, a
    no-show recorded before the scheduled start or against a session that is not
    `CONFIRMED`, a reversal of an already-reversed charge, a sign-off on a
    qualification that is already `QUALIFIED`, a review of an incident already
    `UNDER_REVIEW`, a close of an incident still `OPEN`, a finalization of a note
    that is no longer `DRAFT`, a discontinuation of an already-discontinued goal,
    a reopening of a goal that is not `MET`, a rating of a `DISCONTINUED` goal, a
    horse hold release attempted before `hold_release_at` has been reached, and a
    withdrawal of a rider who still holds sessions in `CREW_PENDING` or
    `CONFIRMED`."

    Design: Corner/state_machines/confirm_of_already_confirmed_session_returns_invalid_state
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    first = validate_success(
        api.confirm_session(session["id"], scenario["instructor_headers"])
    )
    version_after_first = first["version"]

    second = api.confirm_session(session["id"], scenario["instructor_headers"])
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_session(session["id"])
    assert after["schedule_status"] == "CONFIRMED"
    assert after["version"] == version_after_first, (
        "The rejected call performed no mutation"
    )


def test_no_show_before_scheduled_start_is_refused(api):
    """PRD 3.6: "A no-show is recorded by an `Instructor` or `ProgramAdmin`
    against a `CONFIRMED` session once the logical clock has reached
    `scheduled_start`; attempting it earlier, or against a session in any other
    state, is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/no_show_before_scheduled_start_returns_invalid_state
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    validate_success(api.confirm_session(session["id"], scenario["instructor_headers"]))

    too_early = api.record_no_show(session["id"], scenario["instructor_headers"])
    validate_error(too_early, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_session(session["id"])
    assert after["schedule_status"] == "CONFIRMED"
    assert after["billing_status"] == "UNBILLED"
    assert charges_for_session(session["id"]) == []


def test_cancellation_exactly_at_the_notice_window_is_free(api):
    """PRD 3.6: "`RIDER_REQUEST` is resolved against the notice window: the hours
    of notice are the time from the logical clock to the session's
    `scheduled_start`, and 24 hours or more of notice stores `EARLY_RIDER` while
    anything less stores `LATE_RIDER`."
    PRD 3.6: "Only the derived class `LATE_RIDER` creates a charge: a
    `LATE_CANCELLATION_FEE` for half the quoted fee, rounded half-up to whole
    cents, which then runs the waterfall. No other derived class creates any
    charge at all."

    Design: Corner/calculations/cancellation_exactly_at_the_notice_window_is_early_and_free
    """
    scenario = setup_active_rider(rider={"household_income_band": "BAND_B"})
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    validate_success(api.confirm_session(session["id"], scenario["instructor_headers"]))

    set_clock("2026-05-10T10:00:00Z")
    cancelled = validate_success(
        api.cancel_session(
            session["id"],
            {"cancellation_reason": "RIDER_REQUEST"},
            scenario["instructor_headers"],
        )
    )
    assert cancelled["cancellation_reason"] == "EARLY_RIDER"
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "UNBILLED"

    _, meta = validate_paginated(
        api.list_charges(CLERK, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0


def test_cancellation_inside_the_window_charges_half_the_quoted_fee(api):
    """PRD 3.6: "Only the derived class `LATE_RIDER` creates a charge: a
    `LATE_CANCELLATION_FEE` for half the quoted fee, rounded half-up to whole
    cents, which then runs the waterfall."
    PRD 3.8: "a `LATE_CANCELLATION_FEE` and a `NO_SHOW_FEE` may draw only on
    sliding scale, payer and private pay, with the grant and scholarship steps
    skipped entirely. A charge whose `charge_type` is not `SESSION_FEE` therefore
    carries `scholarship_excluded` true, and a `SESSION_FEE` carries it false."
    PRD 3.8: "The rider's `household_income_band` sets a discount percentage —
    `BAND_A` 60 per cent, `BAND_B` 40 per cent, `BAND_C` 20 per cent and `BAND_D`
    nothing at all — and the contribution is that percentage of the **current
    remainder**, rounded half-up to whole cents, capped at the remainder."

    Design: Corner/calculations/cancellation_inside_the_notice_window_charges_half_the_quoted_fee
    """
    scenario = setup_active_rider(rider={"household_income_band": "BAND_B"})
    grant = validate_success(
        api.create_grant(
            {
                "grant_name": "Hooves Fund",
                "funder_name": "County",
                "awarded_amount_cents": 100000,
                "period_start": "2026-01-01",
                "period_end": "2026-12-31",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    validate_success(api.confirm_session(session["id"], scenario["instructor_headers"]))

    set_clock("2026-05-10T11:00:00Z")
    cancelled = validate_success(
        api.cancel_session(
            session["id"],
            {"cancellation_reason": "RIDER_REQUEST"},
            scenario["instructor_headers"],
        )
    )
    assert cancelled["cancellation_reason"] == "LATE_RIDER"

    charge = only_charge_for_session(session["id"])
    assert charge["amount_cents"] == 4500
    assert charge["charge_type"] == "LATE_CANCELLATION_FEE"
    assert charge["scholarship_excluded"] is True
    assert charge["balance_due_cents"] == 2700

    allocations = allocations_for_charge(charge["id"])
    assert allocation_total(allocations, "SLIDING_SCALE") == 1800
    assert allocation_total(allocations, "PRIVATE_PAY") == 2700
    assert allocations_of(allocations, "GRANT") == [], (
        "The grant step is skipped entirely for a cancellation fee"
    )
    assert validate_success(api.get_grant(grant["id"], ADMIN))[
        "remaining_amount_cents"
    ] == 100000
    assert read_session(session["id"])["billing_status"] == "CHARGED"


def test_session_create_missing_duration_is_a_validation_error(api):
    """PRD 2.7 rung 6: "The request body is a JSON object and every field the
    endpoint requires is present and not null — otherwise `ERR_VALIDATION` (400).
    Applies to every POST and PATCH."

    Design: Corner/validations/session_create_missing_required_duration_returns_400
    """
    set_clock("2026-05-01T00:00:00Z")
    horse = make_horse()
    instructor = make_instructor()
    rider = make_rider(household_income_band="BAND_B", condition_codes=[])

    response = api.create_session(
        {
            "rider_id": rider["id"],
            "horse_id": horse["id"],
            "instructor_id": instructor["id"],
            "activity_type": "THERAPEUTIC_RIDING",
            "scheduled_start": "2026-05-11T10:00:00Z",
        },
        make_instructor_headers(instructor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_RIDER_NOT_ACTIVE.value


def test_session_create_with_two_unknown_ids_reports_the_rider_first(api):
    """PRD 2.7 rung 13: "Foreign keys carried in the request body resolve,
    checked in this field order: `rider_id`, `horse_id`, `instructor_id`,
    `supervising_instructor_id`, `volunteer_id`, `medical_release_id`,
    `preferred_grant_id`, and then every `goal_id` inside `goal_ratings` in the
    order the client supplied them. An unresolvable `rider_id` yields
    `ERR_RIDER_NOT_FOUND` (404), an unresolvable `horse_id` yields
    `ERR_HORSE_NOT_FOUND` (404), and every other unresolvable body identifier —
    including `supervisor_instructor_id` on instructor registration — yields
    `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/validations/session_create_with_unknown_rider_and_horse_returns_rider_not_found_first
    """
    set_clock("2026-05-01T00:00:00Z")
    instructor = make_instructor()

    response = api.create_session(
        {
            "rider_id": UNKNOWN_UUID_A,
            "horse_id": UNKNOWN_UUID_B,
            "instructor_id": instructor["id"],
            "activity_type": "THERAPEUTIC_RIDING",
            "scheduled_start": "2026-05-11T10:00:00Z",
            "duration_minutes": 60,
        },
        make_instructor_headers(instructor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RIDER_NOT_FOUND.value)


def test_confirm_on_an_unknown_session_path_is_session_not_found(api):
    """PRD 2.7 rung 10: "A `{session_id}` path segment resolves to an existing
    session — otherwise `ERR_SESSION_NOT_FOUND` (404). Applies to every path
    containing `{session_id}`."

    Design: Corner/validations/confirm_on_unknown_session_path_returns_session_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    instructor = make_instructor()

    response = api.confirm_session(
        UNKNOWN_UUID_A, make_instructor_headers(instructor["id"])
    )
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_FOUND.value)


def test_eligibility_reports_release_active_at_booking_and_expired_at_ride(api):
    """PRD 3.6: "`at_booking_instant` and `at_ride_instant` select the instant at
    which `release_status` and `instructor_certification_status` are evaluated —
    the logical clock of the call, or the session's `scheduled_start`
    respectively — and leave the weight axis at `current_declared`."
    PRD 3.2: "a session booked a week before a release expires but scheduled for
    two weeks after it reports an `ACTIVE` release at the booking instant and an
    `EXPIRED` one at the ride instant, is accepted when it is booked, and is then
    refused at completion once the clock has moved."
    PRD 3.6: "what is fixed is that `blocking_gate` is populated exactly when
    `admissible` is false and is null when `admissible` is true."

    Design: Corner/endpoints/eligibility_read_reports_release_active_at_booking_and_expired_at_ride
    """
    scenario = setup_active_rider(clock="2026-05-11T00:00:00Z")
    assert_same_instant(scenario["release"]["expires_at"], "2027-04-01T00:00:00.000Z")

    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2027-05-11T10:00:00Z",
        duration_minutes=60,
    )

    at_booking = validate_success(
        api.get_session_eligibility(
            session["id"],
            scenario["instructor_headers"],
            params={"variant": "at_booking_instant"},
        )
    )
    at_ride = validate_success(
        api.get_session_eligibility(
            session["id"],
            scenario["instructor_headers"],
            params={"variant": "at_ride_instant"},
        )
    )

    assert at_booking["release_status"] == "ACTIVE"
    assert at_ride["release_status"] == "EXPIRED"
    for picture in (at_booking, at_ride):
        assert picture["instructor_certification_status"] == "CURRENT"
        assert picture["quoted_fee_cents"] == 9000
        assert picture["horse_max_load_lb"] == pytest.approx(220.0, abs=0.001)

    assert at_booking["admissible"] is True
    assert at_booking["blocking_gate"] is None
    assert at_ride["admissible"] is False
    assert at_ride["blocking_gate"] is not None


def test_eligibility_reports_both_load_variants(api):
    """PRD 3.3: "The `current_declared` reading uses the rider's `weight_lb`, the
    value the most recent intake update wrote, and this is the reading the
    booking gate uses and the reading the session's own `effective_load_lb` field
    always reports. The `at_assessment` reading instead uses `rider_weight_lb`
    from the rider's newest `RECORDED` assessment — the weight measured in the
    therapy room."
    PRD 3.6: "`current_declared`, the default, and `at_assessment` select which
    rider weight feeds `effective_load_lb`, as described in §3.3, and leave the
    clock axis at the logical clock."

    Design: Corner/endpoints/eligibility_read_reports_load_at_assessment_vs_current_declared
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    validate_success(api.update_rider(scenario["rider_id"], {"weight_lb": 180}, INTAKE))

    current = validate_success(
        api.get_session_eligibility(
            session["id"],
            scenario["instructor_headers"],
            params={"variant": "current_declared"},
        )
    )
    at_assessment = validate_success(
        api.get_session_eligibility(
            session["id"],
            scenario["instructor_headers"],
            params={"variant": "at_assessment"},
        )
    )

    assert current["effective_load_lb"] == pytest.approx(210.0, abs=0.001)
    assert at_assessment["effective_load_lb"] == pytest.approx(180.0, abs=0.001)
    for picture in (current, at_assessment):
        assert picture["horse_max_load_lb"] == pytest.approx(220.0, abs=0.001)
        assert picture["admissible"] is True
