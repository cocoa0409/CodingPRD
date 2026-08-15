"""Checkout gates: state, weather hold, itinerary presence, orientation
countersignature, fuel-gauge validity — and the clock sweep lifting the hold."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    checkout_payload,
    confirm_booking,
    countersign_orientation,
    create_booking,
    create_qualified_renter,
    create_vessel,
    create_weather_advisory,
    create_season_rate,
    create_geo_zone,
    get_booking,
    put_itinerary,
    set_clock,
    setup_confirmed_booking,
    sign_all_orientation_items,
    sign_orientation_item,
    validate_error,
    validate_success,
    waypoint,
)

FM = TEST_USERS["fleet_manager_headers"]
DS = TEST_USERS["dock_staff_headers"]


class TestCheckoutStateGate:
    def test_checkout_on_held_beats_itinerary_constraint(self, api):
        """PRD §3.6: "Checkout is a `DockStaff` action performed on the day the
        charter begins: the current date must fall on or after the booking's
        `start_date` and strictly before its `end_date`, and the booking must
        be `CONFIRMED`."
        PRD §2.11: "Generic transition state — the resource is not in a state
        that permits the requested transition (confirm on a non-`HELD` booking,
        checkout on a non-`CONFIRMED` booking, settle on a non-`RETURNED`
        booking, sign-item on a `COUNTERSIGNED` orientation, inspect on a turn
        that is not `IN_PROGRESS`, a decision on a non-`SUBMITTED` certificate,
        a resolve on a non-`REPORTED` incident): `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_beats_constraint
        """
        vessel = create_vessel(name="Compact Nine", size_class="COMPACT_36",
                               fuel_tank_capacity_gallons=150)
        create_season_rate(size_class="COMPACT_36", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=45000, weekly_discount_pct=10)
        renter, headers, _ = create_qualified_renter(
            full_name="Sam State", email="sam@x.com", cert_number="C-701")
        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-20", end_date="2026-08-24")
        assert booking["status"] == "HELD"

        # HELD and no itinerary: the generic state precondition surfaces.
        resp = api.checkout_booking(booking["id"], checkout_payload(100, True), DS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_booking(booking["id"])
        assert after["status"] == "HELD"

    def test_checkout_on_held_with_itinerary_still_state_error(self, api):
        """PRD §3.6: "Checkout is a `DockStaff` action performed on the day the
        charter begins: the current date must fall on or after the booking's
        `start_date` and strictly before its `end_date`, and the booking must
        be `CONFIRMED`."
        PRD §3.5: "Submitting the itinerary — allowed only while the booking is
        `HELD` or `CONFIRMED`, with attempts on a booking in any other state
        rejected by the generic `ERR_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/checkout_state_beats_constraint
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-24")
        # Rebuild a second HELD booking on a fresh vessel with an APPROVED
        # itinerary (PUT is legal while HELD) and attempt checkout on it.
        vessel = create_vessel(name="Compact Nine B", size_class="COMPACT_36",
                               fuel_tank_capacity_gallons=150)
        renter, headers, _ = create_qualified_renter(
            full_name="Sam Two", email="sam2@x.com", cert_number="C-702")
        zone = create_geo_zone(zone_code="ZP-HELD", name="Held Bay",
                               allowed_size_classes=["COMPACT_36"])
        # Create the booking at the 2026-08-19 clock so its 48-hour hold
        # (created_at + 48h = 2026-08-21T00:00:00Z) survives the checkout-day
        # clock below; otherwise the §2.4 sweep expires the HELD booking.
        set_clock("2026-08-19T00:00:00Z")
        held = create_booking(vessel["id"], renter, headers,
                              start_date="2026-08-20", end_date="2026-08-24")
        record = put_itinerary(held["id"], headers,
                               [waypoint(zone["id"], "2026-08-20")])
        assert record["status"] == "APPROVED"

        set_clock("2026-08-20T09:00:00Z")
        resp = api.checkout_booking(held["id"], checkout_payload(100, True), DS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_booking(held["id"])["status"] == "HELD"


class TestCheckoutBusinessGates:
    def test_checkout_requires_itinerary(self, api):
        """PRD §3.6: "The gates, in their mandated order after the generic
        state check, are: no `ACTIVE` weather advisory may cover the current
        clock while its `zone_ids` intersect the zones of the booking's
        `APPROVED` itinerary (`ERR_WEATHER_HOLD_ACTIVE`); an `APPROVED`
        itinerary must exist at all (`ERR_ITINERARY_REQUIRED`); the orientation
        must stand at `COUNTERSIGNED` (`ERR_ORIENTATION_NOT_COUNTERSIGNED`); no
        cleaning turn of any booking on the same vessel may be `IN_PROGRESS`
        (`ERR_CLEANING_TURN_INCOMPLETE`); and the deposit dimension must be
        `HELD` — a deposit out of order surfaces the generic
        `ERR_INVALID_STATE`."

        Design: Corner/validations/checkout_requires_itinerary
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-22",
                                      countersign=True)
        set_clock("2026-08-20T09:00:00Z")

        resp = api.checkout_booking(ctx["booking"]["id"],
                                    checkout_payload(100, True), DS)
        validate_error(resp, ApiErrorId.ERR_ITINERARY_REQUIRED, 422)

        after = get_booking(ctx["booking"]["id"])
        assert after["status"] == "CONFIRMED"
        assert after["settlement_status"] == "NONE", (
            "a rejected checkout computes no provisional estimate"
        )

    def test_checkout_blocked_by_orientation_not_countersigned(self, api):
        """PRD §3.6: "the orientation must stand at `COUNTERSIGNED`
        (`ERR_ORIENTATION_NOT_COUNTERSIGNED`)"
        PRD §3.5: "When the last unsigned item is signed, the orientation moves
        `IN_PROGRESS` → `COMPLETED` automatically."

        Design: Difficulty/cross_entity_state_dependency/checkout_requires_orientation_countersigned
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-22",
                                      with_itinerary=True,
                                      zone_code="ZP-LABYRINTH")
        booking = ctx["booking"]
        booking = sign_all_orientation_items(booking["id"], ctx["renter_headers"],
                                             ctx["size_class"])
        assert booking["orientation_status"] == "COMPLETED"

        set_clock("2026-08-20T09:00:00Z")
        resp = api.checkout_booking(booking["id"], checkout_payload(100, True), DS)
        validate_error(resp, ApiErrorId.ERR_ORIENTATION_NOT_COUNTERSIGNED, 409)
        assert get_booking(booking["id"])["status"] == "CONFIRMED"

        booking = countersign_orientation(booking["id"], approved=True)
        assert booking["orientation_status"] == "COUNTERSIGNED"
        checked = validate_success(
            api.checkout_booking(booking["id"], checkout_payload(100, True), DS), 200)
        assert checked["status"] == "CHECKED_OUT"
        assert checked["settlement_status"] == "PROVISIONAL"

    def test_checkout_blocked_while_orientation_in_progress(self, api):
        """PRD §3.6: "the orientation must stand at `COUNTERSIGNED`
        (`ERR_ORIENTATION_NOT_COUNTERSIGNED`)"

        Design: Difficulty/cross_entity_state_dependency/checkout_requires_orientation_countersigned
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-22",
                                      with_itinerary=True,
                                      zone_code="ZP-HALF")
        booking = ctx["booking"]
        sign_orientation_item(booking["id"], ctx["renter_headers"], "SAFETY_BRIEF")
        booking = sign_orientation_item(booking["id"], ctx["renter_headers"], "DOCKING")
        assert booking["orientation_status"] == "IN_PROGRESS"

        set_clock("2026-08-20T09:00:00Z")
        resp = api.checkout_booking(booking["id"], checkout_payload(100, True), DS)
        validate_error(resp, ApiErrorId.ERR_ORIENTATION_NOT_COUNTERSIGNED, 409)
        assert get_booking(booking["id"])["status"] == "CONFIRMED"

    def test_fuel_gauge_out_of_range_rejected(self, api):
        """PRD §3.6: "`fuel_gauge_percent` — an integer from 0 to 100, anything
        outside rejected with `ERR_FUEL_GAUGE_INVALID`"

        Design: Corner/validations/fuel_gauge_out_of_range_rejected
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-22",
                                      with_itinerary=True, zone_code="ZP-FUEL",
                                      countersign=True)
        set_clock("2026-08-20T09:00:00Z")

        resp = api.checkout_booking(ctx["booking"]["id"],
                                    checkout_payload(120, True), DS)
        validate_error(resp, ApiErrorId.ERR_FUEL_GAUGE_INVALID, 422)
        assert get_booking(ctx["booking"]["id"])["status"] == "CONFIRMED"


