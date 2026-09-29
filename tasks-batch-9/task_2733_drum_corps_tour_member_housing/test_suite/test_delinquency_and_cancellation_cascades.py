"""Two four-link cascades that must be followed all the way down.

A third delinquency strike closes a plan, ejects the member, frees their beds and
rewrites three ledgers; cancelling a stop hands back rehearsal space, releases
shifts, and adjusts only the volunteer loads that were actually booked.
"""

from test_helpers import (
    Duty,
    VolunteerRoleType,
    assert_facility_agreement,
    assert_housing_assignment,
    assert_member,
    assert_payment_plan,
    assert_site_booking,
    assert_staff_assignment,
    fixtures as fx,
)


def _two_strikes_and_a_bed(api, season_id):
    """A financed, housed member carrying two delinquency strikes."""
    built = fx.financed_member(
        api,
        season_id,
        first_due_date="2027-01-15",
        tuition_amount_cents=399900,
        payment_plan_type="EXTENDED_6",
    )
    housed = fx.housed_member(
        api,
        season_id,
        check_in_date="2027-05-10",
        check_out_date="2027-05-20",
        member=built["member"],
        nightly_rate_cents=450,
        minimum_billable_beds=0,
    )
    fx.set_clock(api, "2027-02-20T00:00:00Z")
    fx.run_sweep(api, season_id)
    fx.set_clock(api, "2027-03-20T00:00:00Z")
    fx.run_sweep(api, season_id)

    plan = fx.get_plan(api, built["plan"]["id"])
    assert_payment_plan(plan, delinquency_strikes=2, late_fee_accrued_cents=5574,
                        status="DELINQUENT")
    assert_facility_agreement(
        fx.get_agreement(api, housed["agreement"]["id"]),
        occupied_bed_nights=10,
        billable_bed_nights=10,
        billable_cents=4500,
    )
    return {
        "member": built["member"],
        "plan": plan,
        "agreement": housed["agreement"],
        "school": housed["school"],
        "assignment": housed["assignment"],
    }


def test_the_third_strike_closes_the_plan_with_its_balance_intact(api):
    """Link one: the fee is still charged and the plan closes at 420596 cents.

    PRD: "Link one closes the plan: the strike count reaches 3, the late fee for
    that observation is still charged, and `status` becomes `CLOSED_WITH_BALANCE`."

    Design: Difficulty/transitive_cascade/third_delinquency_strike_cascades_plan_member_housing_and_school_ledgers
    """
    season = fx.create_season(api)
    built = _two_strikes_and_a_bed(api, season["id"])

    fx.set_clock(api, "2027-05-20T00:00:00Z")
    fx.run_sweep(api, season["id"])

    assert_payment_plan(
        fx.get_plan(api, built["plan"]["id"]),
        delinquency_strikes=3,
        late_fee_accrued_cents=10698,
        late_fee_paid_cents=0,
        principal_paid_cents=0,
        installments_due_count=5,
        due_amount_cents=341582,
        arrears_cents=341582,
        outstanding_cents=420596,
        status="CLOSED_WITH_BALANCE",
    )


def test_the_closure_ejects_the_member_and_restrikes_the_obligation(api):
    """Link two: withdrawal on the clock date, prorated across the spring window.

    PRD: "Link two, caused by link one, ejects the member: a member sitting in
    `CONTRACTED` moves `CONTRACTED → WITHDRAWN`, the member's `withdrawal_date` is
    set to the logical-clock date, the withdrawal-obligation calculation of §3.5
    runs, `tuition_charged_cents` is replaced by the resulting
    `withdrawal_obligation_cents`, and `tuition_balance_cents` and
    `refund_due_cents` are recomputed."

    Design: Difficulty/transitive_cascade/third_delinquency_strike_cascades_plan_member_housing_and_school_ledgers
    """
    season = fx.create_season(api)
    built = _two_strikes_and_a_bed(api, season["id"])

    fx.set_clock(api, "2027-05-20T00:00:00Z")
    fx.run_sweep(api, season["id"])

    assert_member(
        fx.get_member(api, built["member"]["id"]),
        membership_status="WITHDRAWN",
        withdrawal_date="2027-05-20",
        withdrawal_obligation_basis="PRORATED_SPRING",
        withdrawal_obligation_cents=136182,
        tuition_charged_cents=136182,
        tuition_paid_cents=0,
        tuition_balance_cents=136182,
        refund_due_cents=0,
    )
    assert fx.get_season(api, season["id"])["tuition_charged_cents"] == 136182


