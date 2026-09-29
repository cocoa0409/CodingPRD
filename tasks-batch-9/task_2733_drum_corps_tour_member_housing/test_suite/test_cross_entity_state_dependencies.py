"""Writes whose legality is decided entirely by other entities' states.

A bed may be assigned only when a different record — the facility agreement —
holds the right status *and* the right usage type; a stop may be confirmed only
when members, volunteers and shifts are simultaneously in the right postures.
"""

from test_helpers import (
    ApiErrorId,
    Duty,
    MEMBERSHIP_COORDINATOR_HEADERS,
    TOUR_MANAGER_HEADERS,
    TOUR_MANAGER_ID,
    VOLUNTEER_SCREENER_ID,
    VolunteerRoleType,
    assert_facility_agreement,
    assert_housing_assignment,
    assert_staff_assignment,
    assert_tour_stop,
    assert_volunteer,
    factories as f,
    fixtures as fx,
    validate_error,
)

STAY = ("2027-05-10", "2027-05-20")


def _member_and_three_agreements(api, season_id):
    member = fx.contracted_member(api, season_id, date_of_birth="2005-03-04")["member"]
    school = fx.create_school(api, name="Rockford High School", city="Rockford",
                              state_code="IL")
    draft = fx.draft_agreement(api, school["id"], season_id, usage_type="SPRING_TRAINING",
                               nightly_rate_cents=450, minimum_billable_beds=0)
    rehearsal = fx.signed_agreement_with_school(
        api, season_id, usage_type="TOUR_REHEARSAL", school=school,
        nightly_rate_cents=400, minimum_billable_beds=0,
        start_date="2027-05-10", end_date="2027-06-05",
    )["agreement"]
    spring = fx.signed_agreement_with_school(
        api, season_id, usage_type="SPRING_TRAINING", school=school,
        nightly_rate_cents=450, minimum_billable_beds=0,
    )["agreement"]
    return {"member": member, "school": school, "draft": draft,
            "rehearsal": rehearsal, "spring": spring}


def _bed_request(api, agreement_id, member_id, space_index=1):
    version = fx.get_agreement(api, agreement_id)["version"]
    return api.create_housing_assignment(
        f.housing_assignment_payload(agreement_id, member_id, space_index,
                                     STAY[0], STAY[1], version),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )


def test_neither_a_draft_nor_a_submitted_agreement_can_carry_a_bed(api):
    """Submission is not signature: both pre-signature statuses refuse.

    PRD: "The referenced agreement must be `SIGNED` and its `usage_type` must be
    `SPRING_TRAINING`, or the request reports `ERR_AGREEMENT_NOT_SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/housing_assignment_requires_signed_spring_training_agreement
    """
    season = fx.create_season(api)
    built = _member_and_three_agreements(api, season["id"])

    while_draft = _bed_request(api, built["draft"]["id"], built["member"]["id"])
    validate_error(while_draft, ApiErrorId.AGREEMENT_NOT_SIGNED, 409)

    fx.submit_agreement(api, built["draft"]["id"])
    while_submitted = _bed_request(api, built["draft"]["id"], built["member"]["id"])
    validate_error(while_submitted, ApiErrorId.AGREEMENT_NOT_SIGNED, 409)

    assert_facility_agreement(
        fx.get_agreement(api, built["draft"]["id"]),
        status="SUBMITTED",
        occupied_bed_nights=0,
        billable_cents=0,
    )


def test_a_signed_tour_rehearsal_agreement_still_cannot_carry_a_bed(api):
    """Right status, wrong usage type: the same error surfaces.

    PRD: "The referenced agreement must be `SIGNED` and its `usage_type` must be
    `SPRING_TRAINING`, or the request reports `ERR_AGREEMENT_NOT_SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/housing_assignment_requires_signed_spring_training_agreement
    """
    season = fx.create_season(api)
    built = _member_and_three_agreements(api, season["id"])

    response = _bed_request(api, built["rehearsal"]["id"], built["member"]["id"])
    validate_error(response, ApiErrorId.AGREEMENT_NOT_SIGNED, 409)

    assert_facility_agreement(
        fx.get_agreement(api, built["rehearsal"]["id"]),
        status="SIGNED",
        usage_type="TOUR_REHEARSAL",
        occupied_bed_nights=0,
        billable_cents=0,
    )


