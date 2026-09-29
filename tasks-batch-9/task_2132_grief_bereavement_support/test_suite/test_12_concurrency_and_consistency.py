"""Stale-parent protection on the three version-guarded writes, version
monotonicity and immediate visibility of derived counters."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    api_client,
    assert_cohort_seat_pool,
    assert_grant_money_pool,
    assign_counseling_referral,
    cohort_version,
    confirm_enrollment,
    create_assessed_participant,
    create_cohort,
    create_counseling_referral,
    create_counselor,
    create_funding_allocation,
    create_grant_award,
    create_meeting_space,
    create_open_cohort,
    create_participant,
    create_remembrance_event,
    enroll,
    read_cohort,
    read_counseling_referral,
    read_counselor,
    read_enrollment,
    read_grant_award,
    read_participant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_stale_cohort_version_is_refused_and_the_refreshed_one_succeeds():
    """PRD 2.6: "Creating an enrollment requires a non-optional
    `expected_cohort_version` field carrying the `version` of the target cohort as
    the client last observed it. If that value differs from the cohort's current
    `version`, the create is rejected with `ERR_STALE_COHORT_VERSION` and HTTP 412
    — the seat pool the client reasoned about (`seats_open`, `seats_held`,
    `seats_filled`) has moved, so the hold is refused rather than silently drawn
    from a pool the client never saw."

    Design: Corner/cross_cutting_layers/occ_stale_cohort_version_on_enrollment_create_returns_precondition_failed
    """
    set_clock()
    space, cohort = create_open_cohort(name="OCC Group", seats_total=4,
                                       min_viable_enrollment=1)
    observed_version = cohort["version"]
    first = create_assessed_participant(loss_type=cohort["loss_type"])
    second = create_assessed_participant(loss_type=cohort["loss_type"])
    enroll(first["id"], cohort["id"], observed_version)

    validate_error(
        api_client.create_enrollment(
            {"participant_id": second["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": observed_version}, IC),
        ApiErrorId.ERR_STALE_COHORT_VERSION.value, 412)

    current_version = cohort_version(cohort["id"])
    retried = validate_success(
        api_client.create_enrollment(
            {"participant_id": second["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": current_version}, IC), 201)
    assert retried["status"] == "HELD"

    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_held"] == 2
    assert refreshed["seats_open"] == 2
    assert_cohort_seat_pool(refreshed)


def test_a_stale_counselor_version_is_refused_on_assignment():
    """PRD 2.6: "Assigning a counselling referral requires a non-optional
    `expected_counselor_version` field carrying the `version` of the named
    counsellor as the client last observed it. A mismatch with the counsellor's
    current `version` is rejected with `ERR_STALE_COUNSELOR_VERSION` and HTTP 412,
    because the caseload and weekly-minute figures the client used to pick that
    counsellor are no longer current."

    Design: Corner/cross_cutting_layers/occ_stale_counselor_version_on_assign_returns_precondition_failed
    """
    set_clock()
    counselor = create_counselor(full_name="Dr Wren Adisa",
                                 license_type="PSYCHOLOGIST",
                                 specialties=["SUDDEN_DEATH"], caseload_cap=5,
                                 weekly_capacity_minutes=600)
    observed_version = counselor["version"]

    first_participant = create_participant(loss_type="SUDDEN_DEATH")
    second_participant = create_participant(loss_type="SUDDEN_DEATH")
    first = create_counseling_referral(first_participant["id"],
                                       requested_minutes_per_week=60)
    second = create_counseling_referral(second_participant["id"],
                                        requested_minutes_per_week=60)
    assign_counseling_referral(first["id"], counselor["id"], observed_version)

    validate_error(
        api_client.assign_counseling_referral(
            second["id"],
            {"counselor_id": counselor["id"],
             "expected_counselor_version": observed_version}, IC),
        ApiErrorId.ERR_STALE_COUNSELOR_VERSION.value, 412)

    refreshed = read_counselor(counselor["id"])
    assert refreshed["active_caseload"] == 1
    assert refreshed["committed_minutes"] == 60
    assert read_counseling_referral(second["id"])["status"] == "WAITLISTED"
    assert read_counseling_referral(first["id"])["status"] == "ASSIGNED"


def test_a_stale_grant_version_is_refused_on_allocation_creation():
    """PRD 2.6: "Creating a funding allocation requires a non-optional
    `expected_grant_award_version` field carrying the `version` of the target grant
    award as the client last observed it. A mismatch with the award's current
    `version` is rejected with `ERR_STALE_GRANT_VERSION` and HTTP 412, because the
    `available_cents` figure the commitment was sized against has moved."

    Design: Corner/cross_cutting_layers/occ_stale_grant_version_on_allocation_create_returns_precondition_failed
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(awarded_cents=500_000,
                               allowed_categories=["REMEMBRANCE_EVENT"])
    observed_version = award["version"]
    first_event = create_remembrance_event(space["id"], title="OCC Vigil One",
                                           event_date="2026-10-05",
                                           direct_cost_cents=10_220)
    second_event = create_remembrance_event(space["id"], title="OCC Vigil Two",
                                            event_date="2026-10-06",
                                            direct_cost_cents=10_220)
    create_funding_allocation(award["id"], "REMEMBRANCE_EVENT",
                              event_id=first_event["id"],
                              expected_grant_award_version=observed_version)

    validate_error(
        api_client.create_funding_allocation(
            {"grant_award_id": award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": second_event["id"],
             "expected_grant_award_version": observed_version}, PD),
        ApiErrorId.ERR_STALE_GRANT_VERSION.value, 412)

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 11_446
    assert refreshed["available_cents"] == 488_554
    assert_grant_money_pool(refreshed)
    rows, meta = validate_paginated(
        api_client.list_funding_allocations(
            PD, params={"grant_award_id": award["id"]}))
    assert meta["total_count"] == 1


