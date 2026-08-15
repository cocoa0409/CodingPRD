"""Voucher entitlement windows, night overlap, fiscal caps, lifecycle gates,
and the voucher-issue validation order."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, add_passenger, add_flight, add_event, add_booking,
    event_to_assessing, event_to_recovery,
    setup_disrupted_booking, setup_committed_case, setup_multi_booking_disruption,
    commit_cases, issue_voucher, cost_entries,
)

AGENT = TEST_USERS["agent_headers"]
FIN = TEST_USERS["finance_headers"]


class TestMealWindowFloorBoundary:
    """Window measured in whole hours from cancelled_at (06:00) to the committed
    option's first departure: 8h -> 2 meals + hotel; 7h -> 1 meal, hotel denied."""

    def _setup(self):
        ctx = setup_multi_booking_disruption(
            booking_count=2, event_code="MECH-15", cost_cap_cents=500000,
            event_state="RECOVERY",
            flight_overrides={"flight_number": "OC61",
                              "sched_dep_utc": "2026-08-10T09:00:00Z",
                              "sched_arr_utc": "2026-08-10T10:00:00Z"},
            extra_flights=[
                {"flight_number": "OC62",  # dep 14:00 -> 8h window
                 "sched_dep_utc": "2026-08-10T14:00:00Z",
                 "sched_arr_utc": "2026-08-10T15:00:00Z"},
                {"flight_number": "OC63",  # dep 13:00 -> 7h window
                 "sched_dep_utc": "2026-08-10T13:00:00Z",
                 "sched_arr_utc": "2026-08-10T14:00:00Z"},
            ])
        # OC63 arrives earlier -> ranks first (options[0]); OC62 is options[1].
        commit_cases(ctx, [1, 0])
        return ctx

    def test_eight_hour_window_yields_two_meals_and_hotel(self, api):
        """PRD §3.6: "A `MEAL` voucher carries the same state gates — disrupted
        or rebooked booking, committed case, controllable event in recovery —
        and entitles one meal per full four-hour block of the window, at most
        three meals; at least one meal must be earned or the threshold error
        above applies. Its `face_value_cents` is `meals_count` times fifteen
        hundred cents".
        PRD §3.6: "A `HOTEL` voucher requires a booking that is `DISRUPTED` or
        `REBOOKED` with a `COMMITTED` case on a controllable event, and a window
        of at least eight hours. Its `nights` are the window in hours divided by
        twenty-four and rounded up to a whole number, then forced into the range
        of at least one night and at most three nights; the `check_in_date`
        supplied at issuance names the first covered night. Its
        `face_value_cents` is the number of nights times fifteen thousand cents
        per night, and its `valid_through` is the `check_in_date` plus `nights`
        days."

        Design: Difficulty/boundary_precision_check/meal_window_floor_boundary
        """
        ctx = self._setup()
        b1 = ctx["bookings"][0]
        meal = issue_voucher(b1["id"], "MEAL")
        assert meal["meals_count"] == 2, "floor(8h / 4h) = 2 meals"
        assert meal["face_value_cents"] == 3000
        hotel = issue_voucher(b1["id"], "HOTEL", check_in_date="2026-08-10")
        assert hotel["nights"] == 1, "max(1, ceil(8/24)) = 1 night"
        assert hotel["face_value_cents"] == 15000

    def test_seven_hour_window_yields_one_meal_and_hotel_rejection(self, api):
        """PRD §3.6: "A `MEAL` voucher carries the same state gates — disrupted
        or rebooked booking, committed case, controllable event in recovery —
        and entitles one meal per full four-hour block of the window, at most
        three meals; at least one meal must be earned or the threshold error
        above applies. Its `face_value_cents` is `meals_count` times fifteen
        hundred cents, and it is valid through the day after its issue date."
        PRD §3.6: "Fourth, the entitlement thresholds below must be met,
        otherwise `ERR_VOUCHER_RULE_NOT_MET` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/meal_window_floor_boundary
        """
        ctx = self._setup()
        b2 = ctx["bookings"][1]
        meal = issue_voucher(b2["id"], "MEAL")
        assert meal["meals_count"] == 1, "floor(7h / 4h) = 1 meal"
        assert meal["face_value_cents"] == 1500
        res = api_client.issue_voucher(
            b2["id"], {"voucher_type": "HOTEL", "check_in_date": "2026-08-10"}, AGENT)
        validate_error(res, ApiErrorId.ERR_VOUCHER_RULE_NOT_MET)


