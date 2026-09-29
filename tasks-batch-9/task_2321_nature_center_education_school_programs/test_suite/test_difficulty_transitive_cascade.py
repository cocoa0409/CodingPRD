"""Depth tests for the two long withdrawal cascades of the Nature Center Education API.

The first cascade starts at a wildlife permit and has to reach the trail visitor
counter; the second starts at a no-show and has to reach the funder's ledger.
Each test walks one group of hops and asserts what that hop left behind.
"""

from test_helpers import (
    BC,
    GO,
    SM,
    api_client,
    apply_for_aid,
    assert_fund_ledger_conserved,
    assert_version_incremented,
    assign_resources,
    confirm_booking,
    create_booking,
    create_cleared_educator,
    create_fund,
    create_permitted_animal,
    create_published_offering,
    create_school,
    create_trail_segment,
    get_success_data,
    refresh_aid_application,
    refresh_animal,
    refresh_booking,
    refresh_fund,
    refresh_permit,
    refresh_school,
    refresh_trail_segment,
    set_clock,
    setup_school_with_strikes,
    validate_success,
)

# ======================================================================
# Local composite setups
# ======================================================================


def _setup_confirmed_booking_with_animal_and_trail() -> dict:
    """A CONFIRMED booking for 20 students and 3 chaperones on an offering that needs
    both a live animal ambassador and a trail segment, so the confirmation has committed
    23 trail visitors and 120 projected exposure minutes.
    """
    set_clock()
    animal_bundle = create_permitted_animal()
    trail = create_trail_segment(weekly_visitor_budget_persons=30)
    offering = create_published_offering(
        title="Owls of the Oxbow",
        requires_live_animal=True,
        requires_trail_segment=True,
        slug_prefix="owl",
    )
    school = create_school()
    staffing = create_cleared_educator(handling_tier="TIER_1")
    booking = create_booking(
        school["id"], offering["id"], student_count=20, chaperone_count=3
    )
    assign_resources(
        booking["id"],
        lead_educator_id=staffing["educator"]["id"],
        trail_segment_id=trail["id"],
        animal_id=animal_bundle["animal"]["id"],
    )
    booking = confirm_booking(booking["id"])
    return {
        "permit": refresh_permit(animal_bundle["permit"]["id"]),
        "animal": refresh_animal(animal_bundle["animal"]["id"]),
        "trail_segment": refresh_trail_segment(trail["id"]),
        "offering": offering,
        "school": school,
        "booking": booking,
    }


def _setup_probation_school_with_approved_aid() -> dict:
    """A school already carrying one no-show strike, with two bookings still REQUESTED,
    one of which has an approved award drawing on an OPEN funder pool.
    """
    scenario = setup_school_with_strikes(strikes=1, extra_requested_bookings=2)
    funded_booking, trigger_booking = scenario["requested_bookings"]
    fund = create_fund()
    aid = apply_for_aid(funded_booking["id"], fund["id"], 33300, 6500)
    get_success_data(
        api_client.review_aid_application(aid["id"], {"decision": "APPROVE"}, GO)
    )
    return {
        "school": refresh_school(scenario["school"]["id"]),
        "fund": refresh_fund(fund["id"]),
        "aid_application": refresh_aid_application(aid["id"]),
        "funded_booking": refresh_booking(funded_booking["id"]),
        "trigger_booking": refresh_booking(trigger_booking["id"]),
    }


# ======================================================================
# Permit lapse → animal blocked → booking reverted → capacity released
# ======================================================================


