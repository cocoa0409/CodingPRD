"""Endpoint-level behaviour: creation shape, action guards and list reachability.

Each test drives a route end to end and reads the result back through the same
API, so anything the server stores but never returns is caught here.
"""

from test_helpers import (
    ApiErrorId,
    BUSINESS_MANAGER_HEADERS,
    BookingStatus,
    LedgerStatus,
    MEMBERSHIP_COORDINATOR_HEADERS,
    MembershipStatus,
    NON_EXISTENT_UUID,
    PlanStatus,
    ScreeningStatus,
    SettlementState,
    StopStatus,
    TOUR_MANAGER_HEADERS,
    UsageType,
    VOLUNTEER_SCREENER_ID,
    VolunteerRoleType,
    assert_all_nulls,
    assert_member,
    assert_payment_plan,
    assert_site_booking,
    assert_tour_stop,
    assert_volunteer,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


def test_a_new_plan_exposes_its_whole_schedule_on_create_read_and_list(api):
    """The struck schedule survives a round trip and answers the filters.

    PRD: "A `STANDARD_3` plan therefore always carries a `surcharge_cents` of 0."

    Design: Corner/endpoints/payment_plan_create_read_and_list_expose_the_whole_schedule
    """
    season = fx.create_season(api)
    built = fx.financed_member(api, season["id"], "2027-01-15")
    plan = built["plan"]

    expected = dict(
        plan_type="STANDARD_3",
        installment_count=3,
        principal_cents=399900,
        surcharge_cents=0,
        financed_total_cents=399900,
        installment_base_cents=133300,
        installment_remainder_cents=0,
        first_due_date="2027-01-15",
        installments_due_count=0,
        due_amount_cents=0,
        arrears_cents=0,
        late_fee_accrued_cents=0,
        late_fee_paid_cents=0,
        principal_paid_cents=0,
        outstanding_cents=399900,
        delinquency_strikes=0,
        status=PlanStatus.ACTIVE,
    )
    assert_payment_plan(plan, **expected)
    assert_payment_plan(fx.get_plan(api, plan["id"]), **expected)

    listed, meta = validate_paginated(
        api.list_payment_plans(
            BUSINESS_MANAGER_HEADERS,
            {"member_id": built["member"]["id"], "status": PlanStatus.ACTIVE},
        )
    )
    assert [p["id"] for p in listed] == [plan["id"]]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    assert_member(
        fx.get_member(api, built["member"]["id"]), tuition_charged_cents=399900
    )
    assert fx.get_season(api, season["id"])["tuition_charged_cents"] == 399900


def test_completion_is_refused_one_minute_early_and_allowed_on_the_instant(api):
    """The departure guard is inclusive at exactly depart_at.

    PRD: "It moves the stop `CONFIRMED → COMPLETED` and requires that the logical-clock instant have reached or passed the stop's `depart_at`; completing early reports `ERR_STOP_NOT_DEPARTED`."

    Design: Corner/endpoints/stop_complete_requires_the_clock_to_reach_depart_at
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
    confirmed = fx.confirm_stop(api, stop["id"])
    assert_tour_stop(confirmed, status=StopStatus.CONFIRMED, version=2)

    fx.set_clock(api, "2027-06-19T19:59:00Z")
    validate_error(
        api.complete_tour_stop(stop["id"], TOUR_MANAGER_HEADERS),
        ApiErrorId.STOP_NOT_DEPARTED,
        409,
    )
    assert_tour_stop(
        fx.get_stop(api, stop["id"]), status=StopStatus.CONFIRMED, version=2
    )

    fx.set_clock(api, "2027-06-19T20:00:00Z")
    completed = fx.complete_stop(api, stop["id"])
    assert_tour_stop(
        completed,
        status=StopStatus.COMPLETED,
        settlement_state=SettlementState.NONE,
        version=3,
    )
    assert fx.get_season(api, season["id"])["ledger_status"] == LedgerStatus.OPEN


def test_the_sweep_boards_the_roster_on_the_departure_date_itself(api):
    """One day early boards nobody; the departure date itself boards the member.

    PRD: "Once the logical-clock date has reached or passed the season's `tour_departure_date`, the sweep promotes each member whose `membership_status` is `CONTRACTED` onto the touring roster, moving them `CONTRACTED → ON_TOUR` and advancing their `version` by one."

    Design: Corner/endpoints/billing_sweep_boards_members_only_from_the_departure_date
    """
    season = fx.create_season(api)
    built = fx.financed_member(api, season["id"], "2027-07-15")
    member_id = built["member"]["id"]

    fx.set_clock(api, "2027-06-11T12:00:00Z")
    first = fx.run_sweep(api, season["id"])
    assert first["billing_epoch"] == 1
    assert_member(
        fx.get_member(api, member_id), membership_status=MembershipStatus.CONTRACTED
    )

    fx.set_clock(api, "2027-06-12T00:00:00Z")
    second = fx.run_sweep(api, season["id"])
    assert second["billing_epoch"] == 2
    assert_member(
        fx.get_member(api, member_id), membership_status=MembershipStatus.ON_TOUR
    )

    assert_payment_plan(
        fx.get_plan(api, built["plan"]["id"]),
        installments_due_count=0,
        arrears_cents=0,
        late_fee_accrued_cents=0,
        delinquency_strikes=0,
        status=PlanStatus.ACTIVE,
    )
    assert second["tuition_charged_cents"] == 399900


def test_a_rehearsal_block_resolves_all_three_references_before_any_rule(api):
    """An unknown agreement id answers before the window rule the same call breaks.

    PRD: "Rung 8 then resolves every foreign key in the request body, in declaration order, using the same error family."

    Design: Corner/endpoints/site_booking_link_requires_every_reference_to_resolve
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

    validate_error(
        api.create_site_booking(
            f.site_booking_payload(
                stop["id"],
                school_id,
                NON_EXISTENT_UUID,
                "2027-07-04T10:00:00Z",
                "2027-07-04T14:00:00Z",
                indoor=False,
            ),
            TOUR_MANAGER_HEADERS,
        ),
        ApiErrorId.FACILITY_AGREEMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_site_booking(
            f.site_booking_payload(
                stop["id"],
                school_id,
                agreement_id,
                "2027-06-26T10:00:00Z",
                "2027-06-26T14:00:00Z",
                indoor=False,
            ),
            TOUR_MANAGER_HEADERS,
        ),
        ApiErrorId.BLOCK_OUTSIDE_AGREEMENT_WINDOW,
        409,
    )

    booking = fx.create_booking(
        api,
        stop["id"],
        school_id,
        agreement_id,
        "2027-06-19T10:00:00Z",
        "2027-06-19T14:00:00Z",
        indoor=False,
    )
    assert_site_booking(
        booking,
        tour_stop_id=stop["id"],
        host_school_id=school_id,
        facility_agreement_id=agreement_id,
        indoor=False,
        status=BookingStatus.HELD,
    )

    by_agreement, agreement_meta = validate_paginated(
        api.list_site_bookings(
            TOUR_MANAGER_HEADERS,
            {"facility_agreement_id": agreement_id, "status": BookingStatus.HELD},
        )
    )
    assert [b["id"] for b in by_agreement] == [booking["id"]]
    assert agreement_meta["total_count"] == 1

    by_school, school_meta = validate_paginated(
        api.list_site_bookings(
            MEMBERSHIP_COORDINATOR_HEADERS, {"host_school_id": school_id}
        )
    )
    assert [b["id"] for b in by_school] == [booking["id"]]
    assert school_meta["total_count"] == 1
    assert fx.get_school(api, school_id)["booked_block_count"] == 1


def test_a_clearance_expires_three_hundred_and_sixty_five_days_later(api):
    """A leap day inside the window shifts the expiry off the anniversary.

    PRD: "A clearance moves the volunteer `PENDING → CLEARED` and computes `screening_expires_on` as `screening_decided_on` advanced by three hundred and sixty-five days."

    Design: Corner/endpoints/screening_expiry_is_derived_as_decided_on_plus_365_days
    """
    early = fx.create_volunteer(api, VolunteerRoleType.COOK)
    leap = fx.create_volunteer(api, VolunteerRoleType.CHAPERONE)
    barred = fx.create_volunteer(api, VolunteerRoleType.CHAPERONE)

    cleared_early = fx.clear_volunteer(api, early["id"], "2026-08-01")
    assert_volunteer(
        cleared_early,
        screening_status=ScreeningStatus.CLEARED,
        screening_decided_on="2026-08-01",
        screening_expires_on="2027-08-01",
        screened_by_user_id=VOLUNTEER_SCREENER_ID,
    )

    rejected = fx.reject_volunteer(api, barred["id"], "2026-08-01")
    assert_volunteer(
        rejected,
        screening_status=ScreeningStatus.REJECTED,
        screening_decided_on="2026-08-01",
        screened_by_user_id=VOLUNTEER_SCREENER_ID,
    )
    assert_all_nulls(rejected, "screening_expires_on")

    fx.set_clock(api, "2027-06-12T00:00:00Z")
    cleared_leap = fx.clear_volunteer(api, leap["id"], "2027-06-12")
    assert_volunteer(
        cleared_leap,
        screening_status=ScreeningStatus.CLEARED,
        screening_decided_on="2027-06-12",
        screening_expires_on="2028-06-11",
    )
    assert_volunteer(
        fx.get_volunteer(api, leap["id"], TOUR_MANAGER_HEADERS),
        screening_expires_on="2028-06-11",
    )