def test_hotel_nights_ceil_boundary_25h_vs_24h(api):
    """PRD §3.6: "Its `nights` are the window in hours divided by twenty-four
    and rounded up to a whole number, then forced into the range of at least one
    night and at most three nights; the `check_in_date` supplied at issuance
    names the first covered night. Its `face_value_cents` is the number of
    nights times fifteen thousand cents per night, and its `valid_through` is
    the `check_in_date` plus `nights` days."

    Design: Corner/calculations/hotel_nights_ceil_boundary
    """
    ctx = setup_multi_booking_disruption(
        booking_count=2, event_code="MECH-C10", cost_cap_cents=200000,
        event_state="RECOVERY",
        flight_overrides={"flight_number": "OC34",
                          "sched_dep_utc": "2026-08-10T09:00:00Z",
                          "sched_arr_utc": "2026-08-10T10:00:00Z"},
        extra_flights=[
            {"flight_number": "OC35",  # dep 08-11 07:00 -> 25h window
             "sched_dep_utc": "2026-08-11T07:00:00Z",
             "sched_arr_utc": "2026-08-11T08:00:00Z"},
            {"flight_number": "OC36",  # dep 08-11 06:00 -> 24h window
             "sched_dep_utc": "2026-08-11T06:00:00Z",
             "sched_arr_utc": "2026-08-11T07:00:00Z"},
        ])
    # OC36 arrives earlier -> options[0]; OC35 is options[1].
    commit_cases(ctx, [1, 0])
    b1, b2 = ctx["bookings"]

    h1 = issue_voucher(b1["id"], "HOTEL", check_in_date="2026-08-10")
    assert h1["nights"] == 2, "ceil(25/24) = 2 nights"
    assert h1["face_value_cents"] == 30000

    h2 = issue_voucher(b2["id"], "HOTEL", check_in_date="2026-08-11")
    assert h2["nights"] == 1, "ceil(24/24) = 1 night"
    assert h2["face_value_cents"] == 15000


class TestHotelNightOverlapDiscrete:
    """One passenger, three bookings, all committed to the same 30-hour-window
    recovery flight (2 covered nights per hotel voucher)."""

    def _setup(self):
        pax = add_passenger(full_name="Pat P", contact_email="pat@x.com")
        ctx = setup_multi_booking_disruption(
            booking_specs=[
                {"passenger_id": pax["id"], "booking_overrides": {"fare_cents": 12000}},
                {"passenger_id": pax["id"], "booking_overrides": {"fare_cents": 13000}},
                {"passenger_id": pax["id"], "booking_overrides": {"fare_cents": 14000}},
            ],
            event_code="MECH-18", cost_cap_cents=500000, event_state="RECOVERY",
            flight_overrides={"flight_number": "OC96",
                              "sched_dep_utc": "2026-08-10T09:00:00Z",
                              "sched_arr_utc": "2026-08-10T10:00:00Z",
                              "cabins": [{"cabin": "ECONOMY", "capacity": 10}]},
            extra_flights=[{"flight_number": "OC97",
                            "sched_dep_utc": "2026-08-11T12:00:00Z",
                            "sched_arr_utc": "2026-08-11T13:00:00Z",
                            "cabins": [{"cabin": "ECONOMY", "capacity": 10}]}])
        commit_cases(ctx, [0, 0, 0])
        return ctx

    def test_checkout_day_coinciding_with_next_checkin_is_allowed(self, api):
        """PRD §3.6: "Third, for `HOTEL` vouchers, the passenger must not
        already hold an `ISSUED` or `REDEEMED` hotel voucher whose covered
        nights intersect the new one; nights are counted discretely from
        `check_in_date` through `check_in_date` plus `nights` days, and one
        stay's checkout day coinciding with the next stay's check-in day is
        permitted — a true overlap is rejected with `ERR_HOTEL_NIGHT_OVERLAP`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/hotel_night_overlap_discrete
        """
        ctx = self._setup()
        b1, b2 = ctx["bookings"][0], ctx["bookings"][1]
        v1 = issue_voucher(b1["id"], "HOTEL", check_in_date="2026-08-10")
        assert v1["nights"] == 2, "ceil(30/24) = 2 nights"
        assert v1["face_value_cents"] == 30000
        assert v1["valid_through"] == "2026-08-12"

        # Nights {08-12, 08-13} share no night with {08-10, 08-11}.
        v2 = issue_voucher(b2["id"], "HOTEL", check_in_date="2026-08-12")
        assert v2["voucher_status"] == "ISSUED"

    def test_intersecting_night_set_rejected(self, api):
        """PRD §3.6: "Third, for `HOTEL` vouchers, the passenger must not
        already hold an `ISSUED` or `REDEEMED` hotel voucher whose covered
        nights intersect the new one; nights are counted discretely from
        `check_in_date` through `check_in_date` plus `nights` days, and one
        stay's checkout day coinciding with the next stay's check-in day is
        permitted — a true overlap is rejected with `ERR_HOTEL_NIGHT_OVERLAP`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/hotel_night_overlap_discrete
        """
        ctx = self._setup()
        b1, b3 = ctx["bookings"][0], ctx["bookings"][2]
        issue_voucher(b1["id"], "HOTEL", check_in_date="2026-08-10")
        res = api_client.issue_voucher(
            b3["id"], {"voucher_type": "HOTEL", "check_in_date": "2026-08-11"}, AGENT)
        validate_error(res, ApiErrorId.ERR_HOTEL_NIGHT_OVERLAP)