class TestPermitLapseCascade:
    def test_lapsing_the_permit_blocks_every_animal_it_covers(self, api):
        """PRD §2.10: "Moving a permit from `ACTIVE` to `LAPSED` or to `SUSPENDED` recomputes every animal ambassador under that permit so that its `welfare_posture` becomes `BLOCKED` and its `effective_contact_rule` becomes `NO_PUBLIC_CONTACT`."

        Design: Difficulty/transitive_cascade/permit_lapse_blocks_animal_reverts_booking_releases_trail_capacity
        """
        scenario = _setup_confirmed_booking_with_animal_and_trail()
        assert scenario["animal"]["welfare_posture"] == "OPEN"

        lapsed = validate_success(
            api.set_permit_status(
                scenario["permit"]["id"],
                {"status": "LAPSED", "note": "Annual renewal not filed"},
                SM,
            )
        )
        assert lapsed["status"] == "LAPSED"

        animal = refresh_animal(scenario["animal"]["id"])
        assert animal["welfare_posture"] == "BLOCKED"
        assert animal["effective_contact_rule"] == "NO_PUBLIC_CONTACT"

    def test_blocked_animal_reverts_the_confirmed_booking_and_clears_its_resources(self, api):
        """PRD §2.10: "Because those animals are now blocked, every booking that references them with `delivery_status` of `CONFIRMED` reverts to `REQUESTED` with both `animal_id` and `trail_segment_id` cleared and `resource_release_reason` set to `PERMIT_LAPSE`; and because those bookings left `CONFIRMED`, the trail visitor counter and the animal's projected exposure counter are both decremented."

        Design: Difficulty/transitive_cascade/permit_lapse_blocks_animal_reverts_booking_releases_trail_capacity
        """
        scenario = _setup_confirmed_booking_with_animal_and_trail()
        assert scenario["booking"]["delivery_status"] == "CONFIRMED"

        validate_success(
            api.set_permit_status(
                scenario["permit"]["id"],
                {"status": "LAPSED", "note": "Annual renewal not filed"},
                SM,
            )
        )

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["delivery_status"] == "REQUESTED"
        assert booking["animal_id"] is None
        assert booking["trail_segment_id"] is None
        assert booking["resource_release_reason"] == "PERMIT_LAPSE"

    def test_lapsing_the_permit_releases_the_trail_visitors_and_projected_exposure(self, api):
        """PRD §2.10: "`TrailSegment.visitors_this_week` is decreased by the booking's `student_count` plus `chaperone_count` when a trail segment was attached, and `AnimalAmbassador.projected_exposure_minutes_7d` is decreased by the offering's `duration_minutes` when an animal was attached."

        Design: Difficulty/transitive_cascade/permit_lapse_blocks_animal_reverts_booking_releases_trail_capacity
        """
        scenario = _setup_confirmed_booking_with_animal_and_trail()
        assert scenario["trail_segment"]["visitors_this_week"] == 23
        assert scenario["animal"]["projected_exposure_minutes_7d"] == 120

        validate_success(
            api.set_permit_status(
                scenario["permit"]["id"],
                {"status": "LAPSED", "note": "Annual renewal not filed"},
                SM,
            )
        )

        assert refresh_trail_segment(scenario["trail_segment"]["id"])["visitors_this_week"] == 0
        assert refresh_animal(scenario["animal"]["id"])["projected_exposure_minutes_7d"] == 0

    def test_lapsing_the_permit_mutates_booking_trail_and_animal_alike(self, api):
        """PRD §2.10: "Each touched resource is a genuine mutation: `updated_at` is refreshed and `version` is incremented on the booking, on the trail segment and on the animal alike."

        Design: Difficulty/transitive_cascade/permit_lapse_blocks_animal_reverts_booking_releases_trail_capacity
        """
        scenario = _setup_confirmed_booking_with_animal_and_trail()
        booking_before = scenario["booking"]
        trail_before = scenario["trail_segment"]
        animal_before = scenario["animal"]

        # Timestamps are stamped from the logical clock (PRD §2.5), so the clock is
        # moved forward — inside the same ISO program week and still ahead of the
        # booking's start — before the cascade runs, making "refreshed" observable.
        set_clock("2026-09-28T09:30:00Z")

        validate_success(
            api.set_permit_status(
                scenario["permit"]["id"],
                {"status": "LAPSED", "note": "Annual renewal not filed"},
                SM,
            )
        )

        booking_after = refresh_booking(booking_before["id"])
        trail_after = refresh_trail_segment(trail_before["id"])
        animal_after = refresh_animal(animal_before["id"])

        assert_version_incremented(booking_after["version"], booking_before["version"])
        assert_version_incremented(trail_after["version"], trail_before["version"])
        assert_version_incremented(animal_after["version"], animal_before["version"])
        assert booking_after["updated_at"] > booking_before["updated_at"]
        assert trail_after["updated_at"] > trail_before["updated_at"]
        assert animal_after["updated_at"] > animal_before["updated_at"]


# ======================================================================
# No-show → school suspended → requests cancelled → award revoked
# ======================================================================


