"""Pledge capture: level qualification, drive state gating, challenges, initial state."""
from test_helpers import (
    ApiErrorId,
    assert_pledge,
    capture_pledge,
    close_drive,
    create_drive,
    create_level,
    create_pledge_payload,
    create_premium,
    open_membership,
    setup_donor_membership,
    setup_station,
    setup_station_with_challenge,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLevelQualification:
    def test_level_qualification_sustainer_vs_one_time_thresholds(
            self, api, phone_volunteer_headers, coordinator_headers):
        """PRD §3.5: "The level check passes when a `SUSTAINER` pledge's
        `amount_cents` is at least the level's `min_monthly_sustainer_cents`,
        or a `ONE_TIME` pledge's annualized amount is at least the level's
        `min_annual_cents`."
        PRD §3.5: "A failure here is `ERR_LEVEL_OR_PREMIUM_INELIGIBLE` (422)."
        PRD §3.5: "A `SUSTAINER` pledge also flips the linked membership's
        `sustainer` flag to true."

        Design: Difficulty/combinatorial_formula/level_qualification_three_input_tiering
        """
        station = setup_station(level_overrides={
            "code": "BASIC", "min_annual_cents": 6000,
            "min_monthly_sustainer_cents": 500})

        # 600/month sustainer: 600 >= 500 monthly minimum — accepted even
        # though 600 * 12 = 7200 annualized is not what the check compares.
        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"],
                                  station["membership"]["id"],
                                  station["drive"]["id"],
                                  channel="WEB", kind="SUSTAINER",
                                  amount_cents=600),
            phone_volunteer_headers)
        pledge = validate_success(resp, 201)
        assert_pledge(pledge)
        assert pledge["kind"] == "SUSTAINER"
        assert pledge["payment_status"] == "PLEDGED"

        membership = validate_success(
            api.get_membership(station["membership"]["id"], coordinator_headers))
        assert membership["sustainer"] is True, (
            "SUSTAINER capture flips the membership's sustainer flag")

        # 600 one-time: 600 < 6000 annual minimum — rejected.
        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"],
                                  station["membership"]["id"],
                                  station["drive"]["id"],
                                  channel="WEB", kind="ONE_TIME",
                                  amount_cents=600),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_LEVEL_OR_PREMIUM_INELIGIBLE)

    def test_level_qualification_premium_tier_rank(
            self, api, phone_volunteer_headers):
        """PRD §3.5: "The premium check passes when no premium was selected, or
        when the level is `premium_eligible` and the level's rank is at least
        the rank of the premium's `membership_level_code` (rank by
        `min_annual_cents`, tie-break by `code` ascending). The premium must
        also be `active`. A failure here is `ERR_LEVEL_OR_PREMIUM_INELIGIBLE`
        (422)."

        Design: Difficulty/combinatorial_formula/level_qualification_three_input_tiering
        """
        station = setup_station(level_overrides={
            "code": "BASIC", "min_annual_cents": 6000,
            "min_monthly_sustainer_cents": 500})
        create_level(code="LEADERSHIP", min_annual_cents=120000,
                     min_monthly_sustainer_cents=10000)
        premium = create_premium(sku="TOUR-0001", title="Studio Tour",
                                 fair_market_value_cents=5000,
                                 membership_level_code="LEADERSHIP")

        # The donor's BASIC membership ranks below the premium's LEADERSHIP tier.
        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"],
                                  station["membership"]["id"],
                                  station["drive"]["id"],
                                  channel="PHONE", kind="ONE_TIME",
                                  amount_cents=12000,
                                  premium_id=premium["id"]),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_LEVEL_OR_PREMIUM_INELIGIBLE)

        # A LEADERSHIP membership ranks at the premium's tier — accepted.
        leadership = open_membership(station["donor"]["id"], "LEADERSHIP")
        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"], leadership["id"],
                                  station["drive"]["id"],
                                  channel="PHONE", kind="ONE_TIME",
                                  amount_cents=120000,
                                  premium_id=premium["id"]),
            phone_volunteer_headers)
        pledge = validate_success(resp, 201)
        assert pledge["fulfillment_status"] == "AWAITING_RESERVATION", (
            "no lot exists for the premium, so no automatic reservation")


