"""Requests that break two rules at once, where only the higher-ranked refusal
may be reported: a confirmation of a cancelled rental that is also short its
deposit, and a crew call that both escapes the engagement's window and
oversubscribes the local.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    assess_risk,
    book_presented_engagement,
    book_rental_engagement,
    call_crew,
    cancel,
    clear_rental_rider,
    confirm,
    read_engagement,
    record_deposit,
    register_artist,
    register_hall,
    register_rental_client,
    register_union_department,
    validate_error,
    validate_paginated,
    validate_success,
)

RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]


def _two_cleared_rentals_one_of_them_cancelled() -> dict:
    """Two single-day rentals in a studio house, both riders cleared and both
    assessed LOW, neither with a cent of deposit banked; the first is then
    cancelled while still in draft."""
    space = register_hall(name="Studio Theatre", seat_capacity=400,
                         base_facility_fee_cents=500_000,
                         load_in_day_fee_cents=200_000,
                         changeover_buffer_minutes=60,
                         rigging_capacity_kg=2_000, house_power_amps=200,
                         dmx_universes=2)
    client = register_rental_client(org_name="Fifth Ward Poetry Slam",
                                   contact_email="book@fifthward.example",
                                   credit_rating="A",
                                   outstanding_balance_cents=0)
    engagements = []
    # Grade-A credit contributes 0.00 and a zero arrears ratio contributes 0.00,
    # so the whole rental score is the lead-time term: 0.20 * (1 - days/120),
    # times 100, rounded half up.  The 2 October night stands 62 whole days from
    # the 2026-08-01 logical clock (9.67 -> 10) and the 9 October night 69 whole
    # days (8.50 -> 9).
    for title, day, expected_score in (("Fifth Ward Slam Finals", "02", 10),
                                       ("Fifth Ward Slam Encore", "09", 9)):
        engagement = book_rental_engagement(
            space["id"], client["id"], title=title,
            load_in_start_utc=f"2026-10-{day}T12:00:00Z",
            performance_start_utc=f"2026-10-{day}T19:00:00Z",
            performance_end_utc=f"2026-10-{day}T22:00:00Z",
            load_out_end_utc=f"2026-10-{day}T23:30:00Z",
            performance_day_count=1, load_in_day_count=0)
        assert engagement["facility_fee_cents"] == 500_000
        assert engagement["deposit_required_cents"] == 125_000
        assert engagement["deposit_paid_cents"] == 0
        cleared = clear_rental_rider(engagement["id"], client["id"],
                                    submitted_rigging_kg=500,
                                    requested_power_amps=100,
                                    requested_dmx_universes=1)
        assert cleared["review_status"] == "CLEARED"
        assessed = assess_risk(engagement["id"])
        assert assessed["risk_score"] == expected_score
        assert assessed["risk_tier"] == "LOW"
        assert assessed["financial_clearance"] == "CLEARED"
        engagements.append(engagement)

    cancelled = cancel(engagements[0]["id"],
                       reason="Presenter withdrew before deposit")
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0
    return {"cancelled": engagements[0], "draft": engagements[1]}


def _presented_engagement_with_eight_of_a_ten_person_local_booked() -> dict:
    """A presented engagement occupying its hall from 1 October to the small hours
    of 3 October, with eight of a ten-member stagehand local already called for
    the load-in day."""
    space = register_hall()
    artist = register_artist(legal_name="Ridgeway Gospel Choir",
                            agency_name="Southgate Booking",
                            guarantee_floor_cents=100_000,
                            historical_sell_through_pct=0.65,
                            min_days_between_engagements=0)
    department = register_union_department(department="STAGEHANDS",
                                          roster_size=10,
                                          straight_hourly_rate_cents=5_000)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Ridgeway Gospel Choir",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    call = call_crew(engagement["id"], department["id"], crew_size=8,
                     call_start_utc="2026-10-01T08:00:00Z",
                     call_end_utc="2026-10-01T16:00:00Z")
    assert call["estimated_cost_cents"] == 320_000
    return {"engagement": engagement, "department": department, "call": call}


class TestConfirmStateBeforeDepositShortfall:

    def test_a_cancelled_rental_is_refused_on_its_state_not_on_its_deposit(self):
        """The cancelled booking fails two of confirmation's preconditions at
        once: it is no longer a draft and it never banked its 125,000-cent
        deposit. Only the state refusal may surface, and its 409 status
        distinguishes it from the 402 the fiscal rule would have produced. The
        refused attempt writes nothing.

        PRD: "More generally, when several checks could all reject the same
        request, only the highest-priority one is reported. The evaluation order
        is fixed and applies system-wide:"

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_check_outranks_deposit_shortfall
        """
        scenario = _two_cleared_rentals_one_of_them_cancelled()
        cancelled_id = scenario["cancelled"]["id"]

        validate_error(api_client.confirm_engagement(cancelled_id,
                                                     RENTAL_MANAGER),
                       "ERR_ENGAGEMENT_NOT_DRAFT", expected_status=409)

        after = read_engagement(cancelled_id)
        assert after["lifecycle_status"] == "CANCELLED"
        assert after["deposit_required_cents"] == 125_000
        assert after["deposit_paid_cents"] == 0

    def test_the_masked_deposit_rule_still_bites_on_the_draft_sibling(self):
        """The identical sibling is still a draft, so the fiscal rule is the only
        one left standing and refuses the confirmation with its own 402. Banking
        exactly the required amount then confirms the booking, showing the gate
        clears at equality rather than demanding a surplus.

        PRD: "For a rental engagement, `deposit_paid_cents` must be greater than
        or equal to `deposit_required_cents`, or the request is refused with
        `ERR_DEPOSIT_SHORTFALL`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_check_outranks_deposit_shortfall
        """
        scenario = _two_cleared_rentals_one_of_them_cancelled()
        draft_id = scenario["draft"]["id"]

        validate_error(api_client.confirm_engagement(draft_id, RENTAL_MANAGER),
                       "ERR_DEPOSIT_SHORTFALL", expected_status=402)
        assert read_engagement(draft_id)["lifecycle_status"] == "DRAFT"

        paid = record_deposit(draft_id, 125_000)
        assert paid["deposit_paid_cents"] == 125_000
        assert paid["deposit_required_cents"] == 125_000

        confirmed = confirm(draft_id, RENTAL_MANAGER)
        assert confirmed["lifecycle_status"] == "CONFIRMED"


class TestCallWindowBeforeCrewCapacity:

    def test_a_call_that_escapes_the_window_is_refused_on_the_window(self):
        """The requested call runs ten hours past load-out and would put thirteen
        of ten available crew on the clock during its overlap with the existing
        call. The containment rule outranks the roster rule, so the refusal is the
        422 rather than the 409, and no second call is recorded.

        PRD: "More generally, when several checks could all reject the same
        request, only the highest-priority one is reported. The evaluation order
        is fixed and applies system-wide:"

        Design: Difficulty/priority_pair_validation_conflict/labor_call_window_check_outranks_crew_capacity
        """
        scenario = _presented_engagement_with_eight_of_a_ten_person_local_booked()
        engagement_id = scenario["engagement"]["id"]

        validate_error(api_client.create_labor_call(
            engagement_id,
            {"union_department_id": scenario["department"]["id"],
             "crew_size": 5,
             "call_start_utc": "2026-10-01T12:00:00Z",
             "call_end_utc": "2026-10-03T12:00:00Z"},
            TECH_DIRECTOR), "ERR_CALL_OUTSIDE_ENGAGEMENT_WINDOW",
            expected_status=422)

        calls, meta = validate_paginated(
            api_client.list_engagement_labor_calls(engagement_id, TECH_DIRECTOR))
        assert meta["total_count"] == 1
        assert calls[0]["id"] == scenario["call"]["id"]
        assert read_engagement(engagement_id)["labor_estimate_total_cents"] == \
            320_000

    def test_the_masked_roster_rule_bites_once_the_call_sits_inside_the_window(self):
        """Pulled back inside the occupancy window the same crew of five still
        oversubscribes the local during the overlap and is refused with the 409
        the window rule had been hiding. A crew of two lands, because eight plus
        two exactly fills the roster and the rule tests for exceedance.

        PRD: "For the call's department, the system sums `crew_size` across every
        call whose `status` is `ESTIMATED` or `WORKED` and whose half-open window
        overlaps the new one, adds the new `crew_size`, and requires the total to
        be no greater than the department's `roster_size`."

        Design: Difficulty/priority_pair_validation_conflict/labor_call_window_check_outranks_crew_capacity
        """
        scenario = _presented_engagement_with_eight_of_a_ten_person_local_booked()
        engagement_id = scenario["engagement"]["id"]
        department_id = scenario["department"]["id"]

        validate_error(api_client.create_labor_call(
            engagement_id,
            {"union_department_id": department_id, "crew_size": 5,
             "call_start_utc": "2026-10-01T12:00:00Z",
             "call_end_utc": "2026-10-01T20:00:00Z"},
            TECH_DIRECTOR), "ERR_CREW_CAPACITY_EXCEEDED", expected_status=409)

        fitting = validate_success(api_client.create_labor_call(
            engagement_id,
            {"union_department_id": department_id, "crew_size": 2,
             "call_start_utc": "2026-10-01T12:00:00Z",
             "call_end_utc": "2026-10-01T13:00:00Z"},
            TECH_DIRECTOR), expected_status=201)
        assert fitting["status"] == "ESTIMATED"
        assert fitting["estimated_cost_cents"] == 40_000

        calls, meta = validate_paginated(
            api_client.list_engagement_labor_calls(engagement_id, TECH_DIRECTOR))
        assert meta["total_count"] == 2
        assert read_engagement(engagement_id)["labor_estimate_total_cents"] == \
            360_000
