"""Which rule answers when a single request violates two of them at once.

Each pair is driven twice: once with both rules broken, so the earlier check in
the global order must own the response, and once with only the later rule
broken, so its own code must surface.
"""

from test_helpers import (
    ApiErrorId,
    assign_resources,
    create_aid_application_payload,
    create_booking,
    create_cleared_educator,
    create_fund,
    refresh_booking,
    refresh_fund,
    refresh_trail_segment,
    setup_booking_scenario,
    setup_trail_at_weekly_visitors,
    validate_error,
    validate_success,
)

# A segment budgeted for 30 persons a week, roomy enough at any single instant
# that instantaneous crowding never fires before the weekly budget does.
_TRAIL_OVERRIDES = {
    "capacity_persons": 60,
    "habitat_sensitivity": "LOW",
    "weekly_visitor_budget_persons": 30,
    "recovery_buffer_minutes": 30,
}


def _trail_week_at_23_persons() -> dict:
    """One confirmed 23-person booking on a segment budgeted for 30 persons a week."""
    return setup_trail_at_weekly_visitors(
        persons_per_booking=23,
        bookings_to_confirm=1,
        trail_overrides=dict(_TRAIL_OVERRIDES),
    )


def _second_trail_booking(scenario: dict, chaperone_count: int) -> dict:
    """A second REQUESTED booking for 20 students on the same segment, on a free day."""
    day = scenario["free_days"][0]
    booking = create_booking(
        scenario["school"]["id"],
        scenario["offering"]["id"],
        start_utc=f"{day}T14:00:00Z",
        end_utc=f"{day}T16:00:00Z",
        student_count=20,
        chaperone_count=chaperone_count,
    )
    staffing = create_cleared_educator()
    assign_resources(
        booking["id"],
        lead_educator_id=staffing["educator"]["id"],
        trail_segment_id=scenario["trail_segment"]["id"],
    )
    return refresh_booking(booking["id"])


def _aid_scenario(total_cents: int) -> dict:
    """A REQUESTED booking for 30 students plus a freshly opened pool of ``total_cents``."""
    scenario = setup_booking_scenario()
    scenario["fund"] = create_fund(total_cents=total_cents, transport_sublimit_pct=0.25)
    return scenario


