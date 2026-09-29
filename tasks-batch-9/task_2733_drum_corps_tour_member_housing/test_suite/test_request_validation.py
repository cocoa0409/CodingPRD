"""Request-level rules and the ladder order between them.

Each test drives one call that violates two rungs at once and then isolates each
rung on its own, so a masked check is visible rather than merely suspected.
"""

from test_helpers import (
    ApiErrorId,
    BookingStatus,
    Duty,
    MEMBERSHIP_COORDINATOR_HEADERS,
    MembershipStatus,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    OMIT,
    ScreeningDecision,
    ScreeningStatus,
    StaffAssignmentStatus,
    TOUR_MANAGER_HEADERS,
    UsageType,
    VOLUNTEER_SCREENER_HEADERS,
    VolunteerRoleType,
    WithdrawalBasis,
    assert_all_nulls,
    assert_facility_agreement,
    assert_housing_assignment,
    assert_member,
    assert_season,
    assert_site_booking,
    assert_staff_assignment,
    assert_volunteer,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


def test_a_call_with_no_identity_headers_is_rejected_before_anything_else(api):
    """Rung 1 outranks the existence check and the schema check alike.

    PRD: "the first violated rung decides the response, and no side effect of the request is applied"

    Design: Corner/validations/call_with_missing_x_user_id_header_is_unauthenticated
    """
    season = fx.create_season(api)

    validate_error(
        api.call("GET", f"/seasons/{NON_EXISTENT_UUID}", headers=NO_AUTH_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.call("POST", "/seasons", {"year": 2027}, NO_AUTH_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.create_season(f.season_payload(name="Pirate Season"), TOUR_MANAGER_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    assert_season(fx.get_season(api, season["id"]), version=1, name="2027 Tour")


def test_a_stay_may_touch_the_agreement_end_date_but_not_pass_it(api):
    """26 nights fitting the window exactly, against one day either side.

    PRD: "The whole stay must sit inside the agreement's window — check-in on or after `start_date` and check-out on or before `end_date` — or the request reports `ERR_STAY_OUTSIDE_AGREEMENT_WINDOW`."

    Design: Corner/validations/housing_stay_must_fall_inside_the_agreement_window
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api,
        season["id"],
        UsageType.SPRING_TRAINING,
        school_overrides={
            "name": "Rockford High School",
            "city": "Rockford",
            "state_code": "IL",
            "sleeping_space_count": 30,
            "capacity_per_space": 12,
            "rehearsal_field_count": 2,
            "has_air_conditioning": True,
        },
        start_date="2027-05-10",
        end_date="2027-06-05",
        nightly_rate_cents=500,
        minimum_billable_beds=0,
    )
    agreement_id = built["agreement"]["id"]
    member_a = fx.contracted_member(api, season["id"])["member"]
    member_b = fx.contracted_member(api, season["id"])["member"]

    version_before = fx.get_agreement(api, agreement_id)["version"]
    stay = fx.house_member(
        api, agreement_id, member_a["id"], 1, "2027-05-10", "2027-06-05", version_before
    )
    assert_housing_assignment(stay, nights=26, occupant_is_minor=False)

    version_after = fx.get_agreement(api, agreement_id)["version"]
    assert version_after == version_before + 1, "one accepted stay bumps the agreement once"

    for check_in, check_out in (("2027-05-09", "2027-05-20"), ("2027-05-20", "2027-06-06")):
        validate_error(
            api.create_housing_assignment(
                f.housing_assignment_payload(
                    agreement_id, member_b["id"], 2, check_in, check_out, version_after
                ),
                MEMBERSHIP_COORDINATOR_HEADERS,
            ),
            ApiErrorId.STAY_OUTSIDE_AGREEMENT_WINDOW,
            409,
        )

    assert_facility_agreement(
        fx.get_agreement(api, agreement_id),
        version=version_after,
        occupied_bed_nights=26,
        billable_bed_nights=26,
        billable_cents=13000,
    )
    assert fx.get_school(api, built["school"]["id"])["reserved_bed_nights"] == 26
    assert fx.get_season(api, season["id"])["housing_cost_cents"] == 13000


def test_conditional_credentials_and_show_times_fail_in_both_directions(api):
    """The required field missing and the forbidden field present both fail.

    PRD: "Supplying either outside its condition, or omitting it inside its condition, reports `ERR_CONDITIONAL_FIELD_MISMATCH`."

    Design: Corner/validations/conditional_credential_and_show_fields_track_their_flag
    """
    season = fx.create_season(api)

    rejected_volunteers = [
        f.volunteer_payload(VolunteerRoleType.DRIVER, cdl_number=OMIT),
        f.volunteer_payload(VolunteerRoleType.COOK, cdl_number="IL-99887766"),
        f.volunteer_payload(VolunteerRoleType.ATHLETIC_TRAINER, credential_id=OMIT),
    ]
    for payload in rejected_volunteers:
        validate_error(
            api.create_volunteer(payload, VOLUNTEER_SCREENER_HEADERS),
            ApiErrorId.CONDITIONAL_FIELD_MISMATCH,
            400,
        )

    driver = fx.create_volunteer(
        api, VolunteerRoleType.DRIVER, cdl_number="IL-99887766"
    )
    assert_volunteer(
        driver,
        role_type=VolunteerRoleType.DRIVER,
        cdl_number="IL-99887766",
        screening_status=ScreeningStatus.PENDING,
        assignment_count=0,
    )
    assert_all_nulls(driver, "credential_id")

    rejected_stops = [
        f.tour_stop_payload(season["id"], venue_name="No Show Time", show_start_at=OMIT),
        f.rehearsal_stop_payload(
            season["id"],
            venue_name="Rehearsal With Show Time",
            show_start_at="2027-06-19T12:00:00Z",
        ),
        f.rehearsal_stop_payload(
            season["id"], venue_name="Orphan Mileage", travel_miles_from_previous=120
        ),
    ]
    for payload in rejected_stops:
        validate_error(
            api.create_tour_stop(payload, TOUR_MANAGER_HEADERS),
            ApiErrorId.CONDITIONAL_FIELD_MISMATCH,
            400,
        )

    stops, meta = validate_paginated(
        api.list_tour_stops(TOUR_MANAGER_HEADERS, {"season_id": season["id"]})
    )
    assert stops == [], "not one of the three refused stops was stored"
    assert meta["total_count"] == 0

    volunteers, volunteer_meta = validate_paginated(
        api.list_volunteers(VOLUNTEER_SCREENER_HEADERS)
    )
    assert [v["id"] for v in volunteers] == [driver["id"]]
    assert volunteer_meta["total_count"] == 1


def test_a_future_withdrawal_date_reports_future_dating_not_back_dating(api):
    """One date violates both temporal rungs; the lower-numbered rung answers.

    PRD: "Rung 44 rejects any business date later than the logical-clock date — a payment's `received_on`, a screening's `decided_on`, or a member's `withdrawal_date` — with `ERR_FUTURE_DATED_INPUT`, and it guards payment posting, the screening decision and the withdrawal."

    Design: Corner/validations/future_dating_outranks_the_withdrawal_back_date_window
    """
    season = fx.create_season(api)
    member = fx.offered_member(api, season["id"], audition_score=90)
    volunteer = fx.create_volunteer(api, VolunteerRoleType.COOK)
    fx.set_clock(api, "2027-04-01T00:00:00Z")

    validate_error(
        api.withdraw_member(
            member["id"],
            f.withdraw_payload("2027-05-01", reason="both rules violated"),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.FUTURE_DATED_INPUT,
        409,
    )
    validate_error(
        api.record_screening_decision(
            volunteer["id"],
            f.screening_decision_payload("2027-04-02", ScreeningDecision.CLEAR),
            VOLUNTEER_SCREENER_HEADERS,
        ),
        ApiErrorId.FUTURE_DATED_INPUT,
        409,
    )
    untouched = fx.get_volunteer(api, volunteer["id"])
    assert_volunteer(untouched, screening_status=ScreeningStatus.PENDING)
    assert_all_nulls(untouched, "screening_decided_on", "screening_expires_on")

    fx.set_clock(api, "2027-05-20T00:00:00Z")
    validate_error(
        api.withdraw_member(
            member["id"],
            f.withdraw_payload("2027-05-01", reason="back-dated only"),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.WITHDRAWAL_DATE_OUT_OF_RANGE,
        409,
    )
    assert_member(
        fx.get_member(api, member["id"]), membership_status=MembershipStatus.OFFERED
    )

    withdrawn = fx.withdraw_member(api, member["id"], "2027-05-20", reason="legal")
    assert_member(
        withdrawn,
        membership_status=MembershipStatus.WITHDRAWN,
        withdrawal_date="2027-05-20",
        withdrawal_obligation_basis=WithdrawalBasis.NONE,
        withdrawal_obligation_cents=0,
    )


def test_a_clear_gap_of_exactly_one_hundred_and_eighty_minutes_is_bookable(api):
    """179 minutes conflicts, 180 does not, and both comparisons are strict.

    PRD: "a gap of exactly one hundred and eighty minutes is accepted because the comparison is strict, and one of a hundred and seventy-nine minutes is refused with `ERR_SITE_BLOCK_CONFLICT`"

    Design: Corner/validations/site_block_gap_of_exactly_180_minutes_is_accepted
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api,
        season["id"],
        UsageType.TOUR_REHEARSAL,
        school_overrides={
            "name": "Rockford High School",
            "city": "Rockford",
            "state_code": "IL",
            "sleeping_space_count": 30,
            "capacity_per_space": 12,
            "rehearsal_field_count": 2,
            "has_air_conditioning": True,
        },
        start_date="2027-06-18",
        end_date="2027-06-25",
        nightly_rate_cents=400,
        minimum_billable_beds=0,
    )
    school_id = built["school"]["id"]
    agreement_id = built["agreement"]["id"]
    stop = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="Rockford High School",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-19T06:00:00Z",
        depart_at="2027-06-19T23:00:00Z",
        truck_count=1,
        rehearsal_minutes=120,
    )
    fx.create_booking(
        api,
        stop["id"],
        school_id,
        agreement_id,
        "2027-06-19T08:00:00Z",
        "2027-06-19T12:00:00Z",
        indoor=False,
    )

    validate_error(
        api.create_site_booking(
            f.site_booking_payload(
                stop["id"],
                school_id,
                agreement_id,
                "2027-06-19T14:59:00Z",
                "2027-06-19T16:00:00Z",
                indoor=False,
            ),
            TOUR_MANAGER_HEADERS,
        ),
        ApiErrorId.SITE_BLOCK_CONFLICT,
        409,
    )

    second = fx.create_booking(
        api,
        stop["id"],
        school_id,
        agreement_id,
        "2027-06-19T15:00:00Z",
        "2027-06-19T16:00:00Z",
        indoor=False,
    )
    third = fx.create_booking(
        api,
        stop["id"],
        school_id,
        agreement_id,
        "2027-06-19T20:00:00Z",
        "2027-06-19T22:00:00Z",
        indoor=False,
    )
    assert_site_booking(second, status=BookingStatus.HELD)
    assert_site_booking(third, status=BookingStatus.HELD)
    assert fx.get_school(api, school_id)["booked_block_count"] == 3


def test_the_duty_role_pairing_is_checked_before_the_shift_window(api):
    """A referential violation and a temporal one in one call: rung 29 answers.

    PRD: "The duty must correspond exactly to the volunteer's `role_type`: `DRIVE` pairs with `DRIVER`, `COOK` with `COOK`, `CHAPERONE` with `CHAPERONE`, and `TRAINER` with `ATHLETIC_TRAINER`; any other pairing reports `ERR_DUTY_ROLE_MISMATCH`."

    Design: Corner/validations/duty_role_mismatch_outranks_the_shift_window_check
    """
    season = fx.create_season(api)
    stop = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="Rockford High School",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-19T08:00:00Z",
        depart_at="2027-06-19T20:00:00Z",
        truck_count=1,
        rehearsal_minutes=120,
    )
    cook = fx.create_volunteer(api, VolunteerRoleType.COOK)

    def propose(duty, start, end):
        return api.create_staff_assignment(
            f.staff_assignment_payload(cook["id"], stop["id"], duty, start, end),
            TOUR_MANAGER_HEADERS,
        )

    validate_error(
        propose(Duty.TRAINER, "2027-06-19T07:00:00Z", "2027-06-19T21:00:00Z"),
        ApiErrorId.DUTY_ROLE_MISMATCH,
        409,
    )
    validate_error(
        propose(Duty.TRAINER, "2027-06-19T09:00:00Z", "2027-06-19T19:00:00Z"),
        ApiErrorId.DUTY_ROLE_MISMATCH,
        409,
    )
    validate_error(
        propose(Duty.COOK, "2027-06-19T07:59:00Z", "2027-06-19T19:00:00Z"),
        ApiErrorId.SHIFT_OUTSIDE_STOP_WINDOW,
        409,
    )

    shift = fx.propose_shift(
        api,
        cook["id"],
        stop["id"],
        Duty.COOK,
        "2027-06-19T08:00:00Z",
        "2027-06-19T20:00:00Z",
    )
    assert_staff_assignment(shift, duty=Duty.COOK, status=StaffAssignmentStatus.PROPOSED)

    shifts, meta = validate_paginated(
        api.list_staff_assignments(TOUR_MANAGER_HEADERS, {"tour_stop_id": stop["id"]})
    )
    assert [s["id"] for s in shifts] == [shift["id"]]
    assert meta["total_count"] == 1