def test_the_signed_spring_training_agreement_accepts_the_identical_payload(api):
    """Only the third agreement satisfies both attributes, and it bills.

    PRD: "A successful assignment lands with `status` `ACTIVE` and `released_reason`
    null, then runs the housing chain in full: the agreement's `occupied_bed_nights`
    is re-summed over its active stays, `billable_bed_nights` is re-derived as the
    greater of that occupancy and the minimum-bed floor multiplied by the agreement's
    night count, `billable_cents` is re-derived from the pinned effective rate, the
    school's `reserved_bed_nights` is re-summed across all of its agreements, and the
    season's `housing_cost_cents` is re-summed over `SIGNED` agreements."

    Design: Difficulty/cross_entity_state_dependency/housing_assignment_requires_signed_spring_training_agreement
    """
    season = fx.create_season(api)
    built = _member_and_three_agreements(api, season["id"])

    assignment = fx.house_member(api, built["spring"]["id"], built["member"]["id"], 1,
                                 STAY[0], STAY[1])

    assert_housing_assignment(assignment, status="ACTIVE", nights=10,
                              occupant_is_minor=False, released_reason=None)
    assert_facility_agreement(
        fx.get_agreement(api, built["spring"]["id"]),
        occupied_bed_nights=10,
        billable_bed_nights=10,
        billable_cents=4500,
    )
    assert fx.get_school(api, built["school"]["id"])["reserved_bed_nights"] == 10
    assert fx.get_season(api, season["id"])["housing_cost_cents"] == 4500


SHOW_STOP = dict(
    venue_name="Allen Stadium",
    city="Allen",
    state_code="TX",
    arrive_at="2027-06-20T14:00:00Z",
    depart_at="2027-06-20T23:30:00Z",
    show_start_at="2027-06-20T20:00:00Z",
    travel_miles_from_previous=0,
    uniform_trunks=0,
    instrument_cases=0,
    prop_units=0,
    truck_count=1,
    rehearsal_minutes=0,
    heat_index_f=80,
)


def _roster_stop_and_two_shifts(api, season_id):
    """Two touring members, an approved cook and an unapproved chaperone."""
    fx.contracted_member(api, season_id, full_name="Jamie Torres",
                         date_of_birth="2010-09-01", section="COLOR_GUARD")
    fx.contracted_member(api, season_id, full_name="Avery Nakamura",
                         date_of_birth="2005-03-04", section="BRASS")
    chaperone = fx.create_volunteer(api, VolunteerRoleType.CHAPERONE,
                                    full_name="Nia Foster")
    cook = fx.create_volunteer(api, VolunteerRoleType.COOK, full_name="Robin Vega")
    fx.clear_volunteer(api, cook["id"], "2026-08-01")

    fx.set_clock(api, "2027-06-12T06:00:00Z")
    fx.run_sweep(api, season_id)

    stop = fx.create_stop(api, season_id, **SHOW_STOP)
    cook_shift = fx.propose_shift(api, cook["id"], stop["id"], Duty.COOK,
                                  "2027-06-20T15:00:00Z", "2027-06-20T22:00:00Z")
    fx.accept_shift(api, cook_shift["id"], cook["id"])
    fx.approve_shift(api, cook_shift["id"])

    chaperone_shift = fx.propose_shift(api, chaperone["id"], stop["id"], Duty.CHAPERONE,
                                       "2027-06-20T14:00:00Z", "2027-06-20T23:00:00Z")
    fx.accept_shift(api, chaperone_shift["id"], chaperone["id"])
    return {"stop": stop, "chaperone": chaperone,
            "chaperone_shift": chaperone_shift, "cook_shift": cook_shift}


