"""Half-open intervals: touching is legal, genuine overlap is not.

Both the bed calendar and the volunteer roster treat a range as inclusive at the
start and exclusive at the end, so a stay or a shift may begin exactly where the
previous one ended while a single shared night or minute is refused.
"""

from test_helpers import (
    ApiErrorId,
    Duty,
    MEMBERSHIP_COORDINATOR_HEADERS,
    TOUR_MANAGER_HEADERS,
    VolunteerRoleType,
    assert_facility_agreement,
    assert_housing_assignment,
    assert_staff_assignment,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


def _two_adults_in_space_one(api, season_id):
    built = fx.signed_agreement_with_school(
        api, season_id, nightly_rate_cents=450, minimum_billable_beds=0,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )
    first = fx.contracted_member(api, season_id, full_name="Avery Nakamura",
                                 date_of_birth="2005-03-04", section="BRASS")["member"]
    second = fx.contracted_member(api, season_id, full_name="Casey Whitfield",
                                  date_of_birth="2004-07-19",
                                  section="PERCUSSION")["member"]
    stay_a = fx.house_member(api, built["agreement"]["id"], first["id"], 1,
                             "2027-05-10", "2027-05-20")
    fx.house_member(api, built["agreement"]["id"], second["id"], 1,
                    "2027-05-10", "2027-05-20")
    return {"school": built["school"], "agreement": built["agreement"],
            "member": first, "stay_a": stay_a}


def _second_stay(api, agreement_id, member_id, check_in, check_out):
    version = fx.get_agreement(api, agreement_id)["version"]
    return api.create_housing_assignment(
        f.housing_assignment_payload(agreement_id, member_id, 2, check_in,
                                     check_out, version),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )


def test_a_single_shared_night_in_another_space_is_still_double_housing(api):
    """One overlapping night refuses the stay even in a different space.

    PRD: "And the member may not already hold an active stay whose dates overlap
    the requested ones — in any space, under any agreement — or the request reports
    `ERR_MEMBER_ALREADY_HOUSED`."

    Design: Difficulty/resource_temporal_overlap/touching_housing_stays_allowed_while_overlapping_stay_is_rejected
    """
    season = fx.create_season(api)
    built = _two_adults_in_space_one(api, season["id"])
    before = fx.get_agreement(api, built["agreement"]["id"])

    response = _second_stay(api, built["agreement"]["id"], built["member"]["id"],
                            "2027-05-19", "2027-05-25")
    validate_error(response, ApiErrorId.MEMBER_ALREADY_HOUSED, 409)

    after = fx.get_agreement(api, built["agreement"]["id"])
    assert after["version"] == before["version"], (
        "a refused stay must not advance the agreement version"
    )
    assert_facility_agreement(after, occupied_bed_nights=20, billable_cents=9000)


def test_a_stay_beginning_on_the_previous_check_out_date_is_accepted(api):
    """Check-out is exclusive, so back-to-back stays share no night.

    PRD: "The two remaining checks operate on the **overlap set**: the housing
    assignments whose `status` is `ACTIVE`, that sit on the same
    `facility_agreement_id` and the same `space_index`, and whose date range
    genuinely overlaps the candidate's — that is, whose existing check-in falls
    strictly before the candidate's check-out and whose existing check-out falls
    strictly after the candidate's check-in."

    Design: Difficulty/resource_temporal_overlap/touching_housing_stays_allowed_while_overlapping_stay_is_rejected
    """
    season = fx.create_season(api)
    built = _two_adults_in_space_one(api, season["id"])

    response = _second_stay(api, built["agreement"]["id"], built["member"]["id"],
                            "2027-05-20", "2027-05-25")
    assert response.status_code == 201, response.text
    assignment = response.json()["data"]
    assert_housing_assignment(assignment, status="ACTIVE", nights=5, space_index=2)
    assert_housing_assignment(fx.get_housing(api, built["stay_a"]["id"]),
                              status="ACTIVE", nights=10)

    assert_facility_agreement(
        fx.get_agreement(api, built["agreement"]["id"]),
        occupied_bed_nights=25, billable_bed_nights=25, billable_cents=11250,
    )
    assert fx.get_school(api, built["school"]["id"])["reserved_bed_nights"] == 25
    assert fx.get_season(api, season["id"])["housing_cost_cents"] == 11250


REHEARSAL_SHAPE = dict(
    city="Rockford",
    state_code="IL",
    travel_miles_from_previous=0,
    uniform_trunks=0,
    instrument_cases=0,
    prop_units=0,
    truck_count=1,
    rehearsal_minutes=120,
    heat_index_f=82,
)


def _driver_with_a_morning_shift(api, season_id):
    morning = fx.create_rehearsal_stop(api, season_id, venue_name="Rockford AM block",
                                       arrive_at="2027-06-20T08:00:00Z",
                                       depart_at="2027-06-20T14:00:00Z",
                                       **REHEARSAL_SHAPE)
    afternoon = fx.create_rehearsal_stop(api, season_id, venue_name="Rockford PM block",
                                         arrive_at="2027-06-20T12:00:00Z",
                                         depart_at="2027-06-20T22:00:00Z",
                                         **REHEARSAL_SHAPE)
    driver = fx.create_volunteer(api, VolunteerRoleType.DRIVER,
                                 full_name="Sam Herrera", cdl_number="IL-CDL-88213")
    fx.clear_volunteer(api, driver["id"], "2026-08-01")
    first = fx.propose_shift(api, driver["id"], morning["id"], Duty.DRIVE,
                             "2027-06-20T08:00:00Z", "2027-06-20T13:00:00Z")
    return {"morning": morning, "afternoon": afternoon, "driver": driver,
            "first": first}


def _drive_shift(api, driver_id, stop_id, start, end):
    return api.create_staff_assignment(
        f.staff_assignment_payload(driver_id, stop_id, Duty.DRIVE, start, end),
        TOUR_MANAGER_HEADERS,
    )


def test_a_shift_overlapping_an_already_proposed_one_is_refused(api):
    """A shift still awaiting acceptance already blocks the volunteer's calendar.

    PRD: "And one volunteer may not hold two open shifts whose windows overlap:
    for the same volunteer, no shift whose `status` is `PROPOSED`, `ACCEPTED` or
    `APPROVED` may have a start strictly earlier than the candidate's end while
    also having an end strictly later than the candidate's start."

    Design: Difficulty/resource_temporal_overlap/touching_volunteer_shifts_allowed_while_overlapping_shift_is_rejected
    """
    season = fx.create_season(api)
    built = _driver_with_a_morning_shift(api, season["id"])

    response = _drive_shift(api, built["driver"]["id"], built["afternoon"]["id"],
                            "2027-06-20T12:00:00Z", "2027-06-20T18:00:00Z")
    validate_error(response, ApiErrorId.VOLUNTEER_SHIFT_OVERLAP, 409)

    assert_staff_assignment(fx.get_shift(api, built["first"]["id"]),
                            status="PROPOSED",
                            shift_end_at="2027-06-20T13:00:00Z")


def test_a_shift_that_both_overlaps_and_escapes_the_window_reports_the_window(api):
    """Two violations at once, and the lower rung is the one reported.

    PRD: "Rung 42 rejects a shift falling outside its stop window with
    `ERR_SHIFT_OUTSIDE_STOP_WINDOW`, and rung 43 rejects a volunteer holding two
    overlapping open shifts with `ERR_VOLUNTEER_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/touching_volunteer_shifts_allowed_while_overlapping_shift_is_rejected
    """
    season = fx.create_season(api)
    built = _driver_with_a_morning_shift(api, season["id"])

    response = _drive_shift(api, built["driver"]["id"], built["afternoon"]["id"],
                            "2027-06-20T11:00:00Z", "2027-06-20T18:00:00Z")
    validate_error(response, ApiErrorId.SHIFT_OUTSIDE_STOP_WINDOW, 409)


def test_a_shift_beginning_exactly_when_the_first_ends_is_accepted(api):
    """Touching shifts are legal and neither one counts as an assignment yet.

    PRD: "Touching shifts — one ending exactly when the next begins — are legal;
    genuine overlap reports `ERR_VOLUNTEER_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/touching_volunteer_shifts_allowed_while_overlapping_shift_is_rejected
    """
    season = fx.create_season(api)
    built = _driver_with_a_morning_shift(api, season["id"])

    response = _drive_shift(api, built["driver"]["id"], built["afternoon"]["id"],
                            "2027-06-20T13:00:00Z", "2027-06-20T18:00:00Z")
    assert response.status_code == 201, response.text
    assert_staff_assignment(response.json()["data"], status="PROPOSED",
                            tour_stop_id=built["afternoon"]["id"],
                            shift_start_at="2027-06-20T13:00:00Z")

    assert fx.get_volunteer(api, built["driver"]["id"])["assignment_count"] == 0
    shifts, _meta = validate_paginated(
        api.list_staff_assignments(TOUR_MANAGER_HEADERS,
                                   params={"volunteer_id": built["driver"]["id"]})
    )
    assert len(shifts) == 2, f"expected two shifts for the driver, got {len(shifts)}"
