"""Depth tests: quantities that must be conserved across a forward operation and
its compensation.

One family follows funder cents through an award and its revocation; the other
follows trail persons through a confirmation and its cancellation. Each family
captures the ledger before and after each leg.
"""

from test_helpers import (
    assert_fund_ledger_conserved,
    refresh_aid_application,
    refresh_booking,
    refresh_fund,
    refresh_trail_segment,
    setup_booking_with_approved_aid,
    setup_booking_with_submitted_aid,
    setup_trail_booking_scenario,
    validate_success,
)

_TRAIL_OVERRIDES = {
    "name": "Oxbow Loop",
    "capacity_persons": 40,
    "habitat_sensitivity": "LOW",
    "weekly_visitor_budget_persons": 30,
    "recovery_buffer_minutes": 30,
}


class TestFundCentsConservedAcrossAwardAndRevocation:
    def test_fund_ledger_across_the_aid_approval(self, api, grants_officer_headers):
        """PRD §3.8: "And `available_cents` is `total_cents` less `pending_cents` less `committed_cents` less `disbursed_cents`."

        Design: Difficulty/compensating_invariant/fund_cents_conserved_across_aid_approval_then_booking_cancellation
        """
        scenario = setup_booking_with_submitted_aid()
        fund_before = scenario["fund"]
        aid = scenario["aid_application"]

        assert fund_before["total_cents"] == 5000000
        assert fund_before["committed_cents"] == 0
        assert fund_before["disbursed_cents"] == 0
        assert fund_before["transport_awarded_cents"] == 0
        assert (
            fund_before["pending_cents"]
            == aid["requested_scholarship_cents"] + aid["requested_transport_cents"]
        )
        assert_fund_ledger_conserved(fund_before)

        decided = validate_success(
            api.review_aid_application(
                aid["id"], {"decision": "APPROVE"}, grants_officer_headers
            )
        )
        assert decided["status"] == "PARTIALLY_APPROVED"
        assert decided["awarded_scholarship_cents"] == 28800
        assert decided["awarded_transport_cents"] == 6500

        fund_after = refresh_fund(fund_before["id"])
        assert fund_after["total_cents"] == 5000000
        assert fund_after["pending_cents"] == 0
        assert fund_after["committed_cents"] == 35300
        assert fund_after["disbursed_cents"] == 0
        assert fund_after["transport_awarded_cents"] == 6500
        assert fund_after["available_cents"] == 4964700
        assert_fund_ledger_conserved(fund_after)

        booking_after = refresh_booking(scenario["booking"]["id"])
        assert booking_after["funding_status"] == "AID_APPROVED"

    def test_fund_ledger_across_the_cancellation_that_revokes_the_award(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.8: "Revocation is a true compensation — it reverses every ledger effect the approval had, leaving no drift — and `REVOKED` is terminal."

        Design: Difficulty/compensating_invariant/fund_cents_conserved_across_aid_approval_then_booking_cancellation
        """
        scenario = setup_booking_with_approved_aid()
        fund_before = scenario["fund"]
        aid = scenario["aid_application"]
        booking = scenario["booking"]

        assert fund_before["committed_cents"] == 35300
        assert fund_before["available_cents"] == 4964700
        assert_fund_ledger_conserved(fund_before)

        validate_success(
            api.cancel_booking(
                booking["id"],
                {"reason": "District pulled the buses"},
                booking_coordinator_headers,
            )
        )

        aid_after = refresh_aid_application(aid["id"])
        assert aid_after["status"] == "REVOKED"
        assert aid_after["awarded_scholarship_cents"] == 0
        assert aid_after["awarded_transport_cents"] == 0

        fund_after = refresh_fund(fund_before["id"])
        assert fund_after["total_cents"] == 5000000
        assert fund_after["pending_cents"] == 0
        assert fund_after["committed_cents"] == 0
        assert fund_after["disbursed_cents"] == 0
        assert fund_after["transport_awarded_cents"] == 0
        assert fund_after["available_cents"] == 5000000
        assert_fund_ledger_conserved(fund_after)

        booking_after = refresh_booking(booking["id"])
        assert booking_after["delivery_status"] == "CANCELLED"
        assert booking_after["funding_status"] == "UNFUNDED"
        assert booking_after["aid_amount_cents"] == 0
        assert booking_after["transport_subsidy_cents"] == 0
        assert booking_after["net_due_cents"] == 0


class TestTrailPersonsConservedAcrossConfirmAndCancel:
    def test_visitors_this_week_across_the_confirmation(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.5: "`visitors_this_week` is the sum of `student_count` plus `chaperone_count` over the bookings on this segment whose `delivery_status` is `CONFIRMED`, `RAIN_DIVERTED` or `DELIVERED` and whose `start_utc` falls inside the ISO program week containing the logical clock."

        Design: Difficulty/compensating_invariant/trail_weekly_visitor_persons_conserved_across_confirm_then_cancel
        """
        scenario = setup_trail_booking_scenario(
            student_count=20,
            chaperone_count=3,
            trail_overrides=_TRAIL_OVERRIDES,
        )
        trail_before = scenario["trail_segment"]
        assert trail_before["visitors_this_week"] == 0
        assert trail_before["weekly_visitor_budget_persons"] == 30

        confirmed = validate_success(
            api.confirm_booking(
                scenario["booking"]["id"], booking_coordinator_headers
            )
        )
        assert confirmed["delivery_status"] == "CONFIRMED"

        trail_after = refresh_trail_segment(trail_before["id"])
        assert trail_after["visitors_this_week"] == 23
        assert trail_after["version"] == trail_before["version"] + 1
        assert trail_after["weekly_visitor_budget_persons"] == 30

    def test_visitors_this_week_across_the_cancellation(
        self, api, booking_coordinator_headers
    ):
        """PRD §3.7: "From `CONFIRMED`, cancellation does all of that and additionally releases the committed capacity: `visitors_this_week` decreases by `student_count` plus `chaperone_count` when a trail segment was attached and `projected_exposure_minutes_7d` decreases by the offering's `duration_minutes` when an animal was attached."

        Design: Difficulty/compensating_invariant/trail_weekly_visitor_persons_conserved_across_confirm_then_cancel
        """
        scenario = setup_trail_booking_scenario(
            student_count=20,
            chaperone_count=3,
            trail_overrides=_TRAIL_OVERRIDES,
            confirm=True,
        )
        booking = scenario["booking"]
        trail_id = scenario["trail_segment"]["id"]

        trail_after_confirm = refresh_trail_segment(trail_id)
        assert trail_after_confirm["visitors_this_week"] == 23

        validate_success(
            api.cancel_booking(
                booking["id"], {"reason": "Storm forecast"}, booking_coordinator_headers
            )
        )

        booking_after = refresh_booking(booking["id"])
        assert booking_after["delivery_status"] == "CANCELLED"
        assert booking_after["resource_release_reason"] == "CANCELLED_BY_SCHOOL"

        trail_after_cancel = refresh_trail_segment(trail_id)
        assert trail_after_cancel["visitors_this_week"] == 0
        assert trail_after_cancel["weekly_visitor_budget_persons"] == 30
        assert trail_after_cancel["status"] == "OPEN"
        assert trail_after_cancel["version"] == trail_after_confirm["version"] + 1