def test_an_accepted_chaperone_shift_does_not_yet_cover_the_minor(api):
    """Only approved shifts count toward the coverage ratios.

    PRD: "Chaperone coverage requires at least one approved `CHAPERONE` shift for
    every ten minors on the touring roster — the minor head count divided by ten
    and rounded **up** — reported as `ERR_CHAPERONE_COVERAGE_INSUFFICIENT` when
    short."

    Design: Difficulty/cross_entity_state_dependency/stop_confirmation_depends_on_member_volunteer_and_assignment_states
    """
    season = fx.create_season(api)
    built = _roster_stop_and_two_shifts(api, season["id"])

    response = api.confirm_tour_stop(built["stop"]["id"], TOUR_MANAGER_HEADERS)
    validate_error(response, ApiErrorId.CHAPERONE_COVERAGE_INSUFFICIENT, 409)

    assert_tour_stop(fx.get_stop(api, built["stop"]["id"]), status="PLANNED",
                     roster_head_count=0, minor_head_count=0, meal_cost_cents=0)


def test_the_chaperone_shift_cannot_be_approved_while_screening_is_pending(api):
    """The blocked stop cannot be unblocked without clearing the volunteer.

    PRD: "Approval carries two gates beyond the status gate: the volunteer's
    `screening_status` must be `CLEARED`, so a `PENDING`, `REJECTED` or `EXPIRED`
    screening reports `ERR_SCREENING_NOT_CLEARED`; and the approving `X-User-ID`
    must differ from the volunteer's `screened_by_user_id`, so the screener may
    never bless their own subject and an attempt reports
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/cross_entity_state_dependency/stop_confirmation_depends_on_member_volunteer_and_assignment_states
    """
    season = fx.create_season(api)
    built = _roster_stop_and_two_shifts(api, season["id"])

    response = api.approve_staff_assignment(built["chaperone_shift"]["id"],
                                            TOUR_MANAGER_HEADERS)
    validate_error(response, ApiErrorId.SCREENING_NOT_CLEARED, 409)

    assert_staff_assignment(fx.get_shift(api, built["chaperone_shift"]["id"]),
                            status="ACCEPTED", approved_by_user_id=None)
    assert_volunteer(fx.get_volunteer(api, built["chaperone"]["id"]),
                     screening_status="PENDING", assignment_count=0)


def test_clearing_the_screening_unlocks_approval_and_then_confirmation(api):
    """Three entities move in order and the stop finally snapshots its roster.

    PRD: "A clearance moves the volunteer `PENDING → CLEARED` and computes
    `screening_expires_on` as `screening_decided_on` advanced by three hundred and
    sixty-five days."

    Design: Difficulty/cross_entity_state_dependency/stop_confirmation_depends_on_member_volunteer_and_assignment_states
    """
    season = fx.create_season(api)
    built = _roster_stop_and_two_shifts(api, season["id"])

    cleared = fx.clear_volunteer(api, built["chaperone"]["id"], "2027-06-12")
    assert_volunteer(cleared, screening_status="CLEARED",
                     screening_decided_on="2027-06-12",
                     screening_expires_on="2028-06-11",
                     screened_by_user_id=VOLUNTEER_SCREENER_ID)

    approved = fx.approve_shift(api, built["chaperone_shift"]["id"])
    assert_staff_assignment(approved, status="APPROVED",
                            approved_by_user_id=TOUR_MANAGER_ID)
    assert_volunteer(fx.get_volunteer(api, built["chaperone"]["id"]),
                     assignment_count=1)

    confirmed = fx.confirm_stop(api, built["stop"]["id"])
    assert_tour_stop(confirmed, status="CONFIRMED", roster_head_count=2,
                     minor_head_count=1, required_chaperone_count=1,
                     required_cook_count=1, meal_cost_cents=7050)
