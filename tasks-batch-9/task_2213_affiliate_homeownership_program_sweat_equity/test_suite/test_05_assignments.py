"""Seats: waivers, certifications, calendars, weekly capacity, strikes, releases."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, CREW_LEAD, OFFICER, make_volunteer_headers


def test_a_lapsed_waiver_outranks_the_double_booking_it_also_commits(api):
    """Two rules fire on one seat request; the waiver rule is the one reported.

    "A profile whose `waiver_expires_on` is not strictly later than the shift's
    `start_at` is refused with `ERR_WAIVER_EXPIRED`", and separately "an overlap is
    refused with `ERR_VOLUNTEER_DOUBLE_BOOKED`". The validation order of §2.6 is
    what decides: the waiver check sits above the calendar check, so the request
    for a 13:00 shift by a volunteer whose waiver died at 12:00 — and who already
    holds an 08:00-to-16:00 seat elsewhere — must report the waiver.

    Design: Difficulty/priority_pair_validation_conflict/waiver_expiry_priority_28_beats_volunteer_double_booking_priority_29
    """
    program = X.setup_program(api)
    site_a = X.setup_ready_site(api, program["id"], parcel_number="P-1001")
    site_b = X.setup_ready_site(api, program["id"], parcel_number="P-1002", street_address="14 Cedar Ln")
    volunteer = X.setup_volunteer(api, program["id"], waiver_expires_on="2026-08-10T12:00:00.000Z")

    shift_a = X.setup_open_shift(
        api,
        site_a["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T16:00:00.000Z",
        volunteer_slots=2,
    )
    shift_b = X.setup_open_shift(
        api,
        site_b["id"],
        start_at="2026-08-10T13:00:00.000Z",
        end_at="2026-08-10T17:00:00.000Z",
        volunteer_slots=2,
    )
    seat_a = X.reserve_volunteer_seat(api, shift_a["id"], volunteer["id"])
    assert seat_a["status"] == C.ASSIGNMENT_RESERVED
    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 8.0

    validate_error(
        api.create_assignment(
            F.assignment_payload(
                shift_b["id"], X.shift_version(api, shift_b["id"]), volunteer_id=volunteer["id"]
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_WAIVER_EXPIRED,
        422,
    )


def test_the_losing_double_booking_rule_leaves_no_trace_of_the_refused_seat(api):
    """The refusal is total: no seat, no hours, no version bump on the shift.

    Both candidate rules would have refused this request — the 13:00-to-17:00
    window overlaps the held 08:00-to-16:00 seat, since "a candidate overlaps a
    held seat when the candidate shift's start is strictly before the held shift's
    end and the held shift's start is strictly before the candidate shift's end" —
    yet exactly one refusal happened and it wrote nothing. "Committed volunteer
    hours are a conserved quantity."

    Design: Difficulty/priority_pair_validation_conflict/waiver_expiry_priority_28_beats_volunteer_double_booking_priority_29
    """
    program = X.setup_program(api)
    site_a = X.setup_ready_site(api, program["id"], parcel_number="P-1001")
    site_b = X.setup_ready_site(api, program["id"], parcel_number="P-1002", street_address="14 Cedar Ln")
    volunteer = X.setup_volunteer(api, program["id"], waiver_expires_on="2026-08-10T12:00:00.000Z")

    shift_a = X.setup_open_shift(
        api,
        site_a["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T16:00:00.000Z",
        volunteer_slots=2,
    )
    shift_b = X.setup_open_shift(
        api,
        site_b["id"],
        start_at="2026-08-10T13:00:00.000Z",
        end_at="2026-08-10T17:00:00.000Z",
        volunteer_slots=2,
    )
    seat_a = X.reserve_volunteer_seat(api, shift_a["id"], volunteer["id"])
    shift_b_version = X.shift_version(api, shift_b["id"])

    validate_error(
        api.create_assignment(
            F.assignment_payload(shift_b["id"], shift_b_version, volunteer_id=volunteer["id"]),
            headers=CREW_LEAD,
        ),
        E.ERR_WAIVER_EXPIRED,
        422,
    )

    assert validate_success(api.get_assignment(seat_a["id"], headers=CREW_LEAD))["status"] == C.ASSIGNMENT_RESERVED
    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 8.0

    reread_b = validate_success(api.get_shift(shift_b["id"], headers=CREW_LEAD))
    assert reread_b["confirmed_general_count"] == 0
    assert reread_b["version"] == shift_b_version
    _, meta = validate_paginated(api.list_assignments({"shift_id": shift_b["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 0


def test_back_to_back_seats_that_merely_touch_are_allowed(api):
    """A volunteer calendar is half-open, so noon can end one shift and start another.

    "Volunteer calendars use the opposite interval geometry from sites: a volunteer
    occupies a shift's window as a half-open interval from `start_at` up to but not
    including `end_at`, with **no** buffer, so back-to-back shifts that merely touch
    at an endpoint are explicitly allowed."

    Design: Difficulty/resource_temporal_overlap/overlap_volunteer_half_open_zero_buffer_back_to_back_allowed
    """
    program = X.setup_program(api)
    site_a = X.setup_ready_site(api, program["id"], parcel_number="P-1001")
    site_b = X.setup_ready_site(api, program["id"], parcel_number="P-1002", street_address="14 Cedar Ln")
    volunteer = X.setup_volunteer(
        api, program["id"], birth_date="1990-05-05T00:00:00.000Z", waiver_expires_on="2027-01-01T00:00:00.000Z"
    )

    shift_a = X.setup_open_shift(
        api,
        site_a["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T12:00:00.000Z",
        volunteer_slots=6,
    )
    shift_b = X.setup_open_shift(
        api,
        site_b["id"],
        start_at="2026-08-10T12:00:00.000Z",
        end_at="2026-08-10T16:00:00.000Z",
        volunteer_slots=6,
    )

    X.reserve_volunteer_seat(api, shift_a["id"], volunteer["id"])
    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 4.0

    abutting = validate_success(
        api.create_assignment(
            F.assignment_payload(
                shift_b["id"], X.shift_version(api, shift_b["id"]), volunteer_id=volunteer["id"]
            ),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert abutting["status"] == C.ASSIGNMENT_RESERVED
    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 8.0


def test_a_seat_overlapping_by_one_minute_is_double_booked(api):
    """One minute of genuine overlap is still an overlap.

    "A candidate overlaps a held seat when the candidate shift's start is strictly
    before the held shift's end and the held shift's start is strictly before the
    candidate shift's end; the volunteer's held seats for this purpose are those in
    `RESERVED`, `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` status, and an overlap is
    refused with `ERR_VOLUNTEER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/overlap_volunteer_half_open_zero_buffer_back_to_back_allowed
    """
    program = X.setup_program(api)
    site_a = X.setup_ready_site(api, program["id"], parcel_number="P-1001")
    site_b = X.setup_ready_site(api, program["id"], parcel_number="P-1002", street_address="14 Cedar Ln")
    site_c = X.setup_ready_site(api, program["id"], parcel_number="P-1003", street_address="16 Cedar Ln")
    volunteer = X.setup_volunteer(
        api, program["id"], birth_date="1990-05-05T00:00:00.000Z", waiver_expires_on="2027-01-01T00:00:00.000Z"
    )

    shift_a = X.setup_open_shift(
        api,
        site_a["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T12:00:00.000Z",
        volunteer_slots=6,
    )
    shift_b = X.setup_open_shift(
        api,
        site_b["id"],
        start_at="2026-08-10T12:00:00.000Z",
        end_at="2026-08-10T16:00:00.000Z",
        volunteer_slots=6,
    )
    shift_c = X.setup_open_shift(
        api,
        site_c["id"],
        start_at="2026-08-10T11:59:00.000Z",
        end_at="2026-08-10T15:59:00.000Z",
        volunteer_slots=6,
    )

    X.reserve_volunteer_seat(api, shift_a["id"], volunteer["id"])
    X.reserve_volunteer_seat(api, shift_b["id"], volunteer["id"])

    validate_error(
        api.create_assignment(
            F.assignment_payload(
                shift_c["id"], X.shift_version(api, shift_c["id"]), volunteer_id=volunteer["id"]
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_VOLUNTEER_DOUBLE_BOOKED,
        409,
    )

    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 8.0
    _, meta = validate_paginated(api.list_assignments({"shift_id": shift_c["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 0
    assert validate_success(api.get_shift(shift_c["id"], headers=CREW_LEAD))["confirmed_general_count"] == 0


def test_a_volunteer_releases_its_own_seat_and_the_counts_fall_back(api):
    """A self-release compensates in three tables and re-arms the fill gate.

    "A volunteer or the manager may also release a single seat with a
    `cancellation_reason` from `RESERVED` or `CONFIRMED`; if the seat was
    `CONFIRMED`, the shift's matching confirmed count is decremented and
    `fill_ratio` recomputed, and for a community seat the volunteer's
    `assigned_hours_committed` falls by the shift's `duration_hours`."

    Design: Corner/state_machines/volunteer_cancels_own_confirmed_seat_and_counts_fall_back
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    shift = X.setup_open_shift(api, site["id"], volunteer_slots=1)
    seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    X.confirm_seat(api, seat["id"], headers=make_volunteer_headers(volunteer["id"]))

    released = validate_success(
        api.cancel_assignment(
            seat["id"],
            F.cancellation_payload(cancellation_reason="Family emergency, cannot attend the build day"),
            headers=make_volunteer_headers(volunteer["id"]),
        )
    )
    assert released["status"] == C.ASSIGNMENT_CANCELLED

    reread_shift = validate_success(api.get_shift(shift["id"], headers=CREW_LEAD))
    assert reread_shift["status"] == C.SHIFT_OPEN
    assert reread_shift["confirmed_general_count"] == 0
    assert reread_shift["confirmed_trade_count"] == 0
    assert reread_shift["fill_ratio"] == 0

    reread_volunteer = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert reread_volunteer["assigned_hours_committed"] == 0
    assert reread_volunteer["no_show_strikes"] == 0
    assert reread_volunteer["status"] == C.VOLUNTEER_ACTIVE

    # The compensation restored the pre-confirmation gate state exactly.
    validate_error(
        api.lock_shift(shift["id"], F.lock_payload(), headers=CREW_LEAD), E.ERR_SHIFT_FILL_INSUFFICIENT, 409
    )


def test_the_weekly_ceiling_accepts_exactly_forty_hours_and_refuses_one_more(api):
    """Landing on the cap is legal; one hour past it is not.

    "The volunteer's hours already held inside that week are summed from the
    `duration_hours` of the shifts of their held seats whose `start_at` falls in
    the window, the candidate's own duration is added, the total is rounded half-up
    to two decimal places, and it may not exceed 40.00 hours for an adult or 16.00
    hours for a minor — landing exactly on the ceiling is accepted, one hundredth of
    an hour past it is refused with `ERR_VOLUNTEER_WEEKLY_CAP_EXCEEDED`."

    Design: Corner/calculations/weekly_volunteer_cap_accepts_exactly_forty_hours_then_refuses_one_more
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")

    long_days = []
    for day in ("03", "04", "05", "06"):
        long_days.append(
            X.setup_open_shift(
                api,
                site["id"],
                start_at="2026-08-{}T08:00:00.000Z".format(day),
                end_at="2026-08-{}T18:00:00.000Z".format(day),
                volunteer_slots=2,
            )
        )
    friday_hour = X.setup_open_shift(
        api,
        site["id"],
        start_at="2026-08-07T08:00:00.000Z",
        end_at="2026-08-07T09:00:00.000Z",
        volunteer_slots=2,
    )

    for shift in long_days[:3]:
        X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 30.0

    fourth = validate_success(
        api.create_assignment(
            F.assignment_payload(
                long_days[3]["id"], X.shift_version(api, long_days[3]["id"]), volunteer_id=volunteer["id"]
            ),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert fourth["status"] == C.ASSIGNMENT_RESERVED
    at_the_cap = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert at_the_cap["assigned_hours_committed"] == 40.0
    assert at_the_cap["status"] == C.VOLUNTEER_ACTIVE

    # The one-hour Friday shift overlaps nothing, so only the weekly ceiling can refuse it.
    validate_error(
        api.create_assignment(
            F.assignment_payload(
                friday_hour["id"], X.shift_version(api, friday_hour["id"]), volunteer_id=volunteer["id"]
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_VOLUNTEER_WEEKLY_CAP_EXCEEDED,
        422,
    )

    seats, meta = validate_paginated(api.list_assignments({"volunteer_id": volunteer["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 4
    assert all(seat["status"] == C.ASSIGNMENT_RESERVED for seat in seats)


def test_a_trade_seat_needs_a_matching_unexpired_certification(api):
    """The certification rule fires on the skilled role only, and matches the trade.

    "A `SKILLED_TRADE` seat requires the volunteer to hold a certification whose
    `trade` matches the shift's `required_trade` and whose `expires_on` is strictly
    later than the shift's `end_at`, or it is refused with
    `ERR_TRADE_CERTIFICATION_INVALID`."

    Design: Corner/validations/a_trade_seat_requires_a_matching_unexpired_certification
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    vol_none = X.setup_volunteer(api, program["id"], full_name="Uma Novak", birth_date="1990-04-10T00:00:00.000Z")
    vol_roof = X.setup_volunteer(
        api,
        program["id"],
        full_name="Rhea Ives",
        birth_date="1989-05-05T00:00:00.000Z",
        trade_certifications=[F.certification(C.TRADE_ROOFING)],
    )
    vol_plumb = X.setup_volunteer(
        api,
        program["id"],
        full_name="Pilar Sosa",
        birth_date="1987-07-07T00:00:00.000Z",
        trade_certifications=[F.certification(C.TRADE_PLUMBING)],
    )
    shift = X.setup_open_shift(
        api, site["id"], volunteer_slots=4, required_trade_slots=2, required_trade=C.TRADE_PLUMBING
    )
    version = X.shift_version(api, shift["id"])

    validate_error(
        api.create_assignment(
            F.assignment_payload(
                shift["id"], version, role=C.SEAT_SKILLED_TRADE, volunteer_id=vol_none["id"]
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_TRADE_CERTIFICATION_INVALID,
        422,
    )
    validate_error(
        api.create_assignment(
            F.assignment_payload(
                shift["id"], version, role=C.SEAT_SKILLED_TRADE, volunteer_id=vol_roof["id"]
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_TRADE_CERTIFICATION_INVALID,
        422,
    )

    # The very same uncertified volunteer is welcome on a general seat.
    general = validate_success(
        api.create_assignment(
            F.assignment_payload(shift["id"], version, volunteer_id=vol_none["id"]), headers=CREW_LEAD
        ),
        201,
    )
    assert general["role"] == C.SEAT_GENERAL
    assert general["status"] == C.ASSIGNMENT_RESERVED

    trade = validate_success(
        api.create_assignment(
            F.assignment_payload(
                shift["id"],
                X.shift_version(api, shift["id"]),
                role=C.SEAT_SKILLED_TRADE,
                volunteer_id=vol_plumb["id"],
            ),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert trade["role"] == C.SEAT_SKILLED_TRADE
    assert trade["status"] == C.ASSIGNMENT_RESERVED


def test_the_third_no_show_suspends_the_profile_and_bars_the_next_seat(api):
    """Suspension accrues from attendance; nobody sets it.

    "Every seat still in `CONFIRMED` status — confirmed but never checked in —
    becomes `NO_SHOW` and raises its volunteer's `no_show_strikes` by 1; a profile
    reaching 3 strikes flips to `SUSPENDED`." Thereafter "a profile whose `status`
    is `SUSPENDED` may hold no new reservation and is refused with
    `ERR_VOLUNTEER_SUSPENDED`".

    Design: Corner/validations/three_no_shows_suspend_a_volunteer_and_bar_the_next_seat
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")

    shifts = []
    seats = []
    for day in ("03", "04", "05"):
        shift = X.setup_open_shift(
            api,
            site["id"],
            start_at="2026-08-{}T08:00:00.000Z".format(day),
            end_at="2026-08-{}T09:00:00.000Z".format(day),
            volunteer_slots=1,
        )
        seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
        X.confirm_seat(api, seat["id"], headers=make_volunteer_headers(volunteer["id"]))
        X.lock_shift(api, shift["id"], safety_briefing_reference="SB-2026-08-{}".format(day))
        shifts.append(shift)
        seats.append(seat)
    spare = X.setup_open_shift(
        api,
        site["id"],
        start_at="2026-08-06T08:00:00.000Z",
        end_at="2026-08-06T09:00:00.000Z",
        volunteer_slots=1,
    )
    spare_version = X.shift_version(api, spare["id"])

    X.advance_clock(api, "2026-08-03T09:00:00.000Z")
    X.complete_shift(api, shifts[0]["id"])
    after_one = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert after_one["no_show_strikes"] == 1
    assert after_one["status"] == C.VOLUNTEER_ACTIVE

    X.advance_clock(api, "2026-08-04T09:00:00.000Z")
    X.complete_shift(api, shifts[1]["id"])
    X.advance_clock(api, "2026-08-05T09:00:00.000Z")
    X.complete_shift(api, shifts[2]["id"])

    after_three = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert after_three["no_show_strikes"] == 3
    assert after_three["status"] == C.VOLUNTEER_SUSPENDED

    validate_error(
        api.create_assignment(
            F.assignment_payload(spare["id"], spare_version, volunteer_id=volunteer["id"]), headers=CREW_LEAD
        ),
        E.ERR_VOLUNTEER_SUSPENDED,
        422,
    )

    first_seat = validate_success(api.get_assignment(seats[0]["id"], headers=CREW_LEAD))
    assert first_seat["status"] == C.ASSIGNMENT_NO_SHOW
    assert first_seat["checked_in_at"] is None


def test_general_seats_are_capped_while_partner_seats_need_the_site_link(api):
    """The same rule, two seat economies.

    "General seats may not exceed `volunteer_slots` ... exceeding either allowance
    is refused with `ERR_SHIFT_ROLE_FULL`. Partner-family seats are unlimited in
    number but must name a `household_member_id` whose household is the
    `assigned_household_id` of the shift's build site, or the reservation is refused
    with `ERR_PARTNER_MEMBER_NOT_ON_SITE`."

    Design: Corner/validations/general_seats_fill_while_partner_seats_need_a_site_assignment
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    assert site["assigned_household_id"] is None

    built = X.setup_selected_household(api, program["id"])
    household_a, member_a = built["household"], built["members"][0]
    household_b = X.setup_household(
        api,
        program["id"],
        household_name="Boone",
        household_size=2,
        habitability_deficiency_count=1,
        self_reported_annual_income_cents=3_000_000,
        self_reported_housing_cost_cents=100_000,
        monthly_debt_payment_cents=20_000,
        credit_score=620,
        on_time_housing_payment_months=12,
    )
    member_b = X.add_member(
        api, household_b["id"], full_name="Ben Boone", birth_date="1988-11-11T00:00:00.000Z"
    )

    vol_1 = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    vol_2 = X.setup_volunteer(api, program["id"], full_name="Omar Vance", birth_date="1991-02-02T00:00:00.000Z")
    shift = X.setup_open_shift(api, site["id"], volunteer_slots=1)
    seat_1 = X.reserve_volunteer_seat(api, shift["id"], vol_1["id"])
    X.confirm_seat(api, seat_1["id"], headers=make_volunteer_headers(vol_1["id"]))

    version = X.shift_version(api, shift["id"])
    validate_error(
        api.create_assignment(
            F.assignment_payload(shift["id"], version, volunteer_id=vol_2["id"]), headers=CREW_LEAD
        ),
        E.ERR_SHIFT_ROLE_FULL,
        409,
    )
    validate_error(
        api.create_assignment(
            F.assignment_payload(
                shift["id"],
                version,
                role=C.SEAT_HOMEOWNER_PARTNER,
                household_member_id=member_b["id"],
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_PARTNER_MEMBER_NOT_ON_SITE,
        409,
    )

    X.setup_draft_application(api, household_a["id"], site["id"], headers=OFFICER)
    assert (
        validate_success(api.get_build_site(site["id"], headers=ADMIN))["assigned_household_id"]
        == household_a["id"]
    )

    partner_seat = validate_success(
        api.create_assignment(
            F.assignment_payload(
                shift["id"],
                X.shift_version(api, shift["id"]),
                role=C.SEAT_HOMEOWNER_PARTNER,
                household_member_id=member_a["id"],
            ),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert partner_seat["role"] == C.SEAT_HOMEOWNER_PARTNER
    assert partner_seat["status"] == C.ASSIGNMENT_RESERVED