def test_cohort_version_rises_by_exactly_one_on_every_seat_mutation():
    """PRD 2.4: "Most resources additionally carry `updated_at`, in the same ISO
    8601 UTC format with three fractional digits, and `version`, an integer that
    begins at 1 when the record is created and increases by exactly one on every
    mutation of that record."
    PRD 3.4: "One unit moves out of `seats_open` and into `seats_held`, the
    cohort's `version` increases by one, and if this is the participant's first
    live enrollment their `service_status` advances `ASSESSED → ACTIVE`."

    Design: Corner/cross_cutting_layers/cohort_version_increments_by_one_on_every_seat_mutation
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    participant = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")

    cohort = create_cohort(space["id"], name="Version Group", seats_total=4,
                           min_viable_enrollment=1)
    assert cohort["version"] == 1

    opened = validate_success(api_client.open_cohort_enrollment(cohort["id"], PD))
    assert opened["version"] == 2

    enrollment = enroll(participant["id"], cohort["id"], opened["version"])
    assert cohort_version(cohort["id"]) == 3

    confirm_enrollment(enrollment["id"])
    assert cohort_version(cohort["id"]) == 4

    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_filled"] == 1
    assert refreshed["seats_held"] == 0
    assert refreshed["seats_open"] == 3
    assert_cohort_seat_pool(refreshed)


def test_derived_counters_are_visible_in_the_write_that_changed_them():
    """PRD 2.9: "Third, derived counters are recomputed as part of the same write,
    never lazily: `seats_open`, `seats_held`, `seats_filled`, `active_caseload`,
    `committed_minutes`, `active_match_count`, `has_active_companion`,
    `invitations_sent`, `invitations_accepted`, `confirmed_headcount`,
    `committed_cents`, `spent_cents` and `available_cents` are all expected to be
    correct in the very response that caused them to change."
    PRD 3.4: "A successful placement creates an enrollment in status `HELD` and
    answers with HTTP 201. Its `held_until` is stamped seventy-two hours after the
    record's `created_at` — a three-day window in which the family must confirm."

    Design: Corner/consistency_model/immediate_consistency_seat_counters_visible_in_the_same_response
    """
    set_clock()
    space, cohort = create_open_cohort(name="Immediate Group", seats_total=4,
                                       min_viable_enrollment=1)
    participant = create_assessed_participant(loss_type=cohort["loss_type"])

    enrollment = validate_success(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort["version"]}, IC), 201)
    assert enrollment["status"] == "HELD"
    assert enrollment["held_until"] == "2026-09-04T00:00:00.000Z"

    refreshed_cohort = read_cohort(cohort["id"])
    assert refreshed_cohort["seats_held"] == 1
    assert refreshed_cohort["seats_open"] == 3
    assert_cohort_seat_pool(refreshed_cohort)

    assert read_participant(participant["id"])["service_status"] == "ACTIVE"
    rows, meta = validate_paginated(
        api_client.list_enrollments(IC, params={"participant_id": participant["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == enrollment["id"]
