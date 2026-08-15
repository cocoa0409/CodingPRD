"""Declines, write-offs, compensating reversals, and drive/challenge totals."""
from test_helpers import (
    ApiErrorId,
    WRITEOFF_READY_CLOCK_ISO,
    add_break,
    advance_clock,
    assert_lot_quantity_conserved,
    capture_pledge,
    capture_and_pay,
    create_drive,
    create_level,
    create_reason_payload,
    decline_pledge_ok,
    get_drive,
    get_lot_of_premium,
    get_pledge,
    get_pledge_reservation,
    go_live_drive,
    post_payment_ok,
    schedule_drive,
    setup_donor_membership,
    setup_station,
    setup_station_with_challenge,
    validate_error,
    validate_success,
    write_off_pledge_ok,
)


class TestDeclineCompensation:
    def test_decline_restores_drive_collected_total(
            self, api, station_admin_headers):
        """PRD §3.9: "Both transitions fire the same compensating-reversal
        cascade. The drive's `pledged_cents` decrements by the pledge's
        `amount_cents`. The drive's `collected_cents` decrements by the
        pledge's `net_collected_cents`."
        PRD §3.8: "The pledge's `collected_cents` increments by the payment
        amount, `net_collected_cents` is recomputed per the rule below, and the
        drive's `collected_cents` increments by the resulting net delta."

        Design: Difficulty/compensating_invariant/decline_restores_drive_collected_total
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000)
        # A partial payment leaves the pledge in PARTIAL, the non-terminal
        # state from which PRD §3.9 permits a decline.
        partial = post_payment_ok(pledge, 5000)
        assert partial["payment_status"] == "PARTIAL"

        drive = get_drive(station["drive"]["id"])
        assert drive["pledged_cents"] == 12000
        assert drive["collected_cents"] == 5000, (
            "the payment added the pledge's net to the drive collected total")

        decline_pledge_ok(pledge["id"], reason="donor disputed charge")

        drive = get_drive(station["drive"]["id"])
        assert drive["collected_cents"] == 0, (
            "the decline subtracts exactly the same net — no drift")
        assert drive["pledged_cents"] == 0

    def test_decline_restores_donor_lifetime_and_records_reason(
            self, api, coordinator_headers):
        """PRD §3.9: "The donor's `lifetime_given_cents` decrements by the
        pledge's `net_collected_cents`."
        PRD §3.9: "a `PhoneVolunteer` moves a pledge from `PLEDGED` or
        `PARTIAL` to `DECLINED`, supplying a `reason` which is recorded as
        `decline_reason`."

        Design: Difficulty/compensating_invariant/decline_restores_drive_collected_total
        """
        station = setup_station()
        # A partial payment leaves the pledge in PARTIAL, the non-terminal
        # state from which PRD §3.9 permits a decline.
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="WEB", kind="ONE_TIME",
            amount_cents=12000)
        post_payment_ok(pledge, 5000)
        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lifetime_given_cents"] == 5000

        decline_pledge_ok(pledge["id"], reason="donor disputed charge")

        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lifetime_given_cents"] == 0, (
            "the decline reverses the donor's lifetime giving exactly")
        reread = get_pledge(pledge["id"])
        assert reread["payment_status"] == "DECLINED"
        assert reread["decline_reason"] == "donor disputed charge"


class TestWriteOffCascade:
    def test_writeoff_releases_reservation_rebalances_lot(
            self, api, coordinator_headers):
        """PRD §3.9: "When the pledge's `fulfillment_status` was `RESERVED`,
        the reservation transitions to `RELEASED` and the lot's counters
        compensate (the `reserved_qty` decrements and `available_qty`
        increments by the reservation quantity)."
        PRD §3.9: "after the 60-day unfulfilled-pledge follow-up window has
        elapsed (the current logical time is at least the pledge's `created_at`
        plus 60 days), a `MembershipCoordinator` moves the pledge to
        `WRITTEN_OFF`, again supplying a `reason`."

        Design: Difficulty/transitive_cascade/writeoff_releases_reservation_rebalances_lot
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 10})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        assert pledge["fulfillment_status"] == "RESERVED"
        lot = get_lot_of_premium(station["premium"]["id"])
        assert (lot["available_qty"], lot["reserved_qty"]) == (9, 1)

        # Pledge created at the 2026-08-01 startup clock; 2026-10-02 is 62
        # days later — past the 60-day follow-up window.
        advance_clock(WRITEOFF_READY_CLOCK_ISO)
        resp = api.write_off_pledge(
            pledge["id"], create_reason_payload(
                "no response after 3 follow-up contacts"),
            coordinator_headers)
        written_off = validate_success(resp, 200)
        assert written_off["payment_status"] == "WRITTEN_OFF"

        reservation = get_pledge_reservation(pledge["id"])
        assert reservation["status"] == "RELEASED", (
            "the write-off cascade releases the held reservation")
        lot = get_lot_of_premium(station["premium"]["id"])
        assert lot["available_qty"] == 10
        assert lot["reserved_qty"] == 0
        assert_lot_quantity_conserved(lot)

        drive = get_drive(station["drive"]["id"])
        assert drive["pledged_cents"] == 0

    def test_writeoff_after_partial_payment_reverses_net_everywhere(
            self, api, coordinator_headers, station_admin_headers):
        """PRD §3.9: "Both transitions fire the same compensating-reversal
        cascade. The drive's `pledged_cents` decrements by the pledge's
        `amount_cents`. The drive's `collected_cents` decrements by the
        pledge's `net_collected_cents`."
        PRD §3.9: "The donor's `lifetime_given_cents` decrements by the
        pledge's `net_collected_cents`."

        Design: Difficulty/transitive_cascade/writeoff_releases_reservation_rebalances_lot
        """
        station = setup_station(with_premium=True,
                                lot_overrides={"total_qty": 10})
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=12000, premium_id=station["premium"]["id"])
        partial = post_payment_ok(pledge, 5000)
        assert partial["payment_status"] == "PARTIAL"
        assert partial["collected_cents"] == 5000
        assert partial["net_collected_cents"] == 2500, (
            "5000 collected minus the 2500 premium FMV while RESERVED")

        drive = get_drive(station["drive"]["id"])
        assert drive["pledged_cents"] == 12000
        assert drive["collected_cents"] == 2500
        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lifetime_given_cents"] == 2500

        advance_clock(WRITEOFF_READY_CLOCK_ISO)
        write_off_pledge_ok(pledge["id"])

        drive = get_drive(station["drive"]["id"])
        assert drive["pledged_cents"] == 0
        assert drive["collected_cents"] == 0, (
            "the write-off reverses exactly the pledge's net collected")
        donor = validate_success(
            api.get_donor(station["donor"]["id"], coordinator_headers))
        assert donor["lifetime_given_cents"] == 0
        reservation = get_pledge_reservation(pledge["id"])
        assert reservation["status"] == "RELEASED"


