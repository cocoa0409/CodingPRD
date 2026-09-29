"""The three funding buckets, the two fiscal refusals, and the waitlist promotion."""
import pytest

from test_helpers import (
    advance_clock,
    create_active_contract,
    create_compliant_coach,
    create_enrollment_payload,
    enroll_athlete,
    fetch_athlete,
    fetch_enrollment,
    fetch_group_session,
    fetch_membership_package,
    fetch_team_contract,
    link_athlete_to_contract,
    register_athlete,
    run_movement_screen,
    schedule_group_session,
    sell_package,
    setup_cleared_athlete,
    setup_restricted_athlete,
    setup_session_with_coach,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ATHLETE_ID = "9d3e1a52-0000-4000-8000-0000000000aa"


def test_01_an_omitted_funding_preference_is_stored_as_any(api, front_desk_headers):
    """Neither optional field is supplied, so the declared defaults apply.

    "`funding_preference` is `ANY`, `PACKAGE_ONLY` or `DROP_IN_OK` and defaults to
    `ANY`; `PACKAGE_ONLY` forbids the drop-in bucket entirely."

    "`request_waitlist` is a boolean defaulting to false; when true, a capacity or
    coach-ratio breach produces a `WAITLISTED` row instead of an error."

    Design: Corner/entities/enrollment_funding_preference_defaults_to_any
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Default Funding Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Defaults")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=10)

    created = validate_success(api.create_enrollment(
        create_enrollment_payload(athlete["id"], session["id"]),
        front_desk_headers), expected_status=201)

    assert created["funding_preference"] == "ANY"
    assert created["status"] == "RESERVED"
    assert created["promoted_from_waitlist"] is False
    assert created["funding_source"] == "DROP_IN"
    assert created["charge_cents"] == 4500


def test_02_an_unknown_athlete_in_the_body_is_a_not_found(
        api, front_desk_headers, performance_director_headers):
    """A body foreign key is resolved with the same dedicated code set as a path id.

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

    "The same code set applies to foreign keys carried in a request body: a body
    referencing an absent program block, whether through `predecessor_block_id` or
    otherwise, returns `ERR_PROGRAM_BLOCK_NOT_FOUND`."

    Design: Corner/entities/enrollment_creation_with_unknown_athlete_fk_returns_not_found
    """
    session = schedule_group_session(start_at="2026-08-21T16:00:00Z",
                                    end_at="2026-08-21T17:00:00Z", station_count=3,
                                    max_athletes=8)

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(UNKNOWN_ATHLETE_ID, session["id"]),
            front_desk_headers),
        "ERR_ATHLETE_NOT_FOUND", expected_status=404)

    assert fetch_group_session(session["id"])["reserved_count"] == 0
    _rows, meta = validate_paginated(api.list_enrollments(performance_director_headers))
    assert meta["total_count"] == 0


def test_03_a_restricted_athlete_is_barred_from_a_specific_prep_session(
        api, front_desk_headers):
    """The restricted phase list excludes specific preparation work.

    "A `RESTRICTED` athlete may only be enrolled in sessions whose `phase_focus` is
    `GENERAL_PREP` or `TRANSITION`; `COMPETITION`, `SPECIFIC_PREP` and `TAPER`
    sessions are refused with `ERR_RESTRICTED_PHASE_NOT_PERMITTED`."

    Design: Corner/validations/restricted_athlete_cannot_enroll_in_specific_prep_session
    """
    athlete, staff, _coach = setup_restricted_athlete(
        athlete_overrides={"full_name": "Restricted Enroller",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Restricted")
    assert athlete["training_clearance"] == "RESTRICTED"
    assert athlete["injury_risk_score"] == pytest.approx(12.00, abs=0.01)

    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, phase_focus="SPECIFIC_PREP", max_athletes=8)

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], session["id"]),
            front_desk_headers),
        "ERR_RESTRICTED_PHASE_NOT_PERMITTED", expected_status=422)

    assert fetch_group_session(session["id"])["reserved_count"] == 0


def test_04_the_same_restricted_athlete_joins_a_general_prep_session(api):
    """General preparation stays open, and the booking leaves the clearance alone.

    "A `RESTRICTED` athlete may only be enrolled in sessions whose `phase_focus` is
    `GENERAL_PREP` or `TRANSITION`; `COMPETITION`, `SPECIFIC_PREP` and `TAPER`
    sessions are refused with `ERR_RESTRICTED_PHASE_NOT_PERMITTED`."

    Design: Corner/validations/restricted_athlete_admitted_to_general_prep_session
    """
    athlete, staff, _coach = setup_restricted_athlete(
        athlete_overrides={"full_name": "Restricted But Allowed",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Restricted")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, phase_focus="GENERAL_PREP", max_athletes=8)

    booked = enroll_athlete(athlete["id"], session["id"])

    assert booked["status"] == "RESERVED"
    assert booked["funding_source"] == "DROP_IN"
    assert booked["charge_cents"] == 4500
    assert fetch_athlete(athlete["id"])["training_clearance"] == "RESTRICTED"
    reread = fetch_group_session(session["id"])
    assert reread["reserved_count"] == 1
    assert reread["athlete_units"] == pytest.approx(1.0, abs=0.05)


def test_05_a_full_session_refuses_unless_the_caller_asks_for_the_waitlist(
        api, front_desk_headers):
    """The same request differs only in request_waitlist, and only one is refused.

    "A session whose `reserved_count` already equals `max_athletes` refuses the
    booking with `ERR_SESSION_FULL` unless `request_waitlist` is true."

    "`WAITLISTED` rows run no funding allocation whatsoever: their `funding_source`
    stays `UNFUNDED`, `charge_cents` stays 0, `membership_package_id` stays null, and
    `station_number` stays null."

    Design: Corner/errors/full_session_without_waitlist_request_returns_session_full
    """
    coach, _cert, coach_headers = create_compliant_coach(full_name="Coach Capacity")
    holder = register_athlete(full_name="Capacity Holder", date_of_birth="2009-02-02")
    overflow = register_athlete(full_name="Capacity Overflow",
                               date_of_birth="2009-03-03")
    for athlete in (holder, overflow):
        run_movement_screen(athlete["id"], coach_headers)
    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, max_athletes=1)
    enroll_athlete(holder["id"], session["id"])

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(overflow["id"], session["id"]),
            front_desk_headers),
        "ERR_SESSION_FULL", expected_status=422)

    waitlisted = enroll_athlete(overflow["id"], session["id"], request_waitlist=True)
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["funding_source"] == "UNFUNDED"
    assert waitlisted["charge_cents"] == 0
    assert waitlisted["membership_package_id"] is None
    assert waitlisted["station_number"] is None

    reread = fetch_group_session(session["id"])
    assert reread["reserved_count"] == 1
    assert reread["waitlisted_count"] == 1


def test_06_a_date_ineligible_package_yields_the_expiry_refusal(
        api, front_desk_headers):
    """The athlete does own a package, so the expiry code outranks the missing-credit one.

    "`ERR_PACKAGE_EXPIRED` takes precedence over it whenever the athlete does own at
    least one package but every candidate is rejected purely on date grounds — an
    `effective_expires_on` earlier than the session date — or is already `EXPIRED`,
    and no other bucket may be used."

    Design: Corner/errors/expired_package_only_request_returns_package_expired_not_missing_credit
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Expired Package Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Expiry")
    package = sell_package(athlete["id"], sessions_purchased=4, price_cents=16000,
                          expires_on="2026-08-31")
    assert package["status"] == "ACTIVE"
    session = setup_session_with_coach(
        staff["id"], start_at="2026-09-15T16:00:00Z", end_at="2026-09-15T17:00:00Z",
        station_count=3, max_athletes=8)

    error = validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], session["id"],
                                     funding_preference="PACKAGE_ONLY"),
            front_desk_headers),
        "ERR_PACKAGE_EXPIRED", expected_status=402)
    assert error["error_id"] != "ERR_NO_SESSION_CREDIT"

    reread = fetch_membership_package(package["id"])
    assert reread["status"] == "ACTIVE", \
        "the clock never passed the expiry, so this is a per-session eligibility refusal"
    assert reread["sessions_remaining"] == 4
    assert reread["sessions_reserved"] == 0