def test_the_ejection_frees_the_bed_and_zeroes_the_housing_ledgers(api):
    """Links three and four: the bed goes back and every housing figure follows.

    PRD: "Link four, caused by link three, re-runs the housing chain: each affected
    agreement recomputes `occupied_bed_nights`, `billable_bed_nights` and
    `billable_cents`, each affected host school recomputes `reserved_bed_nights`,
    and the season recomputes `housing_cost_cents`."

    Design: Difficulty/transitive_cascade/third_delinquency_strike_cascades_plan_member_housing_and_school_ledgers
    """
    season = fx.create_season(api)
    built = _two_strikes_and_a_bed(api, season["id"])

    fx.set_clock(api, "2027-05-20T00:00:00Z")
    fx.run_sweep(api, season["id"])

    assert_housing_assignment(
        fx.get_housing(api, built["assignment"]["id"]),
        status="RELEASED",
        released_reason="MEMBER_WITHDRAWN",
        nights=10,
    )
    assert_facility_agreement(
        fx.get_agreement(api, built["agreement"]["id"]),
        status="SIGNED",
        occupied_bed_nights=0,
        billable_bed_nights=0,
        billable_cents=0,
    )
    assert fx.get_school(api, built["school"]["id"])["reserved_bed_nights"] == 0
    closed_season = fx.get_season(api, season["id"])
    assert closed_season["housing_cost_cents"] == 0
    assert closed_season["billing_epoch"] == 3


# ---------------------------------------- cancelling a stop, three cascade links
SHOW_STOP = {
    "venue_name": "Cedar Rapids Bowl",
    "city": "Cedar Rapids",
    "state_code": "IA",
    "arrive_at": "2027-06-20T12:00:00Z",
    "depart_at": "2027-06-20T23:30:00Z",
    "show_start_at": "2027-06-20T20:00:00Z",
    "travel_miles_from_previous": 0,
    "truck_count": 4,
    "rehearsal_minutes": 120,
    "heat_index_f": 82,
}


def _confirmed_stop_with_blocks_and_shifts(api, season_id):
    """A confirmed stop holding two blocks, one approved shift and one proposal."""
    rockford = fx.signed_agreement_with_school(
        api, season_id, usage_type="TOUR_REHEARSAL",
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL", "sleeping_space_count": 30,
                          "capacity_per_space": 12, "rehearsal_field_count": 2,
                          "has_air_conditioning": True},
        start_date="2027-06-18", end_date="2027-06-25",
        nightly_rate_cents=400, minimum_billable_beds=0,
    )
    dubuque = fx.signed_agreement_with_school(
        api, season_id, usage_type="TOUR_REHEARSAL",
        school_overrides={"name": "Dubuque Senior High School", "city": "Dubuque",
                          "state_code": "IA", "sleeping_space_count": 20,
                          "capacity_per_space": 10, "rehearsal_field_count": 1,
                          "has_air_conditioning": False},
        start_date="2027-06-18", end_date="2027-06-25",
        nightly_rate_cents=400, minimum_billable_beds=0,
    )
    stop = fx.create_stop(api, season_id, **SHOW_STOP)
    block_a = fx.create_booking(api, stop["id"], rockford["school"]["id"],
                                rockford["agreement"]["id"],
                                "2027-06-19T14:00:00Z", "2027-06-19T18:00:00Z",
                                indoor=False)
    block_b = fx.create_booking(api, stop["id"], dubuque["school"]["id"],
                                dubuque["agreement"]["id"],
                                "2027-06-20T08:00:00Z", "2027-06-20T11:00:00Z",
                                indoor=False)

    driver = fx.screened_volunteer(api, VolunteerRoleType.DRIVER, "2026-08-01",
                                   full_name="Sam Herrera", cdl_number="IL-CDL-88213")
    drive_shift = fx.approved_shift(api, driver["id"], stop["id"], Duty.DRIVE,
                                    "2027-06-20T12:00:00Z", "2027-06-20T20:00:00Z")
    chaperone = fx.screened_volunteer(api, VolunteerRoleType.CHAPERONE, "2026-08-01",
                                      full_name="Nia Foster")
    chaperone_shift = fx.propose_shift(api, chaperone["id"], stop["id"], Duty.CHAPERONE,
                                       "2027-06-20T12:00:00Z", "2027-06-20T22:00:00Z")

    fx.confirm_stop(api, stop["id"])
    assert_site_booking(fx.get_booking(api, block_a["id"]), status="CONFIRMED")
    assert_site_booking(fx.get_booking(api, block_b["id"]), status="CONFIRMED")
    assert fx.get_school(api, rockford["school"]["id"])["booked_block_count"] == 1
    assert fx.get_school(api, dubuque["school"]["id"])["booked_block_count"] == 1
    assert fx.get_volunteer(api, driver["id"])["assignment_count"] == 1
    assert fx.get_volunteer(api, chaperone["id"])["assignment_count"] == 0
    return {
        "stop": stop,
        "schools": [rockford["school"], dubuque["school"]],
        "blocks": [block_a, block_b],
        "driver": driver,
        "chaperone": chaperone,
        "drive_shift": drive_shift,
        "chaperone_shift": chaperone_shift,
    }