class TestNoShowSuspensionCascade:
    def test_second_no_show_writes_the_booking_off_and_suspends_the_school(self, api):
        """PRD §3.7: "This is reachable from `REQUESTED` and from `CONFIRMED` alike, and both branches set `delivery_status` to `NO_SHOW`, set `final_gross_fee_cents` and `net_due_cents` to the flat no-show fee of 7,500 cents, set `funding_status` to `WRITTEN_OFF`, set `resource_release_reason` to `NO_SHOW`, increment the school's `no_show_strikes` and recompute `SchoolPartner.status`."

        Design: Difficulty/transitive_cascade/no_show_strike_suspends_school_cancels_requests_revokes_aid_and_frees_fund
        """
        scenario = _setup_probation_school_with_approved_aid()
        assert scenario["school"]["no_show_strikes"] == 1
        assert scenario["school"]["status"] == "PROBATION"

        no_showed = validate_success(
            api.no_show_booking(
                scenario["trigger_booking"]["id"], {"note": "Second missed visit"}, BC
            )
        )

        assert no_showed["delivery_status"] == "NO_SHOW"
        assert no_showed["funding_status"] == "WRITTEN_OFF"
        assert no_showed["net_due_cents"] == 7500

        school = refresh_school(scenario["school"]["id"])
        assert school["no_show_strikes"] == 2
        assert school["status"] == "SUSPENDED"

    def test_suspension_cancels_the_schools_other_requested_booking(self, api):
        """PRD §2.10: "If the school reaches suspension, every other booking of that school still sitting at `REQUESTED` transitions to `CANCELLED` with `resource_release_reason` set to `SCHOOL_SUSPENSION`; and because those bookings are now cancelled, every aid application on them whose status is `APPROVED` or `PARTIALLY_APPROVED` transitions to `REVOKED`, the awarded amounts are reset to zero, the fund's `committed_cents`, `transport_awarded_cents` and `available_cents` are recomputed, and each affected booking's `aid_amount_cents` and `net_due_cents` fall back to 0."

        Design: Difficulty/transitive_cascade/no_show_strike_suspends_school_cancels_requests_revokes_aid_and_frees_fund
        """
        scenario = _setup_probation_school_with_approved_aid()
        assert scenario["funded_booking"]["delivery_status"] == "REQUESTED"

        validate_success(
            api.no_show_booking(
                scenario["trigger_booking"]["id"], {"note": "Second missed visit"}, BC
            )
        )

        cancelled = refresh_booking(scenario["funded_booking"]["id"])
        assert cancelled["delivery_status"] == "CANCELLED"
        assert cancelled["resource_release_reason"] == "SCHOOL_SUSPENSION"
        assert cancelled["aid_amount_cents"] == 0
        assert cancelled["net_due_cents"] == 0

    def test_cascaded_cancellation_revokes_the_award_and_frees_the_pool(self, api):
        """PRD §2.10: "If the school reaches suspension, every other booking of that school still sitting at `REQUESTED` transitions to `CANCELLED` with `resource_release_reason` set to `SCHOOL_SUSPENSION`; and because those bookings are now cancelled, every aid application on them whose status is `APPROVED` or `PARTIALLY_APPROVED` transitions to `REVOKED`, the awarded amounts are reset to zero, the fund's `committed_cents`, `transport_awarded_cents` and `available_cents` are recomputed, and each affected booking's `aid_amount_cents` and `net_due_cents` fall back to 0."

        Design: Difficulty/transitive_cascade/no_show_strike_suspends_school_cancels_requests_revokes_aid_and_frees_fund
        """
        scenario = _setup_probation_school_with_approved_aid()
        assert scenario["aid_application"]["status"] == "PARTIALLY_APPROVED"
        assert scenario["aid_application"]["awarded_scholarship_cents"] == 28800
        assert scenario["aid_application"]["awarded_transport_cents"] == 6500
        assert scenario["fund"]["committed_cents"] == 35300

        validate_success(
            api.no_show_booking(
                scenario["trigger_booking"]["id"], {"note": "Second missed visit"}, BC
            )
        )

        aid = refresh_aid_application(scenario["aid_application"]["id"])
        assert aid["status"] == "REVOKED"
        assert aid["awarded_scholarship_cents"] == 0
        assert aid["awarded_transport_cents"] == 0

        fund = refresh_fund(scenario["fund"]["id"])
        assert fund["committed_cents"] == 0
        assert fund["pending_cents"] == 0
        assert fund["available_cents"] == 5000000
        assert_fund_ledger_conserved(fund)