def test_07_an_offsite_booking_beyond_the_allowance_is_refused_not_downgraded(
        api, front_desk_headers):
    """A zero travel allowance is reported, rather than quietly charged elsewhere.

    "A contract-linked athlete whose contract is `ACTIVE` but whose
    `offsite_sessions_used` has already reached `offsite_allowance` cannot consume a
    contract slot for an offsite session, and that condition is reported as
    `ERR_OFFSITE_ALLOWANCE_EXHAUSTED` rather than silently falling through to the
    package bucket."

    Design: Corner/errors/offsite_enrollment_beyond_contract_allowance_returns_allowance_exhausted
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "No Travel Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach No Travel")
    contract = create_active_contract(
        organization_name="No Travel School", organization_type="SCHOOL",
        contracted_sessions=5, base_rate_cents=50000, offsite_allowance=0,
        term_start="2026-08-01", term_end="2027-05-31")
    link_athlete_to_contract(contract["id"], athlete["id"])
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        site_code="OFFSITE", offsite_location="No Travel School Gym", station_count=3,
        max_athletes=8, team_contract_id=contract["id"])

    validate_error(
        api.create_enrollment(
            create_enrollment_payload(athlete["id"], session["id"]),
            front_desk_headers),
        "ERR_OFFSITE_ALLOWANCE_EXHAUSTED", expected_status=402)

    reread = fetch_team_contract(contract["id"])
    assert reread["offsite_sessions_used"] == 0
    assert reread["sessions_reserved"] == 0
    assert reread["sessions_available"] == 5, \
        "the refusal is about the travel allowance, not about slot exhaustion"
    assert fetch_group_session(session["id"])["reserved_count"] == 0


def test_08_the_contract_bucket_is_spent_before_any_package_credit(api):
    """One contract slot is consumed first, and only the second booking touches the package.

    "*Bucket one — the team contract*, always preferred when eligible."

    "The winner sets `funding_source` to `MEMBERSHIP_PACKAGE`, records its own id as
    `membership_package_id`, and leaves `charge_cents` at 0; its `sessions_remaining`
    drops by one, its `sessions_reserved` rises by one, and if that leaves
    `sessions_remaining` at 0 the package moves to `DEPLETED`."

    Design: Corner/calculations/contract_bucket_fills_before_package_and_dropin_buckets
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Waterfall Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Waterfall")
    contract = create_active_contract(
        organization_name="Waterfall Club", organization_type="CLUB",
        contracted_sessions=1, base_rate_cents=50000, offsite_allowance=0,
        term_start="2026-08-01", term_end="2027-05-31")
    link_athlete_to_contract(contract["id"], athlete["id"])
    package = sell_package(athlete["id"], sessions_purchased=5, price_cents=20000,
                          expires_on="2026-12-31")
    first_session = setup_session_with_coach(
        staff["id"], start_at="2026-08-25T16:00:00Z", end_at="2026-08-25T17:00:00Z",
        station_count=3, max_athletes=8, team_contract_id=contract["id"])
    second_session = setup_session_with_coach(
        staff["id"], start_at="2026-08-26T16:00:00Z", end_at="2026-08-26T17:00:00Z",
        station_count=3, max_athletes=8, team_contract_id=contract["id"])

    by_contract = enroll_athlete(athlete["id"], first_session["id"])

    assert by_contract["funding_source"] == "TEAM_CONTRACT"
    assert by_contract["charge_cents"] == 0
    assert by_contract["membership_package_id"] is None, \
        "an eligible package is still left untouched while a contract slot remains"
    contract_after_first = fetch_team_contract(contract["id"])
    assert contract_after_first["sessions_reserved"] == 1
    assert contract_after_first["sessions_available"] == 0
    package_after_first = fetch_membership_package(package["id"])
    assert package_after_first["sessions_remaining"] == 5
    assert package_after_first["sessions_reserved"] == 0

    by_package = enroll_athlete(athlete["id"], second_session["id"])

    assert by_package["funding_source"] == "MEMBERSHIP_PACKAGE"
    assert by_package["membership_package_id"] == package["id"]
    assert by_package["charge_cents"] == 0, "the drop-in bucket is never reached"
    package_after_second = fetch_membership_package(package["id"])
    assert package_after_second["sessions_reserved"] == 1
    assert package_after_second["sessions_remaining"] == 4