class TestCapturePriorityAgainstClosedDrive:
    def test_capture_on_closed_drive_with_low_amount_state_beats_constraint(
            self, api, phone_volunteer_headers):
        """PRD §2.9: "When multiple validations could fire on the same request,
        they are evaluated in a strict priority order so that the surfaced
        error is deterministic."
        PRD §2.9: "Target resource state permits the operation (generic) →
        `ERR_INVALID_STATE` (409). Pledge capture against a drive not `ON_AIR`
        is the one exception and yields the more specific `ERR_DRIVE_NOT_OPEN`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/capture_on_closed_drive_with_low_amount_state_beats_constraint
        """
        create_level(code="BASIC", min_annual_cents=6000,
                     min_monthly_sustainer_cents=500)
        donor, membership = setup_donor_membership()
        drive = create_drive()  # stays DRAFT — never scheduled
        assert drive["status"] == "DRAFT"

        # Amount 100 is also below the 6000 level minimum, but the drive
        # state check fires earlier in the priority order.
        resp = api.create_pledge(
            create_pledge_payload(donor["id"], membership["id"], drive["id"],
                                  channel="PHONE", kind="ONE_TIME",
                                  amount_cents=100),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_DRIVE_NOT_OPEN)

        pledges, meta = validate_paginated(
            api.list_pledges(phone_volunteer_headers))
        assert meta["total_count"] == 0, "no pledge is persisted"

    def test_capture_on_closed_drive_with_met_challenge_surfaces_drive_not_open(
            self, api, phone_volunteer_headers, station_admin_headers):
        """PRD §2.9: "and a pledge capture against a closed drive with a
        challenge that is `MET` surfaces `ERR_DRIVE_NOT_OPEN`, not
        `ERR_CHALLENGE_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/capture_on_closed_drive_with_low_amount_state_beats_constraint
        """
        station = setup_station_with_challenge(sponsor_name="Acme Corp",
                                               goal_cents=100, match_cents=500)
        challenge = station["challenge"]
        # One 6000-cent pledge blows past the 100-cent goal: challenge MET.
        capture_pledge(station["donor"]["id"], station["membership"]["id"],
                       station["drive"]["id"],
                       matching_challenge_id=challenge["id"],
                       channel="PHONE", kind="ONE_TIME", amount_cents=6000)
        challenge_after = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert challenge_after["status"] == "MET"

        close_drive(station["drive"]["id"])

        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"],
                                  station["membership"]["id"],
                                  station["drive"]["id"],
                                  matching_challenge_id=challenge["id"],
                                  channel="WEB", kind="ONE_TIME",
                                  amount_cents=6000),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_DRIVE_NOT_OPEN)


class TestMatchingChallengeExactGoal:
    def test_matching_challenge_exact_goal_triggers_met(
            self, api, phone_volunteer_headers, station_admin_headers):
        """PRD §3.7: "The threshold rule fires when an `OPEN` challenge's
        `progress_cents` reaches or exceeds the `goal_cents` — a pledge landing
        exactly on the goal flips the challenge."

        Design: Difficulty/boundary_precision_check/matching_challenge_exact_goal_triggers_met
        """
        # Level minimum of 1 so the boundary-spanning 9999 + 1 split captures.
        station = setup_station_with_challenge(
            level_overrides={"code": "BASIC", "min_annual_cents": 1,
                             "min_monthly_sustainer_cents": 1},
            sponsor_name="Acme Corp", goal_cents=10000, match_cents=50000)
        challenge = station["challenge"]

        capture_pledge(station["donor"]["id"], station["membership"]["id"],
                       station["drive"]["id"],
                       matching_challenge_id=challenge["id"],
                       channel="PHONE", kind="ONE_TIME", amount_cents=9999)
        below = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert below["progress_cents"] == 9999
        assert below["status"] == "OPEN", (
            "one cent below the goal leaves the challenge OPEN")

        capture_pledge(station["donor"]["id"], station["membership"]["id"],
                       station["drive"]["id"],
                       matching_challenge_id=challenge["id"],
                       channel="WEB", kind="ONE_TIME", amount_cents=1)
        at = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert at["progress_cents"] == 10000
        assert at["status"] == "MET", (
            "progress landing exactly on the goal flips the challenge to MET")

    def test_matching_challenge_single_pledge_exactly_at_goal(
            self, api, phone_volunteer_headers, station_admin_headers):
        """PRD §3.7: "The challenge starts `OPEN` with `progress_cents` at 0."
        PRD §3.7: "The threshold rule fires when an `OPEN` challenge's
        `progress_cents` reaches or exceeds the `goal_cents` — a pledge landing
        exactly on the goal flips the challenge."

        Design: Difficulty/boundary_precision_check/matching_challenge_exact_goal_triggers_met
        """
        station = setup_station_with_challenge(
            level_overrides={"code": "BASIC", "min_annual_cents": 1000,
                             "min_monthly_sustainer_cents": 100},
            sponsor_name="Exact Match Foundation",
            goal_cents=5000, match_cents=25000)
        challenge = station["challenge"]
        fresh = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert fresh["status"] == "OPEN"
        assert fresh["progress_cents"] == 0

        capture_pledge(station["donor"]["id"], station["membership"]["id"],
                       station["drive"]["id"],
                       matching_challenge_id=challenge["id"],
                       channel="PHONE", kind="ONE_TIME", amount_cents=5000)
        after = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert after["progress_cents"] == 5000
        assert after["status"] == "MET", (
            "a single pledge equal to the goal flips the challenge")