class TestCheckoutWeatherHold:
    def test_checkout_blocked_by_active_weather_hold(self, api):
        """PRD §3.6: "no `ACTIVE` weather advisory may cover the current clock
        while its `zone_ids` intersect the zones of the booking's `APPROVED`
        itinerary (`ERR_WEATHER_HOLD_ACTIVE`)"

        Design: Corner/validations/checkout_blocked_by_active_weather_hold
        """
        ctx = setup_confirmed_booking(start_date="2026-08-10",
                                      end_date="2026-08-13",
                                      with_itinerary=True, zone_code="ZP-GALE",
                                      itinerary_night="2026-08-10",
                                      countersign=True)
        create_weather_advisory("STORM", [ctx["zone"]["id"]],
                                "2026-08-09T00:00:00Z", "2026-08-12T00:00:00Z")
        set_clock("2026-08-10T09:00:00Z")  # inside the advisory window

        resp = api.checkout_booking(ctx["booking"]["id"],
                                    checkout_payload(100, True), DS)
        validate_error(resp, ApiErrorId.ERR_WEATHER_HOLD_ACTIVE, 422)
        assert get_booking(ctx["booking"]["id"])["status"] == "CONFIRMED"

    def test_weather_advisory_expiry_allows_checkout(self, api):
        """PRD §2.4: "Every `ACTIVE` weather advisory whose `window_end` now
        lies before the current clock transitions to `EXPIRED` and stops
        triggering both the weather cancellation variant and the checkout
        weather hold."
        PRD §3.6: "fuel is estimated at a 50% burn of the tank — half of
        `fuel_tank_capacity_gallons`, rounded half up to one decimal place,
        priced at 700 cents per gallon; the pump-out fee of 15,000 cents is
        assumed due; the cleaning fee of 25,000 cents is included; and
        late-return, damage, grounding and mechanical-refund components are all
        zero."

        Design: Corner/state_machines/weather_advisory_expiry_allows_checkout
        """
        ctx = setup_confirmed_booking(start_date="2026-08-10",
                                      end_date="2026-08-13",
                                      with_itinerary=True, zone_code="ZP-STORMY",
                                      itinerary_night="2026-08-10",
                                      countersign=True)
        create_weather_advisory("STORM", [ctx["zone"]["id"]],
                                "2026-08-05T00:00:00Z", "2026-08-08T00:00:00Z")
        set_clock("2026-08-10T09:00:00Z")  # window_end has passed: EXPIRED

        checked = validate_success(
            api.checkout_booking(ctx["booking"]["id"],
                                 checkout_payload(100, True), DS), 200)
        assert checked["status"] == "CHECKED_OUT"
        # COMPACT tank 150 -> 75.0 gal x 700 = 52500 + 15000 pump-out + 25000 cleaning
        assert checked["provisional_estimate_cents"] == 92500, (
            f"provisional estimate must use the 50% burn variant, got "
            f"{checked['provisional_estimate_cents']}"
        )