def test_09_a_promotion_with_no_eligible_bucket_cancels_the_waitlisted_row(
        api, front_desk_headers):
    """The freed slot cannot be funded, so the promoted row is canceled, not errored.

    "If no bucket resolves, the row instead moves `WAITLISTED → CANCELED` with
    `cancel_reason` of `FUNDING_UNAVAILABLE`; the failure does **not** consume the
    freed slot, and the loop proceeds to the next candidate in ascending `created_at`
    order."

    "A funding failure during promotion never surfaces as an error to any client,
    because no client made the request."

    Design: Corner/calculations/promotion_allocation_variant_cancels_waitlisted_row_when_no_bucket_qualifies
    """
    coach, _cert, coach_headers = create_compliant_coach(full_name="Coach Promotion")
    holder = register_athlete(full_name="Promotion Holder", date_of_birth="2009-02-02")
    candidate = register_athlete(full_name="Promotion Candidate",
                                date_of_birth="2009-03-03")
    for athlete in (holder, candidate):
        run_movement_screen(athlete["id"], coach_headers)
    package = sell_package(candidate["id"], sessions_purchased=2, price_cents=9000,
                          expires_on="2026-08-05")
    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=1)

    held = enroll_athlete(holder["id"], session["id"])
    waitlisted = enroll_athlete(candidate["id"], session["id"],
                                funding_preference="PACKAGE_ONLY", request_waitlist=True)
    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["funding_source"] == "UNFUNDED"

    swept = advance_clock("2026-08-10T09:00:00Z")
    assert swept["packages_expired_count"] == 1
    assert fetch_membership_package(package["id"])["status"] == "EXPIRED"

    released = validate_success(api.cancel_enrollment(held["id"], front_desk_headers))
    assert released["status"] == "CANCELED", "the cancel is more than 24 hours out"

    promoted = fetch_enrollment(waitlisted["id"])
    assert promoted["status"] == "CANCELED"
    assert promoted["cancel_reason"] == "FUNDING_UNAVAILABLE"
    assert promoted["funding_source"] == "UNFUNDED"
    assert promoted["charge_cents"] == 0

    reread = fetch_group_session(session["id"])
    assert reread["reserved_count"] == 0
    assert reread["waitlisted_count"] == 0