class TestConfirmChaperoneSafetyBeatsTrailWeeklyBudget:
    """A confirmation that both understaffs chaperones and overruns the weekly budget."""

    def test_understaffed_and_over_budget_answers_chaperone_ratio(
        self, api, booking_coordinator_headers
    ):
        """PRD §2.9: "Checks are therefore evaluated in the fixed global order below, and the **first** check that fails determines the response."

        Design: Difficulty/priority_pair_validation_conflict/confirm_chaperone_safety_beats_trail_weekly_budget_constraint
        """
        scenario = _trail_week_at_23_persons()
        # 20 students on a one-adult-per-ten programme need 2 chaperones, and 23
        # already-committed persons plus 21 more would blow a 30-person budget.
        booking = _second_trail_booking(scenario, chaperone_count=1)
        assert booking["required_chaperones"] == 2
        trail_before = refresh_trail_segment(scenario["trail_segment"]["id"])
        assert trail_before["visitors_this_week"] == 23

        response = api.confirm_booking(booking["id"], booking_coordinator_headers)
        validate_error(response, ApiErrorId.ERR_CHAPERONE_RATIO_UNMET.value)

        after = refresh_booking(booking["id"])
        assert after["delivery_status"] == "REQUESTED"
        assert after["required_chaperones"] == 2
        assert after["version"] == booking["version"]

        trail = refresh_trail_segment(scenario["trail_segment"]["id"])
        assert trail["visitors_this_week"] == 23
        assert trail["version"] == trail_before["version"]

    def test_chaperone_coverage_met_answers_trail_weekly_budget(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.5: "Confirmation is refused with `ERR_TRAIL_WEEKLY_BUDGET_EXCEEDED` when that running total plus the candidate's own persons would exceed `weekly_visitor_budget_persons`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_chaperone_safety_beats_trail_weekly_budget_constraint
        """
        scenario = _trail_week_at_23_persons()
        # 2 chaperones for 20 students satisfies the ratio, so only the weekly
        # budget remains broken: 23 committed persons plus 22 more against 30.
        booking = _second_trail_booking(scenario, chaperone_count=2)
        assert booking["required_chaperones"] == 2
        trail_before = refresh_trail_segment(scenario["trail_segment"]["id"])
        assert trail_before["visitors_this_week"] == 23

        response = api.confirm_booking(booking["id"], booking_coordinator_headers)
        validate_error(response, ApiErrorId.ERR_TRAIL_WEEKLY_BUDGET_EXCEEDED.value)

        after = refresh_booking(booking["id"])
        assert after["delivery_status"] == "REQUESTED"
        assert after["version"] == booking["version"]

        trail = refresh_trail_segment(scenario["trail_segment"]["id"])
        assert trail["visitors_this_week"] == 23
        assert trail["version"] == trail_before["version"]


class TestAidCreateFundStateBeatsFundInsufficient:
    """An aid application against a frozen pool that is also too small for the ask."""

    def test_frozen_pool_and_oversized_request_answers_fund_not_open(
        self, api, booking_coordinator_headers, grants_officer_headers
    ):
        """PRD §2.9: "Checks are therefore evaluated in the fixed global order below, and the **first** check that fails determines the response."

        Design: Difficulty/priority_pair_validation_conflict/aid_create_fund_state_beats_fund_insufficient_fiscal
        """
        scenario = _aid_scenario(total_cents=20000)
        validate_success(
            api.set_scholarship_fund_status(
                scenario["fund"]["id"], {"status": "FROZEN"}, grants_officer_headers
            )
        )
        fund = refresh_fund(scenario["fund"]["id"])
        assert fund["status"] == "FROZEN"
        assert fund["available_cents"] == 20000

        response = api.create_aid_application(
            create_aid_application_payload(
                scenario["booking"]["id"],
                fund["id"],
                fund["version"],
                requested_scholarship_cents=30000,
                requested_transport_cents=0,
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_FUND_NOT_OPEN.value)

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["funding_status"] == "UNFUNDED"

        after = refresh_fund(fund["id"])
        assert after["pending_cents"] == 0
        assert after["available_cents"] == 20000
        assert after["version"] == fund["version"]

    def test_frozen_pool_with_affordable_request_answers_fund_not_open(
        self, api, booking_coordinator_headers, grants_officer_headers
    ):
        """PRD §2.9: "The referenced scholarship fund is `OPEN` — otherwise `ERR_FUND_NOT_OPEN` (409)."

        Design: Difficulty/priority_pair_validation_conflict/aid_create_fund_state_beats_fund_insufficient_fiscal
        """
        scenario = _aid_scenario(total_cents=20000)
        validate_success(
            api.set_scholarship_fund_status(
                scenario["fund"]["id"], {"status": "FROZEN"}, grants_officer_headers
            )
        )
        fund = refresh_fund(scenario["fund"]["id"])

        # 10000 cents sits well inside the pool's 20000, so only the pool's
        # status is wrong.
        response = api.create_aid_application(
            create_aid_application_payload(
                scenario["booking"]["id"],
                fund["id"],
                fund["version"],
                requested_scholarship_cents=10000,
                requested_transport_cents=0,
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_FUND_NOT_OPEN.value)

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["funding_status"] == "UNFUNDED"

        after = refresh_fund(fund["id"])
        assert after["pending_cents"] == 0
        assert after["available_cents"] == 20000

    def test_open_pool_with_oversized_request_answers_fund_insufficient(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.8: "Two fiscal gates apply at creation: the two requested amounts together must not exceed the pool's `available_cents` (`ERR_FUND_INSUFFICIENT`), and a non-zero transport request requires a strictly positive remaining transport sublimit, computed as `total_cents` multiplied by `transport_sublimit_pct` and rounded half up to whole cents, less `transport_awarded_cents` (`ERR_TRANSPORT_SUBLIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/aid_create_fund_state_beats_fund_insufficient_fiscal
        """
        scenario = _aid_scenario(total_cents=20000)
        fund = refresh_fund(scenario["fund"]["id"])
        assert fund["status"] == "OPEN"
        assert fund["available_cents"] == 20000

        response = api.create_aid_application(
            create_aid_application_payload(
                scenario["booking"]["id"],
                fund["id"],
                fund["version"],
                requested_scholarship_cents=30000,
                requested_transport_cents=0,
            ),
            booking_coordinator_headers,
        )
        validate_error(response, ApiErrorId.ERR_FUND_INSUFFICIENT.value)

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["funding_status"] == "UNFUNDED"

        after = refresh_fund(fund["id"])
        assert after["pending_cents"] == 0
        assert after["available_cents"] == 20000
        assert after["version"] == fund["version"]