def test_booking_voucher_cap_is_inclusive_at_40000(api):
    """PRD §3.6: "Fifth, the booking's own fiscal cap: the sum of
    `face_value_cents` over the booking's `ISSUED` and `REDEEMED` vouchers plus
    the new voucher's face value must not exceed forty thousand cents, otherwise
    `ERR_VOUCHER_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/booking_voucher_cap_boundary
    """
    ctx = setup_committed_case(
        event_code="MECH-C15", event_state="RECOVERY", cost_cap_cents=500000,
        flight_overrides={"flight_number": "OC55",
                          "sched_dep_utc": "2026-08-10T09:00:00Z",
                          "sched_arr_utc": "2026-08-10T10:00:00Z"},
        extra_flights=[{"flight_number": "OC56",
                        "sched_dep_utc": "2026-08-12T06:00:00Z",
                        "sched_arr_utc": "2026-08-12T07:00:00Z"}])
    booking_id = ctx["booking"]["id"]
    hotel = issue_voucher(booking_id, "HOTEL", check_in_date="2026-08-10")
    assert hotel["face_value_cents"] == 30000, "48h window -> min(3, ceil(48/24)) = 2 nights"
    issue_voucher(booking_id, "TRANSPORT")  # 5000 -> cumulative 35000
    issue_voucher(booking_id, "TRANSPORT")  # 5000 -> cumulative exactly 40000

    res = api_client.issue_voucher(booking_id, {"voucher_type": "TRANSPORT"}, AGENT)
    validate_error(res, ApiErrorId.ERR_VOUCHER_CAP_EXCEEDED)


