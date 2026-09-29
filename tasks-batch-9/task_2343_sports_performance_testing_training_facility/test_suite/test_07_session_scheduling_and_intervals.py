"""Scheduling a session: interval semantics, the facility cap, and the write envelope."""
import pytest

from test_helpers import (
    assign_coach_payload,
    assign_coach_to_session,
    create_active_contract,
    create_compliant_coach,
    create_group_session_payload,
    fetch_group_session,
    find_assigned_staff_ids,
    register_athlete,
    schedule_group_session,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_SESSION_ID = "6f1c1a52-0000-4000-8000-000000000abc"


def test_01_a_coach_may_work_two_sessions_that_merely_touch_at_the_same_site(api):
    """An eleven o'clock handoff onsite is not a schedule conflict.

    "A staff member may not hold two assignments whose intervals overlap when
    treated as **closed** intervals — endpoints included — which returns
    `ERR_STAFF_SCHEDULE_CONFLICT`; sessions that merely touch at an endpoint while
    sharing the same `site_code` and the same `offsite_location` do not conflict."

    Design: Difficulty/resource_temporal_overlap/staff_closed_interval_touching_allowed_but_cross_site_gap_under_buffer_rejected
    """
    coach, _cert, _headers = create_compliant_coach(full_name="Sol Rivera")
    first = schedule_group_session(start_at="2026-08-10T10:00:00Z",
                                  end_at="2026-08-10T11:00:00Z", station_count=3,
                                  max_athletes=10)
    second = schedule_group_session(start_at="2026-08-10T11:00:00Z",
                                   end_at="2026-08-10T12:00:00Z", station_count=3,
                                   max_athletes=10)

    assigned_first = assign_coach_to_session(first["id"], coach["id"])
    assigned_second = assign_coach_to_session(second["id"], coach["id"])

    assert assigned_first["compliant_coach_count"] == 1
    assert assigned_second["compliant_coach_count"] == 1
    assert assigned_second["staffing_status"] == "STAFFED"
    assert find_assigned_staff_ids(fetch_group_session(second["id"])) == [coach["id"]]


def test_02_a_twenty_minute_gap_across_a_location_change_is_refused(
        api, performance_director_headers):
    """Crossing to an offsite venue needs half an hour; twenty minutes is not enough.

    "And consecutive assignments at *different* locations — a differing `site_code`,
    or both `OFFSITE` with differing `offsite_location` — require a gap of at least
    30 minutes between the earlier session's `end_at` and the later session's
    `start_at`, failing which the assignment is refused with
    `ERR_TRAVEL_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/staff_closed_interval_touching_allowed_but_cross_site_gap_under_buffer_rejected
    """
    coach, _cert, _headers = create_compliant_coach(full_name="Sol Rivera")
    onsite = schedule_group_session(start_at="2026-08-10T11:00:00Z",
                                   end_at="2026-08-10T12:00:00Z", station_count=3,
                                   max_athletes=10)
    assign_coach_to_session(onsite["id"], coach["id"])

    too_soon = schedule_group_session(
        start_at="2026-08-10T12:20:00Z", end_at="2026-08-10T13:20:00Z",
        site_code="OFFSITE", offsite_location="Eastside Club", station_count=3,
        max_athletes=10)
    far_enough = schedule_group_session(
        start_at="2026-08-10T12:30:00Z", end_at="2026-08-10T13:30:00Z",
        site_code="OFFSITE", offsite_location="Eastside Club", station_count=3,
        max_athletes=10)

    validate_error(
        api.assign_coach(too_soon["id"],
                         assign_coach_payload(coach["id"], too_soon["version"]),
                         performance_director_headers),
        "ERR_TRAVEL_BUFFER_VIOLATION", expected_status=409)
    assert find_assigned_staff_ids(fetch_group_session(too_soon["id"])) == []

    accepted = validate_success(api.assign_coach(
        far_enough["id"], assign_coach_payload(coach["id"], far_enough["version"]),
        performance_director_headers))
    assert accepted["compliant_coach_count"] == 1
    assert accepted["staffing_status"] == "STAFFED"


def test_03_a_fourth_overlapping_onsite_session_exceeds_the_facility_cap(
        api, performance_director_headers):
    """Three onsite sessions saturate the floor, and an offsite one is not counted.

    "At most three non-canceled `ONSITE` sessions may have overlapping half-open
    intervals — the cap is aggregate across every contract and every athlete, not
    per contract — and a fourth overlapping onsite session is refused with
    `ERR_SITE_CONCURRENCY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/aggregate_onsite_concurrency_cap_counts_overlaps_across_all_sessions
    """
    for _ in range(3):
        schedule_group_session(start_at="2026-08-14T10:00:00Z",
                              end_at="2026-08-14T11:00:00Z", station_count=3,
                              max_athletes=10)

    validate_error(
        api.create_group_session(create_group_session_payload(
            start_at="2026-08-14T10:30:00Z", end_at="2026-08-14T11:30:00Z",
            site_code="ONSITE", station_count=3, max_athletes=10),
            performance_director_headers),
        "ERR_SITE_CONCURRENCY_EXCEEDED", expected_status=409)

    offsite = validate_success(api.create_group_session(create_group_session_payload(
        start_at="2026-08-14T10:30:00Z", end_at="2026-08-14T11:30:00Z",
        site_code="OFFSITE", offsite_location="Westview Club", station_count=3,
        max_athletes=10), performance_director_headers), expected_status=201)

    assert offsite["site_code"] == "OFFSITE"
    assert offsite["session_status"] == "SCHEDULED"
    assert offsite["staffing_status"] == "STAFF_PENDING"

    rows, _meta = validate_paginated(api.list_group_sessions(
        performance_director_headers, params={"limit": 100}))
    assert len(rows) == 4, "the refused fourth onsite session was never created"


def test_04_cancelling_one_of_the_overlapping_sessions_frees_the_floor_again(
        api, performance_director_headers):
    """The cap counts non-canceled sessions, so a cancellation restores capacity.

    "At most three non-canceled `ONSITE` sessions may have overlapping half-open
    intervals — the cap is aggregate across every contract and every athlete, not
    per contract — and a fourth overlapping onsite session is refused with
    `ERR_SITE_CONCURRENCY_EXCEEDED`."

    "The `PerformanceDirector` or `FrontDesk` cancels a session from either
    `SCHEDULED` or `ROSTER_LOCKED`, recording a free-text `cancel_reason` on the
    session."

    Design: Difficulty/resource_temporal_overlap/aggregate_onsite_concurrency_cap_counts_overlaps_across_all_sessions
    """
    saturating = [schedule_group_session(start_at="2026-08-14T10:00:00Z",
                                        end_at="2026-08-14T11:00:00Z",
                                        station_count=3, max_athletes=10)
                  for _ in range(3)]
    validate_error(
        api.create_group_session(create_group_session_payload(
            start_at="2026-08-14T10:30:00Z", end_at="2026-08-14T11:30:00Z",
            station_count=3, max_athletes=10), performance_director_headers),
        "ERR_SITE_CONCURRENCY_EXCEEDED", expected_status=409)

    canceled = validate_success(api.cancel_group_session(
        saturating[2]["id"], {"cancel_reason": "Court resurfacing"},
        performance_director_headers))
    assert canceled["session_status"] == "CANCELED"
    assert canceled["cancel_reason"] == "Court resurfacing"

    replacement = validate_success(api.create_group_session(
        create_group_session_payload(start_at="2026-08-14T10:30:00Z",
                                    end_at="2026-08-14T11:30:00Z", station_count=3,
                                    max_athletes=10),
        performance_director_headers), expected_status=201)
    assert replacement["session_status"] == "SCHEDULED"
    assert fetch_group_session(saturating[0]["id"])["session_status"] == "SCHEDULED"
    assert fetch_group_session(saturating[1]["id"])["session_status"] == "SCHEDULED"


def test_05_the_offsite_venue_label_is_conditionally_required(
        api, performance_director_headers):
    """An offsite session must name its venue, and an onsite session must not.

    "Two optional fields complete it: `offsite_location`, the travel-training venue
    label, which is **required** and non-empty when `site_code` is `OFFSITE` and must
    be absent or null when `site_code` is `ONSITE`; and `team_contract_id`, set when
    the session is delivered under a school or club contract."

    Design: Corner/validations/offsite_session_requires_offsite_location_and_onsite_forbids_it
    """
    validate_error(
        api.create_group_session(create_group_session_payload(
            start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
            site_code="OFFSITE", station_count=3, max_athletes=8),
            performance_director_headers),
        "ERR_INVALID_REQUEST", expected_status=422)

    validate_error(
        api.create_group_session(create_group_session_payload(
            start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
            site_code="ONSITE", station_count=3, max_athletes=8,
            offsite_location="Northside High Gym"), performance_director_headers),
        "ERR_INVALID_REQUEST", expected_status=422)

    _rows, meta = validate_paginated(api.list_group_sessions(
        performance_director_headers))
    assert meta["total_count"] == 0, "neither refused call created a session"


def test_06_unknown_enums_reversed_intervals_and_out_of_range_counts_are_refused(
        api, performance_director_headers):
    """The schema tier rejects the site code, the interval order and the station count.

    "The `PerformanceDirector` or a `FrontDesk` operator schedules a **group
    session** by giving its `start_at` and `end_at` as ISO 8601 UTC instants with the
    end strictly after the start, a `site_code` of `ONSITE` or `OFFSITE`, a
    `station_count` from 1 through 12 describing how many equipment stations the
    rotation uses, a `phase_focus` of `GENERAL_PREP`, `SPECIFIC_PREP`, `COMPETITION`
    or `TRANSITION`, and a `max_athletes` roster capacity from 1 through 40."

    Design: Corner/entities/group_session_invalid_enum_and_reversed_interval_rejected
    """
    bad_payloads = [
        create_group_session_payload(start_at="2026-08-20T16:00:00Z",
                                    end_at="2026-08-20T17:00:00Z",
                                    site_code="ROOFTOP", station_count=4),
        create_group_session_payload(start_at="2026-08-20T17:00:00Z",
                                    end_at="2026-08-20T16:00:00Z", station_count=4),
        create_group_session_payload(start_at="2026-08-20T16:00:00Z",
                                    end_at="2026-08-20T17:00:00Z", station_count=13),
    ]
    for payload in bad_payloads:
        validate_error(api.create_group_session(payload, performance_director_headers),
                       "ERR_INVALID_REQUEST", expected_status=422)

    _rows, meta = validate_paginated(api.list_group_sessions(
        performance_director_headers))
    assert meta["total_count"] == 0


def test_07_an_unknown_session_id_returns_the_session_specific_not_found(
        api, performance_director_headers):
    """Each path identifier carries its own dedicated not-found code.

    "Each identifier has its own dedicated code: `athlete_id` yields
    `ERR_ATHLETE_NOT_FOUND`, `injury_record_id` yields `ERR_INJURY_RECORD_NOT_FOUND`,
    `test_session_id` yields `ERR_TEST_SESSION_NOT_FOUND`, `training_program_id`
    yields `ERR_TRAINING_PROGRAM_NOT_FOUND`, `program_block_id` yields
    `ERR_PROGRAM_BLOCK_NOT_FOUND`, `group_session_id` yields
    `ERR_GROUP_SESSION_NOT_FOUND`, `enrollment_id` yields
    `ERR_ENROLLMENT_NOT_FOUND`, `staff_member_id` yields
    `ERR_STAFF_MEMBER_NOT_FOUND`, `certification_id` yields
    `ERR_CERTIFICATION_NOT_FOUND`, `membership_package_id` yields
    `ERR_MEMBERSHIP_PACKAGE_NOT_FOUND`, `team_contract_id` yields
    `ERR_TEAM_CONTRACT_NOT_FOUND`, `rts_plan_id` yields `ERR_RTS_PLAN_NOT_FOUND`, and
    `clearance_document_id` yields `ERR_CLEARANCE_DOCUMENT_NOT_FOUND`."

    Design: Corner/entities/group_session_not_found_returns_group_session_not_found
    """
    error = validate_error(
        api.get_group_session(UNKNOWN_SESSION_ID, performance_director_headers),
        "ERR_GROUP_SESSION_NOT_FOUND", expected_status=404)

    assert error["error_id"] == "ERR_GROUP_SESSION_NOT_FOUND"
    assert error["message"].strip() != ""


def test_08_the_version_counter_advances_by_exactly_one_per_write(
        api, performance_director_headers):
    """Creation, a coach assignment and a cancellation walk the version 1, 2, 3.

    "**`version`** (integer): a monotonically increasing counter that advances by one
    on every mutation of the resource. No resource in this system omits `updated_at`
    or `version`."

    Design: Corner/cross_cutting_layers/entity_version_increments_by_one_on_every_mutation
    """
    coach, _cert, _headers = create_compliant_coach(
        full_name="Coach Versioning", role_title="PERFORMANCE_COACH")

    session = schedule_group_session(start_at="2026-08-25T16:00:00Z",
                                    end_at="2026-08-25T17:00:00Z", station_count=3,
                                    max_athletes=8)
    assert session["version"] == 1

    assigned = validate_success(api.assign_coach(
        session["id"], assign_coach_payload(coach["id"], 1),
        performance_director_headers))
    assert assigned["version"] == 2
    assert assigned["staffing_status"] == "STAFFED", \
        "one write recomputed the staffing fields and still consumed a single version"

    canceled = validate_success(api.cancel_group_session(
        session["id"], {"cancel_reason": "Version probe"},
        performance_director_headers))
    assert canceled["version"] == 3
    assert fetch_group_session(session["id"])["version"] == 3


def test_09_a_superseded_session_version_blocks_a_second_coach_assignment(
        api, performance_director_headers):
    """The first assignment moves the version on, so the original view is stale.

    "If that value does not equal the session's current `version`, the assignment is
    rejected with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_layers/coach_assignment_with_stale_session_version_returns_stale_version
    """
    alpha, _cert_a, _headers_a = create_compliant_coach(
        full_name="Coach Alpha", role_title="PERFORMANCE_COACH")
    beta, _cert_b, _headers_b = create_compliant_coach(
        full_name="Coach Beta", role_title="PERFORMANCE_COACH")
    session = schedule_group_session(start_at="2026-08-25T16:00:00Z",
                                    end_at="2026-08-25T17:00:00Z", station_count=6,
                                    max_athletes=20)
    stale_version = session["version"]

    fresh = validate_success(api.assign_coach(
        session["id"], assign_coach_payload(alpha["id"], stale_version),
        performance_director_headers))
    assert fresh["version"] == stale_version + 1

    validate_error(
        api.assign_coach(session["id"],
                         assign_coach_payload(beta["id"], stale_version),
                         performance_director_headers),
        "ERR_STALE_VERSION", expected_status=412)

    unchanged = fetch_group_session(session["id"])
    assert find_assigned_staff_ids(unchanged) == [alpha["id"]]
    assert unchanged["compliant_coach_count"] == 1
    assert unchanged["version"] == fresh["version"]

    retried = validate_success(api.assign_coach(
        session["id"], assign_coach_payload(beta["id"], fresh["version"]),
        performance_director_headers))
    assert retried["compliant_coach_count"] == 2
    assert retried["version"] == fresh["version"] + 1
    assert retried["staffing_status"] == "STAFFED"


def test_10_both_listed_roles_can_schedule_sessions_and_link_contract_athletes(
        api, performance_director_headers, front_desk_headers):
    """A shared operation is open to every role its endpoint lists.

    "Each endpoint in §4 lists the roles permitted to invoke it; a caller whose role
    is absent from that list is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/performance_director_and_front_desk_share_the_session_creation_operation
    """
    athlete = register_athlete(full_name="Shared Op Athlete",
                              date_of_birth="2009-02-02")
    contract = create_active_contract(organization_name="Shared Op Club",
                                    organization_type="CLUB", contracted_sessions=4,
                                    base_rate_cents=30000, offsite_allowance=1,
                                    term_start="2026-08-01", term_end="2027-05-31")

    by_director = validate_success(api.create_group_session(
        create_group_session_payload(start_at="2026-08-25T16:00:00Z",
                                    end_at="2026-08-25T17:00:00Z", station_count=3,
                                    max_athletes=8), performance_director_headers),
        expected_status=201)
    by_front_desk = validate_success(api.create_group_session(
        create_group_session_payload(start_at="2026-08-26T16:00:00Z",
                                    end_at="2026-08-26T17:00:00Z", station_count=3,
                                    max_athletes=8), front_desk_headers),
        expected_status=201)

    for created in (by_director, by_front_desk):
        assert created["session_status"] == "SCHEDULED"
        assert created["staffing_status"] == "STAFF_PENDING"

    linked = validate_success(api.link_contract_athlete(
        contract["id"], {"athlete_id": athlete["id"]}, front_desk_headers))
    assert linked["team_contract_id"] == contract["id"]