def test_cancelling_a_confirmed_stop_hands_every_block_back(api):
    """Links one and two: blocks release and each school's count drops.

    PRD: "The first cascade link releases rehearsal space: every rehearsal block on
    the stop whose `status` is `HELD` or `CONFIRMED` moves to `RELEASED` with
    `released_reason` `STOP_CANCELLED`. The second link, caused by the first,
    decrements each affected school's `booked_block_count` once per released block."

    Design: Difficulty/transitive_cascade/tour_stop_cancellation_cascades_bookings_school_counts_and_volunteer_loads
    """
    season = fx.create_season(api)
    built = _confirmed_stop_with_blocks_and_shifts(api, season["id"])

    cancelled = fx.cancel_stop(api, built["stop"]["id"], reason="venue lost its permit")
    assert cancelled["status"] == "CANCELLED"

    for block in built["blocks"]:
        assert_site_booking(
            fx.get_booking(api, block["id"]),
            status="RELEASED",
            released_reason="STOP_CANCELLED",
        )
    for school in built["schools"]:
        assert fx.get_school(api, school["id"])["booked_block_count"] == 0


def test_cancelling_releases_shifts_but_only_unwinds_approved_loads(api):
    """Link three: both shifts release, and only the approved one decrements.

    PRD: "The third releases people: every shift on the stop whose `status` is
    `PROPOSED`, `ACCEPTED` or `APPROVED` moves to `RELEASED` with `released_reason`
    `STOP_CANCELLED`, and for each shift that was `APPROVED` at the moment of
    release, that volunteer's `assignment_count` is decremented by one — shifts that
    never reached approval never contributed to the count and so do not decrement
    it."

    Design: Difficulty/transitive_cascade/tour_stop_cancellation_cascades_bookings_school_counts_and_volunteer_loads
    """
    season = fx.create_season(api)
    built = _confirmed_stop_with_blocks_and_shifts(api, season["id"])

    fx.cancel_stop(api, built["stop"]["id"], reason="venue lost its permit")

    assert_staff_assignment(
        fx.get_shift(api, built["drive_shift"]["id"]),
        status="RELEASED",
        released_reason="STOP_CANCELLED",
        duty=Duty.DRIVE,
    )
    assert_staff_assignment(
        fx.get_shift(api, built["chaperone_shift"]["id"]),
        status="RELEASED",
        released_reason="STOP_CANCELLED",
        duty=Duty.CHAPERONE,
    )
    assert fx.get_volunteer(api, built["driver"]["id"])["assignment_count"] == 0
    assert fx.get_volunteer(api, built["chaperone"]["id"])["assignment_count"] == 0


def test_the_cancellation_cascade_stops_short_of_the_screening_records(api):
    """Screenings are untouched: the cascade never reaches the fourth hop.

    PRD: "A clearance moves the volunteer `PENDING → CLEARED` and computes
    `screening_expires_on` as `screening_decided_on` advanced by three hundred and
    sixty-five days."

    Design: Difficulty/transitive_cascade/tour_stop_cancellation_cascades_bookings_school_counts_and_volunteer_loads
    """
    season = fx.create_season(api)
    built = _confirmed_stop_with_blocks_and_shifts(api, season["id"])

    fx.cancel_stop(api, built["stop"]["id"], reason="venue lost its permit")

    for volunteer_id in (built["driver"]["id"], built["chaperone"]["id"]):
        volunteer = fx.get_volunteer(api, volunteer_id)
        assert volunteer["screening_status"] == "CLEARED"
        assert volunteer["screening_decided_on"] == "2026-08-01"
        assert volunteer["screening_expires_on"] == "2027-08-01"
