"""Coaching credentials: review, renewal, and the lapse cascade down to station numbers."""
import pytest

from test_helpers import (
    advance_clock,
    assign_coach_payload,
    assert_staff_member,
    create_compliant_coach,
    create_staff_member_payload,
    fetch_certification,
    fetch_enrollment,
    fetch_group_session,
    fetch_staff_member,
    find_assigned_staff_ids,
    schedule_group_session,
    setup_lapsing_coach_on_future_session,
    setup_session_with_coach,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_01_a_new_staff_member_round_trips_with_empty_credential_counters(
        api, performance_director_headers):
    """Registration seeds a compliant staff member holding no certifications.

    "A newly registered staff member holds no certifications and their
    `credential_status` is `COMPLIANT`, with `valid_certification_count`,
    `lapsed_certification_count` and `ceu_credits_earned_total` at 0 and
    `last_credential_review_at` null."

    Design: Corner/endpoints/staff_member_create_then_read_then_list_round_trip
    """
    created = validate_success(api.create_staff_member(create_staff_member_payload(
        full_name="Coach Roundtrip", role_title="HEAD_COACH",
        liability_insurance_expires_on="2027-06-30"), performance_director_headers),
        expected_status=201)

    assert_staff_member(created)
    assert created["full_name"] == "Coach Roundtrip"
    assert created["role_title"] == "HEAD_COACH"
    assert created["liability_insurance_expires_on"] == "2027-06-30"
    assert created["credential_status"] == "COMPLIANT"
    assert created["valid_certification_count"] == 0
    assert created["lapsed_certification_count"] == 0
    assert created["ceu_credits_earned_total"] == 0
    assert created["last_credential_review_at"] is None
    assert created["version"] == 1

    fetched = validate_success(api.get_staff_member(created["id"],
                                                   performance_director_headers))
    assert fetched == created

    rows, meta = validate_paginated(api.list_staff_members(performance_director_headers))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == created["id"]


def test_02_renewal_is_refused_while_the_ceu_requirement_is_unmet(
        api, performance_director_headers):
    """Four of the six required credits is not enough to renew.

    "Renewal is accepted from `VALID`, `EXPIRING` or `LAPSED`, and in every case
    requires `ceu_credits_earned` to have reached at least `ceu_credits_required` at
    the moment of renewal; falling short returns `ERR_CEU_REQUIREMENT_NOT_MET`."

    Design: Corner/endpoints/certification_renew_requires_ceu_credits_earned_to_reach_requirement
    """
    staff, certification, _coach = create_compliant_coach(
        full_name="Coach Renewal", cert_code="CSCS", issued_on="2023-08-15",
        cert_expires_on="2026-08-15", ceu_credits_required=6)

    reviewed = validate_success(api.credential_review(staff["id"],
                                                     performance_director_headers))
    assert fetch_certification(certification["id"])["status"] == "EXPIRING"
    assert reviewed["credential_status"] == "EXPIRING"

    logged = validate_success(api.log_ceu_credits(
        certification["id"], {"credits": 4}, performance_director_headers))
    assert logged["ceu_credits_earned"] == 4

    validate_error(
        api.renew_certification(certification["id"],
                                {"new_expires_on": "2029-08-15"},
                                performance_director_headers),
        "ERR_CEU_REQUIREMENT_NOT_MET", expected_status=422)

    reread = fetch_certification(certification["id"])
    assert reread["status"] == "EXPIRING"
    assert reread["expires_on"] == "2026-08-15"
    assert reread["renewal_count"] == 0


def test_03_renewal_succeeds_once_the_credits_reach_the_requirement(
        api, performance_director_headers):
    """A successful renewal moves the expiry out, counts the renewal and zeroes the credits.

    "On success `expires_on` is replaced by `new_expires_on`, `renewal_count` rises
    by one, `ceu_credits_earned` is reset to 0 and the owner's
    `ceu_credits_earned_total` is re-derived as the sum across their certifications,
    and `credential_status` is recomputed on exactly the same rules the review uses
    — so a formerly `LAPSED` staff member returns to `COMPLIANT` provided no other
    certification is `LAPSED` and their insurance is still live."

    Design: Corner/endpoints/certification_renew_requires_ceu_credits_earned_to_reach_requirement
    """
    staff, certification, _coach = create_compliant_coach(
        full_name="Coach Renewal", cert_code="CSCS", issued_on="2023-08-15",
        cert_expires_on="2026-08-15", ceu_credits_required=6)
    validate_success(api.credential_review(staff["id"], performance_director_headers))
    validate_success(api.log_ceu_credits(certification["id"], {"credits": 4},
                                         performance_director_headers))
    topped_up = validate_success(api.log_ceu_credits(
        certification["id"], {"credits": 2}, performance_director_headers))
    assert topped_up["ceu_credits_earned"] == 6

    renewed = validate_success(api.renew_certification(
        certification["id"], {"new_expires_on": "2029-08-15"},
        performance_director_headers))

    assert renewed["status"] == "VALID"
    assert renewed["expires_on"] == "2029-08-15"
    assert renewed["renewal_count"] == 1
    assert renewed["ceu_credits_earned"] == 0

    reread_staff = fetch_staff_member(staff["id"])
    assert reread_staff["credential_status"] == "COMPLIANT"
    assert reread_staff["valid_certification_count"] == 1
    assert reread_staff["lapsed_certification_count"] == 0
    assert reread_staff["ceu_credits_earned_total"] == 0, \
        "the total is re-derived from the certifications, whose credits were just zeroed"


def test_04_credential_review_is_what_lapses_a_certification_against_the_clock(
        api, performance_director_headers):
    """Only the review reconciles a certification with the logical clock.

    "The review walks the staff member's certifications in ascending `created_at`
    order and re-derives each one: an `expires_on` earlier than today makes it
    `LAPSED`; an `expires_on` from today through today plus 30 days inclusive makes
    it `EXPIRING`; anything further out makes it `VALID`."

    Design: Difficulty/transitive_cascade/credential_review_lapse_cascades_five_hops_to_cleared_station_numbers
    """
    staff, certification, _coach, session, _athlete, _enrollment = (
        setup_lapsing_coach_on_future_session(
            cert_expires_on="2026-08-15", review_clock="2026-09-01T00:00:00Z",
            session_start_at="2026-09-20T10:00:00Z",
            session_end_at="2026-09-20T11:00:00Z"))
    assert session["session_status"] == "ROSTER_LOCKED"
    assert fetch_certification(certification["id"])["status"] == "VALID", \
        "advancing the clock alone never lapses anything"

    reviewed = validate_success(api.credential_review(staff["id"],
                                                     performance_director_headers))

    assert fetch_certification(certification["id"])["status"] == "LAPSED"
    assert reviewed["credential_status"] == "LAPSED"
    assert reviewed["lapsed_certification_count"] == 1
    assert reviewed["valid_certification_count"] == 0
    assert reviewed["last_credential_review_at"] is not None


def test_05_the_lapse_cascade_unstaffs_the_session_and_clears_the_stations(
        api, performance_director_headers):
    """The cascade runs staff member to session to staffing state to station numbers.

    "Because `staffing_status` became `UNDERSTAFFED`, each affected session that was
    `ROSTER_LOCKED` reverts to `SCHEDULED`, and every `RESERVED` enrollment on it has
    its `station_number` cleared to null."

    Design: Difficulty/transitive_cascade/credential_review_lapse_cascades_five_hops_to_cleared_station_numbers
    """
    staff, _certification, _coach, session, _athlete, enrollment = (
        setup_lapsing_coach_on_future_session(
            cert_expires_on="2026-08-15", review_clock="2026-09-01T00:00:00Z",
            session_start_at="2026-09-20T10:00:00Z",
            session_end_at="2026-09-20T11:00:00Z"))
    assert enrollment["station_number"] == 1

    validate_success(api.credential_review(staff["id"], performance_director_headers))

    reread_session = fetch_group_session(session["id"])
    assert find_assigned_staff_ids(reread_session) == []
    assert reread_session["compliant_coach_count"] == 0
    assert reread_session["required_coach_count"] == 1
    assert reread_session["staffing_status"] == "UNDERSTAFFED"
    assert reread_session["session_status"] == "SCHEDULED"

    reread_enrollment = fetch_enrollment(enrollment["id"])
    assert reread_enrollment["status"] == "RESERVED"
    assert reread_enrollment["station_number"] is None


def test_06_a_lapsed_coach_stops_counting_as_compliant_on_a_past_session(
        api, performance_director_headers):
    """A session that has already begun keeps the assignment but loses the compliant count.

    "`compliant_coach_count` counts the rows of `assigned_staff` whose staff
    member's `credential_status` is anything other than `LAPSED`."

    Design: Difficulty/priority_pair_validation_conflict/staff_credential_error_outranks_staff_schedule_conflict_on_coach_assignment
    """
    staff, certification, _coach = create_compliant_coach(
        full_name="Yusuf Demir", cert_code="CSCS", cert_expires_on="2026-08-15")
    session_a = setup_session_with_coach(
        staff["id"], start_at="2026-08-25T10:00:00Z", end_at="2026-08-25T11:00:00Z",
        station_count=3, max_athletes=10)
    assert session_a["compliant_coach_count"] == 1

    advance_clock("2026-09-01T00:00:00Z")
    validate_success(api.credential_review(staff["id"], performance_director_headers))

    assert fetch_certification(certification["id"])["status"] == "LAPSED"
    assert fetch_staff_member(staff["id"])["credential_status"] == "LAPSED"
    reread = fetch_group_session(session_a["id"])
    assert reread["compliant_coach_count"] == 0
    assert reread["session_status"] == "SCHEDULED"


def test_07_the_credential_defect_outranks_the_schedule_conflict_on_an_assignment(
        api, performance_director_headers):
    """An overlapping assignment by a lapsed coach reports the credential failure.

    "On a coach assignment that credential defect is reported **before** any
    scheduling-overlap or travel-buffer evaluation on the same request."

    Design: Difficulty/priority_pair_validation_conflict/staff_credential_error_outranks_staff_schedule_conflict_on_coach_assignment
    """
    staff, _certification, _coach = create_compliant_coach(
        full_name="Yusuf Demir", cert_code="CSCS", cert_expires_on="2026-08-15")
    setup_session_with_coach(
        staff["id"], start_at="2026-08-25T10:00:00Z", end_at="2026-08-25T11:00:00Z",
        station_count=3, max_athletes=10)
    advance_clock("2026-09-01T00:00:00Z")
    validate_success(api.credential_review(staff["id"], performance_director_headers))

    session_b = schedule_group_session(
        start_at="2026-08-25T10:30:00Z", end_at="2026-08-25T11:30:00Z",
        station_count=3, max_athletes=10)
    version_before = session_b["version"]

    error = validate_error(
        api.assign_coach(session_b["id"],
                         assign_coach_payload(staff["id"], version_before),
                         performance_director_headers),
        "ERR_STAFF_CREDENTIAL_LAPSED", expected_status=422)
    assert error["error_id"] != "ERR_STAFF_SCHEDULE_CONFLICT", \
        "the overlapping interval must not be reported ahead of the credential defect"

    reread = fetch_group_session(session_b["id"])
    assert find_assigned_staff_ids(reread) == []
    assert reread["staffing_status"] == "STAFF_PENDING"
    assert reread["version"] == version_before, "a refused assignment mutates nothing"