class TestVoucherIssueValidationOrder:
    def _setup_cancelled_booking(self, cost_cap_cents):
        """A booking outside DISRUPTED/REBOOKED whose event is in RECOVERY, so
        that only the booking-state gate (PRD §3.6 gate 2) can fire: the booking
        is disrupted under the event, the event reaches RECOVERY, and the
        booking is then cancelled outright (PRD §3.4), which voids its open case
        while the case's event stays in RECOVERY.
        """
        ctx = setup_disrupted_booking(
            event_code="MECH-10", cost_cap_cents=cost_cap_cents,
            event_state="RECOVERY",
            flight_overrides={"flight_number": "OC3000",
                              "sched_dep_utc": "2026-08-10T10:00:00Z",
                              "sched_arr_utc": "2026-08-10T11:00:00Z"})
        cancelled = validate_success(api_client.cancel_booking(ctx["booking"]["id"], AGENT))
        assert cancelled["booking_status"] == "CANCELLED"
        return ctx["booking"]

    def test_booking_state_error_wins_over_event_cap(self, api):
        """PRD §3.6: "Second, the booking must be in `DISRUPTED` or `REBOOKED`,
        otherwise `ERR_BOOKING_NOT_DISRUPTED` (HTTP 409); note that this
        booking-state gate applies to vouchers only, and elections are exempt
        from it as §3.7 describes."
        PRD §3.6: "Last, the event's fiscal cap: the event's
        `accrual_total_cents` plus the new face value must not exceed the
        event's `cost_cap_cents`, otherwise `ERR_EVENT_COST_CAP_EXCEEDED`
        (HTTP 422)." The booking-state gate is evaluated before the event
        fiscal cap.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_voucher_issue
        """
        booking = self._setup_cancelled_booking(cost_cap_cents=1)
        res = api_client.issue_voucher(booking["id"], {"voucher_type": "TRANSPORT"}, AGENT)
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_DISRUPTED)

    def test_cancelled_booking_rejected_even_with_generous_event_cap(self, api):
        """PRD §3.6: "Second, the booking must be in `DISRUPTED` or `REBOOKED`,
        otherwise `ERR_BOOKING_NOT_DISRUPTED` (HTTP 409)". Isolated
        single-failure scenario: only the booking-state gate can fire.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_voucher_issue
        """
        booking = self._setup_cancelled_booking(cost_cap_cents=500000)
        res = api_client.issue_voucher(booking["id"], {"voucher_type": "TRANSPORT"}, AGENT)
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_DISRUPTED)

    def _setup_six_hour_window(self, cost_cap_cents):
        return setup_committed_case(
            event_code="MECH-11", event_state="RECOVERY",
            cost_cap_cents=cost_cap_cents,
            flight_overrides={"flight_number": "OC3100",
                              "sched_dep_utc": "2026-08-10T09:00:00Z",
                              "sched_arr_utc": "2026-08-10T10:00:00Z"},
            extra_flights=[{"flight_number": "OC3200",
                            "sched_dep_utc": "2026-08-10T12:00:00Z",
                            "sched_arr_utc": "2026-08-10T13:00:00Z"}])

    def test_short_window_error_wins_over_event_cap(self, api):
        """PRD §3.6: "Fourth, the entitlement thresholds below must be met,
        otherwise `ERR_VOUCHER_RULE_NOT_MET` (HTTP 422)."
        PRD §3.6: "Last, the event's fiscal cap: the event's
        `accrual_total_cents` plus the new face value must not exceed the
        event's `cost_cap_cents`, otherwise `ERR_EVENT_COST_CAP_EXCEEDED`
        (HTTP 422)." The entitlement threshold is evaluated before the event
        fiscal cap.
        PRD §3.6: "A `HOTEL` voucher requires a booking that is `DISRUPTED` or
        `REBOOKED` with a `COMMITTED` case on a controllable event, and a window
        of at least eight hours."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_voucher_issue
        """
        ctx = self._setup_six_hour_window(cost_cap_cents=1)
        res = api_client.issue_voucher(
            ctx["booking"]["id"],
            {"voucher_type": "HOTEL", "check_in_date": "2026-08-10"}, AGENT)
        validate_error(res, ApiErrorId.ERR_VOUCHER_RULE_NOT_MET)

    def test_short_window_hotel_rejected_even_with_generous_cap(self, api):
        """PRD §3.6: "A `HOTEL` voucher requires a booking that is `DISRUPTED`
        or `REBOOKED` with a `COMMITTED` case on a controllable event, and a
        window of at least eight hours." Isolated single-failure scenario: the
        6-hour window (cancel 06:00 -> recovery dep 12:00) fails the threshold
        on its own.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_voucher_issue
        """
        ctx = self._setup_six_hour_window(cost_cap_cents=500000)
        res = api_client.issue_voucher(
            ctx["booking"]["id"],
            {"voucher_type": "HOTEL", "check_in_date": "2026-08-10"}, AGENT)
        validate_error(res, ApiErrorId.ERR_VOUCHER_RULE_NOT_MET)


def test_redeem_after_void_rejected(api):
    """PRD §3.6: "Redeeming a voucher — permitted only while it is `ISSUED`,
    otherwise `ERR_VOUCHER_NOT_OPEN` (HTTP 409) — takes the `actual_amount_cents`
    actually spent, which must be zero or greater (a negative amount is
    `ERR_INVALID_REQUEST`), records it in `redeemed_amount_cents`, moves the
    voucher to `REDEEMED`, and posts a `SETTLEMENT` entry at that amount against
    the `VOUCHER` source. Voiding an `ISSUED` voucher — same state gate, same
    error — moves it to `VOIDED` and posts a compensating `REVERSAL` entry of
    minus the `face_value_cents`."

    Design: Corner/state_machines/voucher_redeem_after_void_rejected
    """
    ctx = setup_disrupted_booking(event_code="MECH-C4", event_state="RECOVERY",
                                  cost_cap_cents=100000)
    voucher = issue_voucher(ctx["booking"]["id"], "TRANSPORT")
    validate_success(api_client.void_voucher(voucher["id"], FIN))

    res = api_client.redeem_voucher(voucher["id"], {"actual_amount_cents": 5000}, FIN)
    validate_error(res, ApiErrorId.ERR_VOUCHER_NOT_OPEN)

    entries = cost_entries(ctx["event"]["id"])
    assert len(entries) == 2, (
        "the failed redemption posts nothing: ACCRUAL + REVERSAL only")