class TestWriteOffWindowAndTerminal:
    def test_writeoff_before_60_day_window_rejected(
            self, api, coordinator_headers):
        """PRD §3.9: "**Write-off** is the follow-up path: after the 60-day
        unfulfilled-pledge follow-up window has elapsed (the current logical
        time is at least the pledge's `created_at` plus 60 days), a
        `MembershipCoordinator` moves the pledge to `WRITTEN_OFF`, again
        supplying a `reason`. A write-off attempted before the window elapses
        is rejected with `ERR_WRITEOFF_WINDOW` (422)."

        Design: Corner/validations/writeoff_before_60_day_window_rejected
        """
        create_level()
        donor, membership = setup_donor_membership()
        drive = create_drive()
        add_break(drive["id"], drive["version"])
        schedule_drive(drive["id"])
        # Go live and capture at 2026-08-02T18:05, inside the drive window.
        advance_clock("2026-08-02T18:05:00Z")
        go_live_drive(drive["id"])
        pledge = capture_pledge(
            donor["id"], membership["id"], drive["id"],
            channel="PHONE", kind="ONE_TIME", amount_cents=6000)

        # 2026-09-30T18:05 is 59 days after capture — inside the window.
        advance_clock("2026-09-30T18:05:00Z")
        resp = api.write_off_pledge(
            pledge["id"], create_reason_payload("no response"),
            coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_WRITEOFF_WINDOW)
        assert get_pledge(pledge["id"])["payment_status"] == "PLEDGED"

    def test_decline_on_written_off_pledge_terminal_lockdown(
            self, api, phone_volunteer_headers, coordinator_headers):
        """PRD §3.9: "**Decline** is the immediate path: a `PhoneVolunteer`
        moves a pledge from `PLEDGED` or `PARTIAL` to `DECLINED`, supplying a
        `reason` which is recorded as `decline_reason`."
        PRD §2.9: "Target resource state permits the operation (generic) →
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/decline_on_written_off_pledge_terminal_lockdown
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)
        advance_clock(WRITEOFF_READY_CLOCK_ISO)
        write_off_pledge_ok(pledge["id"], reason="unreachable donor")

        resp = api.decline_pledge(
            pledge["id"], create_reason_payload("late dispute"),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_pledge(pledge["id"])["payment_status"] == "WRITTEN_OFF", (
            "the terminal write-off is not disturbed by the declined call")

    def test_phone_volunteer_cannot_write_off_pledge(
            self, api, phone_volunteer_headers):
        """PRD §2.1: "`MembershipCoordinator` — the membership manager. Owns
        donor CRM, premium inventory lot receipt, premium
        reservation/shipment/waiver/release, pledge write-off, lapsed-member
        reinstatement, drive reconciliation, and NFFS report drafting."
        PRD §2.1: "A recognized role attempting an operation outside its grant
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/phone_volunteer_cannot_write_off_pledge
        """
        station = setup_station()
        pledge = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)
        advance_clock(WRITEOFF_READY_CLOCK_ISO)

        resp = api.write_off_pledge(
            pledge["id"], create_reason_payload("no response"),
            phone_volunteer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_pledge(pledge["id"])["payment_status"] == "PLEDGED"


class TestDriveAndChallengeRollups:
    def test_drive_totals_rollup_input_set_filtering(
            self, api, phone_volunteer_headers):
        """PRD §3.5: "Every capture increments the drive's `pledged_cents` by
        the pledge's `amount_cents`."
        PRD §3.9: "Both transitions fire the same compensating-reversal
        cascade. The drive's `pledged_cents` decrements by the pledge's
        `amount_cents`. The drive's `collected_cents` decrements by the
        pledge's `net_collected_cents`."
        PRD §3.3: "The drive's `pledged_cents` and `collected_cents` start at
        0 and are server-maintained."

        Design: Corner/calculations/drive_totals_rollup_input_set_filtering
        """
        # Level minimum of 4000 so both the 6000 and 4000 pledges qualify.
        station = setup_station(level_overrides={
            "code": "BASIC", "min_annual_cents": 4000,
            "min_monthly_sustainer_cents": 400})
        pledge_a = capture_and_pay(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="PHONE", kind="ONE_TIME",
            amount_cents=6000)
        pledge_b = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"], channel="WEB", kind="ONE_TIME",
            amount_cents=4000)
        decline_pledge_ok(pledge_b["id"], reason="card declined")

        drive = get_drive(station["drive"]["id"])
        assert drive["pledged_cents"] == 6000, (
            "the declined pledge no longer counts toward pledged_cents")
        assert drive["collected_cents"] == 6000, (
            "only the paid pledge's net counts toward collected_cents")

    def test_matching_challenge_decline_decrements_progress(
            self, api, phone_volunteer_headers, station_admin_headers):
        """PRD §3.7: "Progress is a derived sum over the challenge's
        non-terminal pledges: the sum of `amount_cents` over pledges whose
        `matching_challenge_id` is this challenge and whose `payment_status` is
        neither `DECLINED` nor `WRITTEN_OFF`."
        PRD §3.7: "At that point the challenge transitions to `MET` and stays
        there: the status is latched and never reverts, even if a subsequent
        decline or write-off pulls the progress back below the goal."

        Design: Corner/calculations/matching_challenge_decline_decrements_progress
        """
        # Level minimum of 1000 so the 7000/4000 split pledges both qualify.
        station = setup_station_with_challenge(
            level_overrides={"code": "BASIC", "min_annual_cents": 1000,
                             "min_monthly_sustainer_cents": 100},
            sponsor_name="Acme", goal_cents=10000, match_cents=5000)
        challenge = station["challenge"]

        capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"],
            matching_challenge_id=challenge["id"],
            channel="PHONE", kind="ONE_TIME", amount_cents=7000)
        pledge_b = capture_pledge(
            station["donor"]["id"], station["membership"]["id"],
            station["drive"]["id"],
            matching_challenge_id=challenge["id"],
            channel="WEB", kind="ONE_TIME", amount_cents=4000)

        mid = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert mid["progress_cents"] == 11000
        assert mid["status"] == "MET"

        decline_pledge_ok(pledge_b["id"], reason="donor reneged")

        after = validate_success(
            api.get_matching_challenge(challenge["id"], station_admin_headers))
        assert after["progress_cents"] == 7000, (
            "the declined pledge is excluded from the derived progress sum")
        assert after["status"] == "MET", (
            "MET is latched — the decline does not un-latch it")
