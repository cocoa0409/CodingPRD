"""Optimistic concurrency on the two supersede-capable writes, and the probation threshold.

Two writes in the program are deliberately allowed to supersede work another
writer performed: booking an inspection attempt annuls a still-scheduled one,
and offering a title to a second jurisdiction annuls the pending request against
it. Both therefore carry a mandatory version field, and a writer holding a stale
read is turned away before it can destroy a state it never observed. The last
group here follows the cumulative referral count that moves a licence onto
probation the moment it reaches its threshold.
"""

from test_helpers import (
    CLERK_USER_ID,
    create_fraud_referral_payload,
    create_recognition_request_payload,
    make_state_title_clerk_headers,
    schedule_inspection_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import (
    open_application,
    read_application,
    read_fraud_referral,
    read_inspection,
    read_inspector,
    read_rebuilder,
    read_recognition_request,
    read_station,
    read_title,
    read_vehicle,
    schedule_inspection,
    setup_docs_accepted_application,
    setup_program_actors,
    setup_salvage_titled_vehicle,
    submit_recognition_request,
)

FIRST_SLOT_START = "2026-08-10T09:00:00Z"
FIRST_SLOT_END = "2026-08-10T11:00:00Z"
SECOND_SLOT_START = "2026-08-12T09:00:00Z"
SECOND_SLOT_END = "2026-08-12T11:00:00Z"


def _accepted_application_with_one_booking():
    """An accepted trailer application with one attempt booked, plus the version the
    clerk read at acceptance — which the booking has already superseded."""
    env = setup_docs_accepted_application(body_class="TRAILER")
    stale_version = env["app_version"]
    first_attempt = schedule_inspection(
        env["application_id"],
        env["inspector_id"],
        env["station_id"],
        stale_version,
        FIRST_SLOT_START,
        FIRST_SLOT_END,
    )
    return env, stale_version, first_attempt


def test_stale_application_version_refuses_the_second_booking():
    """Replaying the version read before a booking cannot annul the booking that followed it.

    PRD: "If that value does not equal the application's current `version`, the request is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_application_version_blocks_a_second_booking_then_the_current_version_supersedes
    """
    env, stale_version, first_attempt = _accepted_application_with_one_booking()

    response = api.schedule_inspection(
        env["application_id"],
        schedule_inspection_payload(
            env["inspector_id"],
            env["station_id"],
            stale_version,
            SECOND_SLOT_START,
            SECOND_SLOT_END,
        ),
        make_state_title_clerk_headers(CLERK_USER_ID),
    )
    validate_error(response, "ERR_STALE_APPLICATION_VERSION")

    untouched = read_inspection(first_attempt["id"])
    assert untouched["status"] == "SCHEDULED", (
        f"the existing booking must survive the refused call, got {untouched['status']}"
    )
    assert untouched["scheduled_start_at"] == first_attempt["scheduled_start_at"], (
        f"expected the slot to stay at {first_attempt['scheduled_start_at']}, "
        f"got {untouched['scheduled_start_at']}"
    )

    application = read_application(env["application_id"])
    assert application["version"] > stale_version, (
        f"the first booking already advanced the version past {stale_version}, "
        f"got {application['version']}"
    )
    assert application["status"] == "SCHEDULED", (
        f"expected SCHEDULED after the refused call, got {application['status']}"
    )
    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 1, (
        "the refused call must neither book nor release an interval"
    )


def test_current_application_version_supersedes_the_earlier_booking():
    """Re-reading the version lets the clerk move the appointment, cancelling the first attempt.

    PRD: "The rule exists because a later scheduling call legitimately supersedes a still-`SCHEDULED` attempt by cancelling it with `cancellation_reason` set to `RESCHEDULED`; without the version check, a writer holding a stale read would silently annul a booking made after its own read."

    Design: Corner/cross_cutting_complexity_layers/stale_application_version_blocks_a_second_booking_then_the_current_version_supersedes
    """
    env, stale_version, first_attempt = _accepted_application_with_one_booking()

    fresh_version = read_application(env["application_id"])["version"]
    assert fresh_version > stale_version, (
        f"expected a version above {stale_version}, got {fresh_version}"
    )

    replacement = validate_success(
        api.schedule_inspection(
            env["application_id"],
            schedule_inspection_payload(
                env["inspector_id"],
                env["station_id"],
                fresh_version,
                SECOND_SLOT_START,
                SECOND_SLOT_END,
            ),
            make_state_title_clerk_headers(CLERK_USER_ID),
        ),
        201,
    )
    assert replacement["status"] == "SCHEDULED", (
        f"the replacement attempt lands in SCHEDULED, got {replacement['status']}"
    )
    assert replacement["scheduled_start_at"] != first_attempt["scheduled_start_at"], (
        "the replacement must carry the newly requested slot, "
        f"got {replacement['scheduled_start_at']}"
    )
    assert replacement["attempt_no"] == first_attempt["attempt_no"], (
        "a cancelled attempt consumes no number, so the replacement reuses "
        f"{first_attempt['attempt_no']}, got {replacement['attempt_no']}"
    )

    superseded = read_inspection(first_attempt["id"])
    assert superseded["status"] == "CANCELLED", (
        f"the superseded booking must be CANCELLED, got {superseded['status']}"
    )
    assert superseded["cancellation_reason"] == "RESCHEDULED", (
        f"expected cancellation_reason RESCHEDULED, got {superseded['cancellation_reason']}"
    )

    application = read_application(env["application_id"])
    assert application["status"] == "SCHEDULED", (
        f"the reschedule is a self-loop on SCHEDULED, got {application['status']}"
    )
    assert application["attempts_completed"] == 0, (
        f"no attempt has been conducted yet, got {application['attempts_completed']}"
    )

    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 1, (
        "exactly one live attempt occupies the inspector's calendar"
    )
    assert read_station(env["station_id"])["scheduled_occupancy_count"] == 1, (
        "exactly one live attempt occupies a station bay"
    )


def _salvage_title_offered_to_one_state():
    """A salvage-branded title with one pending recognition request against it, plus
    the version the requester read before that request advanced the title."""
    branded = setup_salvage_titled_vehicle()
    title_id = branded["salvage_title_id"]
    stale_version = read_title(title_id)["version"]
    first_request = submit_recognition_request(
        title_id, stale_version, requesting_state_code="AZ"
    )
    return title_id, stale_version, first_request


def test_stale_title_version_refuses_the_second_recognition_request():
    """A requester holding the pre-request brand snapshot cannot supersede the pending request.

    PRD: "If that value does not equal the title's current `version`, the request is rejected with `ERR_STALE_TITLE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_title_version_blocks_a_recognition_request_then_the_fresh_read_supersedes
    """
    title_id, stale_version, first_request = _salvage_title_offered_to_one_state()

    response = api.create_recognition_request(
        create_recognition_request_payload(
            title_id, stale_version, requesting_state_code="UT"
        ),
        make_state_title_clerk_headers(CLERK_USER_ID),
    )
    validate_error(response, "ERR_STALE_TITLE_VERSION")

    untouched = read_recognition_request(first_request["id"])
    assert untouched["status"] == "PENDING", (
        f"the pending request must survive the refused call, got {untouched['status']}"
    )
    assert untouched["requesting_state_code"] == "AZ", (
        "the refused call must not repoint the pending request, got "
        f"{untouched['requesting_state_code']}"
    )

    title = read_title(title_id)
    assert title["version"] > stale_version, (
        f"the first request already advanced the version past {stale_version}, "
        f"got {title['version']}"
    )
    assert title["status"] == "ACTIVE", (
        f"the title stays ACTIVE while recognition is pending, got {title['status']}"
    )


def test_fresh_title_version_supersedes_the_pending_recognition_request():
    """Re-reading the title lets a second jurisdiction's request supersede the first.

    PRD: "Here too the operation is a supersede: a second recognition request for the same still-`ACTIVE` title moves the earlier pending request to `SUPERSEDED`, so the stale-version check is the only thing preventing a writer holding an outdated brand snapshot from replacing a newer submission."

    Design: Corner/cross_cutting_complexity_layers/stale_title_version_blocks_a_recognition_request_then_the_fresh_read_supersedes
    """
    title_id, stale_version, first_request = _salvage_title_offered_to_one_state()

    fresh_version = read_title(title_id)["version"]
    assert fresh_version > stale_version, (
        f"expected a version above {stale_version}, got {fresh_version}"
    )

    second_request = validate_success(
        api.create_recognition_request(
            create_recognition_request_payload(
                title_id, fresh_version, requesting_state_code="UT"
            ),
            make_state_title_clerk_headers(CLERK_USER_ID),
        ),
        201,
    )
    assert second_request["status"] == "PENDING", (
        f"the accepted request opens in PENDING, got {second_request['status']}"
    )
    assert second_request["requesting_state_code"] == "UT", (
        f"expected the new jurisdiction UT, got {second_request['requesting_state_code']}"
    )

    superseded = read_recognition_request(first_request["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the earlier pending request must move to SUPERSEDED, got {superseded['status']}"
    )

    title = read_title(title_id)
    assert title["recognition_state"] == "RECOGNITION_PENDING", (
        f"expected recognition_state RECOGNITION_PENDING, got {title['recognition_state']}"
    )
    assert title["status"] == "ACTIVE", (
        f"a recognition request never disturbs the title's own status, got {title['status']}"
    )
    assert title["is_current"] is True, (
        "the salvage title remains the vehicle's current record while recognition is pending"
    )

    data, meta = validate_paginated(
        api.list_recognition_requests(
            headers=make_state_title_clerk_headers(CLERK_USER_ID)
        )
    )
    assert meta["total_count"] == 2, (
        f"both the superseded and the pending request are retained, got {meta['total_count']}"
    )
    against_this_title = [row for row in data if row["title_record_id"] == title_id]
    assert {row["status"] for row in against_this_title} == {"SUPERSEDED", "PENDING"}, (
        "expected one superseded and one pending row, got "
        f"{[row['status'] for row in against_this_title]}"
    )


def _one_rebuilder_with_two_open_applications():
    """One licensed rebuilder holding two draft applications, each on its own
    salvage-branded trailer, so referrals can be aimed at the same licence twice."""
    actors = setup_program_actors()
    branded = [
        setup_salvage_titled_vehicle(body_class="TRAILER"),
        setup_salvage_titled_vehicle(body_class="TRAILER"),
    ]
    applications = [
        open_application(
            item["vehicle_id"],
            actors["rebuilder_id"],
            item["salvage_title_id"],
            declared_repair_cost_cents=320_000,
        )
        for item in branded
    ]
    return actors["rebuilder_id"], branded, applications


def _file_referral_against(vehicle_id: str, application_id: str) -> dict:
    return validate_success(
        api.create_fraud_referral(
            create_fraud_referral_payload(
                vehicle_id,
                application_id=application_id,
                referral_type="DOCUMENT_FORGERY",
                evidence_summary="the parts receipts name a supplier that never existed",
            ),
            make_state_title_clerk_headers(CLERK_USER_ID),
        ),
        201,
    )


def test_one_open_referral_leaves_the_licence_below_the_probation_threshold():
    """A single open referral counts against the licence without moving it off ACTIVE.

    PRD: "When `application_id` is supplied, the owning rebuilder's `open_referral_count` rises by one, and reaching 2 moves the licence `ACTIVE → PROBATION`."

    Design: Corner/cross_cutting_complexity_layers/two_open_referrals_trip_the_probation_threshold_at_the_boundary
    """
    rebuilder_id, branded, applications = _one_rebuilder_with_two_open_applications()

    referral = _file_referral_against(branded[0]["vehicle_id"], applications[0]["id"])
    assert referral["status"] == "OPEN", (
        f"a filed referral opens in OPEN, got {referral['status']}"
    )

    rebuilder = read_rebuilder(rebuilder_id)
    assert rebuilder["open_referral_count"] == 1, (
        f"one open referral counts once, got {rebuilder['open_referral_count']}"
    )
    assert rebuilder["license_status"] == "ACTIVE", (
        "one open referral is still below the threshold, got "
        f"{rebuilder['license_status']}"
    )

    assert read_vehicle(branded[0]["vehicle_id"])["fraud_hold"] == "UNDER_REFERRAL", (
        "the referred vehicle carries the referral hold"
    )
    assert read_vehicle(branded[1]["vehicle_id"])["fraud_hold"] == "NONE", (
        "the untouched vehicle carries no hold"
    )


def test_second_open_referral_moves_the_licence_to_probation_on_its_own():
    """The moment the second referral opens, the licence moves to probation with no admin action.

    PRD: "An action of `PROBATION` moves the licence `ACTIVE → PROBATION`; the same move happens on its own whenever `open_referral_count` reaches 2."

    Design: Corner/cross_cutting_complexity_layers/two_open_referrals_trip_the_probation_threshold_at_the_boundary
    """
    rebuilder_id, branded, applications = _one_rebuilder_with_two_open_applications()

    first_referral = _file_referral_against(
        branded[0]["vehicle_id"], applications[0]["id"]
    )
    assert read_rebuilder(rebuilder_id)["license_status"] == "ACTIVE", (
        "the licence must still be ACTIVE one referral short of the threshold"
    )

    second_referral = _file_referral_against(
        branded[1]["vehicle_id"], applications[1]["id"]
    )

    rebuilder = read_rebuilder(rebuilder_id)
    assert rebuilder["open_referral_count"] == 2, (
        f"two open referrals count twice, got {rebuilder['open_referral_count']}"
    )
    assert rebuilder["license_status"] == "PROBATION", (
        "reaching two open referrals moves the licence to PROBATION, got "
        f"{rebuilder['license_status']}"
    )
    assert rebuilder["substantiated_referral_count"] == 0, (
        "neither referral has been resolved, so nothing is substantiated yet, got "
        f"{rebuilder['substantiated_referral_count']}"
    )

    for referral in (first_referral, second_referral):
        current = read_fraud_referral(referral["id"])
        assert current["status"] == "OPEN", (
            f"referral {referral['id']} must stay OPEN, got {current['status']}"
        )

    for item in branded:
        assert read_vehicle(item["vehicle_id"])["fraud_hold"] == "UNDER_REFERRAL", (
            f"vehicle {item['vehicle_id']} carries the referral hold"
        )
