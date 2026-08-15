"""The logical clock and its sweep: hold expiry, the maintenance-window /
vessel status cycle, and the certificate-revoke suspension cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_deposit_invariants,
    confirm_booking,
    create_booking,
    create_geo_zone,
    create_qualified_renter,
    create_season_rate,
    create_vessel,
    find_charge,
    get_booking,
    get_renter,
    get_single_turn,
    get_vessel,
    list_charges,
    list_itineraries,
    list_maintenance_windows,
    put_itinerary,
    set_clock,
    setup_confirmed_booking,
    setup_fleet_with_rate,
    submit_certificate,
    validate_error,
    validate_success,
    verify_certificate,
    waypoint,
)

FM = TEST_USERS["fleet_manager_headers"]
DS = TEST_USERS["dock_staff_headers"]


class TestMaintenanceWindowConflicts:
    def test_maintenance_window_closed_interval_conflict(self, api):
        """PRD §3.2: "Creation is refused with `ERR_MAINTENANCE_DATE_CONFLICT`
        in two situations: the window would intersect, under closed-interval
        comparison, any booking of the same vessel in `CONFIRMED`,
        `CHECKED_OUT`, `INTERRUPTED`, or `RETURNED` (a window whose
        `start_date` falls on or before the booking's `end_date` and whose
        `end_date` falls on or after the booking's `start_date` conflicts,
        touching endpoints included); or it would overlap another maintenance
        window of the same vessel, again with touching endpoints counting as a
        conflict."

        Design: Corner/validations/maintenance_window_closed_interval_conflict
        """
        ctx = setup_confirmed_booking(size_class="STANDARD_44", tank=200,
                                      vessel_name="Standard Mw",
                                      start_date="2026-08-10",
                                      end_date="2026-08-17")
        vessel = ctx["vessel"]

        # Window end touches the booking's start_date: a conflict under the
        # closed-interval comparison.
        resp = api.create_maintenance_window(
            vessel["id"],
            {"start_date": "2026-08-09", "end_date": "2026-08-10",
             "reason": "Impeller"},
            FM)
        validate_error(resp, ApiErrorId.ERR_MAINTENANCE_DATE_CONFLICT, 409)

        # A window starting after the stay's end_date is free.
        ok = api.create_maintenance_window(
            vessel["id"],
            {"start_date": "2026-08-18", "end_date": "2026-08-20",
             "reason": "Zincs"},
            FM)
        window = validate_success(ok, 201)
        assert window["status"] == "SCHEDULED"
        assert window["source"] == "SCHEDULED_PLANNED"


class TestClockSweep:
    def test_held_booking_expires_via_clock(self, api):
        """PRD §3.4: "If the renter never confirms, the clock sweep moves a
        `HELD` booking whose `hold_expires_at` has passed to `EXPIRED`: since
        no funds were ever captured, the deposit dimension goes straight from
        `PENDING` to `RELEASED` with `deposit_held_cents`,
        `deposit_applied_cents` and `deposit_released_cents` all at 0, and
        `Booking.version` increments."

        Design: Corner/state_machines/held_booking_expires_via_clock
        """
        vessel = setup_fleet_with_rate()
        renter, headers, _ = create_qualified_renter(
            full_name="Exp Ire", email="exp@x.com", cert_number="C-1308")
        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-20", end_date="2026-08-24")
        assert booking["status"] == "HELD"

        # hold_expires_at is 2026-08-03T00:00:00Z (created at the default
        # 2026-08-01 clock + 48h); one second past it expires the hold.
        set_clock("2026-08-03T00:00:01Z")

        after = get_booking(booking["id"])
        assert after["status"] == "EXPIRED"
        assert after["deposit_status"] == "RELEASED"
        assert after["deposit_held_cents"] == 0
        assert after["deposit_applied_cents"] == 0
        assert after["deposit_released_cents"] == 0

    def test_vessel_cycles_with_window_under_clock(self, api):
        """PRD §3.2: "Thereafter the clock sweep drives the window lifecycle:
        `SCHEDULED` → `IN_PROGRESS` when the current date enters the interval
        (vessel to `IN_MAINTENANCE`), and `IN_PROGRESS` → `COMPLETED` once the
        current date passes `end_date`, returning the vessel to `AVAILABLE`
        provided no other window of that vessel covers the current date."

        Design: Difficulty/non_linear_state_machine/vessel_maintenance_cycle_via_clock
        """
        vessel = create_vessel(name="Compact Five", size_class="COMPACT_36",
                               fuel_tank_capacity_gallons=150)
        assert vessel["status"] == "AVAILABLE"

        ok = api.create_maintenance_window(
            vessel["id"],
            {"start_date": "2026-08-05", "end_date": "2026-08-07",
             "reason": "Lower unit service"},
            FM)
        window = validate_success(ok, 201)
        assert window["status"] == "SCHEDULED"

        set_clock("2026-08-06T00:00:00Z")  # inside the closed interval
        assert get_vessel(vessel["id"])["status"] == "IN_MAINTENANCE"
        windows = list_maintenance_windows(vessel["id"])
        assert windows[0]["status"] == "IN_PROGRESS"

        set_clock("2026-08-08T00:00:00Z")  # past end_date: the cycle closes
        assert get_vessel(vessel["id"])["status"] == "AVAILABLE"
        windows = list_maintenance_windows(vessel["id"])
        assert windows[0]["status"] == "COMPLETED"

    def test_window_born_in_progress_when_clock_inside(self, api):
        """PRD §3.2: "A scheduled window is born with `source`
        `SCHEDULED_PLANNED` and status `SCHEDULED` — unless the current date
        already falls inside the window, in which case it is born `IN_PROGRESS`
        and immediately moves the vessel from `AVAILABLE` to `IN_MAINTENANCE`."
        PRD §3.2: "`IN_PROGRESS` → `COMPLETED` once the current date passes
        `end_date`, returning the vessel to `AVAILABLE` provided no other
        window of that vessel covers the current date."

        Design: Difficulty/non_linear_state_machine/vessel_maintenance_cycle_via_clock
        """
        vessel = create_vessel(name="Compact Six", size_class="COMPACT_36",
                               fuel_tank_capacity_gallons=150)
        set_clock("2026-08-06T00:00:00Z")  # already inside the future window

        ok = api.create_maintenance_window(
            vessel["id"],
            {"start_date": "2026-08-05", "end_date": "2026-08-07",
             "reason": "Immediate service"},
            FM)
        window = validate_success(ok, 201)
        assert window["status"] == "IN_PROGRESS"
        assert window["source"] == "SCHEDULED_PLANNED"
        assert get_vessel(vessel["id"])["status"] == "IN_MAINTENANCE"

        set_clock("2026-08-08T00:00:00Z")
        assert get_vessel(vessel["id"])["status"] == "AVAILABLE"
        assert list_maintenance_windows(vessel["id"])[0]["status"] == "COMPLETED"


class TestCertificateSuspensionCascade:
    def _setup_revoke_scenario(self):
        vessel = create_vessel(name="Luxe Six", size_class="LUXE_56", berth_count=8,
                               fuel_tank_capacity_gallons=300)
        create_season_rate(size_class="LUXE_56", season="SHOULDER",
                           start_date="2026-09-01", end_date="2026-10-31",
                           nightly_rate_cents=65000, weekly_discount_pct=10)
        renter, headers, cert = create_qualified_renter(
            full_name="Kit Cascade", email="kit@x.com",
            date_of_birth="1982-12-01", cert_number="C-500",
            issuing_authority="USCG", cert_issued_on="2026-01-10")
        b1 = create_booking(vessel["id"], renter, headers,
                            start_date="2026-09-20", end_date="2026-09-25",
                            party_size=4)
        b1 = confirm_booking(b1["id"], headers)
        assert b1["quoted_total_cents"] == 325000  # 5 x 65000
        zone = create_geo_zone(zone_code="ZP-FACE", name="Face Canyon",
                               allowed_size_classes=["LUXE_56"])
        put_itinerary(b1["id"], headers, [waypoint(zone["id"], "2026-09-20")])
        b2 = create_booking(vessel["id"], renter, headers,
                            start_date="2026-10-01", end_date="2026-10-04",
                            party_size=4)
        return {"vessel": vessel, "renter": renter, "headers": headers,
                "cert": cert, "b1": b1, "b2": b2}

    def test_certificate_revoke_cascades_to_confirmed_booking(self, api):
        """PRD §3.3: "A later `decision` of `REVOKE` — the `FleetManager`'s
        prerogative, with the decision endpoint itself shared between
        `DockStaff` and `FleetManager` — moves a `VERIFIED` certificate to
        `REVOKED`"
        PRD §3.3: "The suspension cascade cancels every booking of the renter
        that is in `HELD` or `CONFIRMED` with a `start_date` after the current
        date, stamping `cancellation_reason` `RENTER_SUSPENDED`: confirmed
        bookings receive a 100% rental refund posted as a negative
        `CANCELLATION_REFUND` charge, deposits are `RELEASED`, cleaning turns
        and orientations are `CANCELLED`, and any `APPROVED` itinerary becomes
        `VOID`, freeing its zone occupancy."

        Design: Difficulty/transitive_cascade/certificate_revoke_cascades_to_cancellation
        """
        ctx = self._setup_revoke_scenario()

        cert = validate_success(
            api.decide_certificate(ctx["cert"]["id"], {"decision": "REVOKE"}, FM), 200)
        assert cert["status"] == "REVOKED"
        assert get_renter(ctx["renter"]["id"])["qualification_status"] == "SUSPENDED"

        b1 = get_booking(ctx["b1"]["id"])
        assert b1["status"] == "CANCELLED"
        assert b1["cancellation_reason"] == "RENTER_SUSPENDED"
        assert b1["refund_issued_cents"] == 325000, "100% of the pinned quote"
        assert b1["deposit_status"] == "RELEASED"
        assert b1["deposit_released_cents"] == 250000
        assert b1["deposit_applied_cents"] == 0
        assert b1["orientation_status"] == "CANCELLED"
        assert_deposit_invariants(b1)

        refund_line = find_charge(list_charges(b1["id"]), "CANCELLATION_REFUND")
        assert refund_line["amount_cents"] == -325000
        assert refund_line["status"] == "REFUNDED"

        assert list_itineraries(b1["id"])[0]["status"] == "VOID"
        assert get_single_turn(b1["id"])["status"] == "CANCELLED"

    def test_certificate_revoke_cancels_held_and_requalification_restores(self, api):
        """PRD §3.3: "The suspension cascade cancels every booking of the
        renter that is in `HELD` or `CONFIRMED` with a `start_date` after the
        current date, stamping `cancellation_reason` `RENTER_SUSPENDED`"
        PRD §3.9: "From `HELD`, nothing was ever paid and the deposit was never
        captured, so the refund is zero."
        PRD §3.3: "The first verification lifts an `UNVERIFIED` renter to
        `QUALIFIED`; a fresh verification likewise restores a `SUSPENDED`
        renter."

        Design: Difficulty/transitive_cascade/certificate_revoke_cascades_to_cancellation
        """
        ctx = self._setup_revoke_scenario()

        validate_success(
            api.decide_certificate(ctx["cert"]["id"], {"decision": "REVOKE"}, FM), 200)

        b2 = get_booking(ctx["b2"]["id"])
        assert b2["status"] == "CANCELLED"
        assert b2["cancellation_reason"] == "RENTER_SUSPENDED"
        assert b2["refund_issued_cents"] == 0, "a HELD booking paid nothing"
        assert b2["deposit_status"] == "RELEASED"
        assert b2["deposit_held_cents"] == 0
        assert_deposit_invariants(b2)

        profile = get_renter(ctx["renter"]["id"])
        assert profile["qualification_status"] == "SUSPENDED"

        # Renewal path: a fresh certificate verification restores QUALIFIED.
        new_cert = submit_certificate(ctx["renter"], ctx["headers"],
                                      cert_number="C-500B",
                                      issuing_authority="NASBLA",
                                      issued_on="2026-08-01",
                                      expires_on="2027-12-31")
        verify_certificate(new_cert["id"])
        profile = get_renter(ctx["renter"]["id"])
        assert profile["qualification_status"] == "QUALIFIED"