class TestCaptureInitialStateAndReferences:
    def test_pledge_created_in_initial_state_pledged(
            self, api, phone_volunteer_headers):
        """PRD §3.5: "The pledge's `payment_status` starts at `PLEDGED`."
        PRD §3.6: "Reservation, ship, and waive operations on a pledge with no
        premium selected — one whose `fulfillment_status` is `NO_PREMIUM` or
        already `WAIVED` — are rejected with `ERR_PREMIUM_NOT_SELECTED` (422)."

        Design: Corner/state_machines/pledge_created_in_initial_state_pledged
        """
        station = setup_station()
        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"],
                                  station["membership"]["id"],
                                  station["drive"]["id"],
                                  channel="WEB", kind="ONE_TIME",
                                  amount_cents=6000),
            phone_volunteer_headers)
        pledge = validate_success(resp, 201)
        assert_pledge(pledge)
        assert pledge["payment_status"] == "PLEDGED"
        assert pledge["fulfillment_status"] == "NO_PREMIUM", (
            "a pledge with no premium selected starts at NO_PREMIUM")
        assert pledge["collected_cents"] == 0
        assert pledge["net_collected_cents"] == 0

    def test_cross_reference_membership_not_owned_by_donor(
            self, api, phone_volunteer_headers):
        """PRD §3.5: "the `membership_id` must belong to the `donor_id`; the
        `on_air_break_id`, when present, must belong to the `drive_id`; the
        `matching_challenge_id`, when present, must belong to the `drive_id`.
        Any mismatch is `ERR_CROSS_REFERENCE` (422)."

        Design: Corner/validations/cross_reference_membership_not_owned_by_donor
        """
        station = setup_station()
        donor2, membership2 = setup_donor_membership()

        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"], membership2["id"],
                                  station["drive"]["id"],
                                  channel="PHONE", kind="ONE_TIME",
                                  amount_cents=6000),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE)

    def test_error_challenge_not_open_on_pledge_capture(
            self, api, phone_volunteer_headers):
        """PRD §3.5: "A challenge reference also requires the challenge to be
        in `OPEN` status; a challenge that is `MET` or `EXPIRED` rejects with
        `ERR_CHALLENGE_NOT_OPEN` (409)."

        Design: Corner/errors/error_challenge_not_open_on_pledge_capture
        """
        station = setup_station_with_challenge(sponsor_name="Acme",
                                               goal_cents=100, match_cents=500)
        challenge = station["challenge"]
        # First pledge of 6000 >= goal 100 flips the challenge to MET.
        capture_pledge(station["donor"]["id"], station["membership"]["id"],
                       station["drive"]["id"],
                       matching_challenge_id=challenge["id"],
                       channel="PHONE", kind="ONE_TIME", amount_cents=6000)

        resp = api.create_pledge(
            create_pledge_payload(station["donor"]["id"],
                                  station["membership"]["id"],
                                  station["drive"]["id"],
                                  matching_challenge_id=challenge["id"],
                                  channel="WEB", kind="ONE_TIME",
                                  amount_cents=6000),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_CHALLENGE_NOT_OPEN)
