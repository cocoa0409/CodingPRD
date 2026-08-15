"""Availability posting, the daily availability charge, and its windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_aircraft,
    create_active_contract,
    create_availability_period_payload,
    create_contract_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]
DISPATCH = TEST_USERS["agency_dispatcher_headers"]


class TestAvailabilityCharge:
    def test_eu_full_rate_at_threshold_and_prorate_below(self, api):
        """PRD §3.3: "Under an exclusive-use contract, a `CONFIRMED` day whose
        `available_minutes` reaches `min_daily_available_minutes` bills the
        full daily rate — the threshold is inclusive — while a shorter day
        bills a linear prorate: the daily rate multiplied by the ratio of
        `available_minutes` to `min_daily_available_minutes`, rounded half up
        to a whole cent."
        PRD §3.3: "From the window the system derives `available_minutes`, its
        whole-minute length."

        Design: Difficulty/combinatorial_formula/availability_charge_eu_prorate_vs_cwn_flat
        """
        contract = create_active_contract()  # EU, daily rate 500000, min 570
        aircraft = add_aircraft(contract["id"])

        # 07:00 -> 16:30 == 570 minutes: inclusive threshold bills full rate.
        full = validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-08-03",
                available_start="2026-08-03T07:00:00Z",
                available_end="2026-08-03T16:30:00Z"),
            OPS), 201)
        assert full["status"] == "CONFIRMED", "EU days are CONFIRMED at birth"
        assert full["available_minutes"] == 570
        assert full["availability_charge_cents"] == 500000

        # 07:00 -> 16:29 == 569 minutes: linear prorate, round half up.
        short = validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-08-04",
                available_start="2026-08-04T07:00:00Z",
                available_end="2026-08-04T16:29:00Z"),
            OPS), 201)
        assert short["available_minutes"] == 569
        assert short["availability_charge_cents"] == 499123, \
            "round_half_up(500000 * 569 / 570)"

    def test_cwn_flat_rate_on_confirm_zero_while_offered(self, api):
        """PRD §3.3: "Under a call-when-needed contract, a `CONFIRMED` day bills
        the flat `daily_availability_rate_cents` regardless of minutes, while
        an `OFFERED` day bills nothing."
        PRD §3.3: "The period's initial status depends on the contract type:
        `CONFIRMED` at birth under an `EXCLUSIVE_USE` contract, but merely
        `OFFERED` under `CALL_WHEN_NEEDED`, awaiting agency confirmation."

        Design: Difficulty/combinatorial_formula/availability_charge_eu_prorate_vs_cwn_flat
        """
        cwn = create_active_contract(
            contract_number="CWN-2026-002", agency="CAL_FIRE",
            contract_type="CALL_WHEN_NEEDED",
            daily_availability_rate_cents=600000, flight_hour_rate_cents=320000,
            season_flight_hour_cap_tenths=5000, acceptance_window_minutes=120)
        aircraft = add_aircraft(cwn["id"], tail_number="N200CF", model="S-70I",
                                tank_capacity_gallons=1000)

        offered = validate_success(api.create_availability_period(
            cwn["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-08-03",
                available_start="2026-08-03T07:00:00Z",
                available_end="2026-08-03T16:30:00Z"),
            OPS), 201)
        assert offered["status"] == "OFFERED", "CWN days are OFFERED at birth"
        assert offered["availability_charge_cents"] == 0, \
            "an OFFERED day bills nothing"

        confirmed = validate_success(
            api.confirm_availability_period(offered["id"], DISPATCH), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["availability_charge_cents"] == 600000, \
            "CWN confirmation bills the flat daily rate regardless of minutes"


class TestAvailabilityPostingRules:
    def test_missing_service_date_rejected(self, api):
        """PRD §2.9: "required fields present, types valid, enum members valid,
        date and datetime formats valid, and the intrinsic orderings:
        `hobbs_stop` strictly after `hobbs_start`, `available_end` strictly
        after `available_start`, `planned_end` strictly after `planned_start`,
        `period_end` on or after `period_start`, `season_end_date` strictly
        after `season_start_date`, and exactly one of an inspection's two
        subjects set. Any violation is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/availability_period_missing_required_field
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        payload = create_availability_period_payload(
            aircraft["id"], service_date="2026-08-03")
        del payload["service_date"]
        resp = api.create_availability_period(contract["id"], payload, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_second_period_same_aircraft_date_rejected(self, api):
        """PRD §3.3: "at most one availability period may ever exist per
        aircraft per date — a second period for the same pair, in any status,
        is `ERR_AVAILABILITY_OVERLAP`."

        Design: Corner/entities/availability_period_unique_aircraft_date
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)

        resp = api.create_availability_period(
            contract["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-08-03",
                available_start="2026-08-03T08:00:00Z",
                available_end="2026-08-03T12:00:00Z"),
            OPS)
        validate_error(resp, ApiErrorId.ERR_AVAILABILITY_OVERLAP,
                       expected_status=409)

    def test_contract_availability_reverse_reachability(self, api):
        """PRD §2.3: "Reverse-reachability lists under a parent resource accept
        their own date- or status-scoped filters: a contract's availability
        periods filter by `service_date` and `status`, its invoices by
        `status`, and its agency records by `record_date`".
        PRD §2.3: "the `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/fk_reverse_reachability_contract_availability
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        for day, end in (("2026-08-03", "2026-08-03T16:30:00Z"),
                         ("2026-08-04", "2026-08-04T16:30:00Z")):
            validate_success(api.create_availability_period(
                contract["id"],
                create_availability_period_payload(
                    aircraft["id"], service_date=day,
                    available_start=f"{day}T07:00:00Z", available_end=end),
                OPS), 201)

        resp = api.list_contract_availability_periods(contract["id"], OPS)
        assert resp.json()["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(data) == 2
        for period in data:
            assert period["contract_id"] == contract["id"], \
                "reverse list returns exactly this contract's periods"

    def test_availability_excuse_from_confirmed(self, api):
        """PRD §3.3: "A `CarrierOps` operator may instead excuse a day from
        either `OFFERED` or `CONFIRMED`, supplying an `excuse_reason` of
        `MAINTENANCE`, `CARDING`, `WEATHER`, or `AGENCY_RELEASE`; excusing
        zeroes the charge".

        Design: Corner/state_machines/availability_excuse_from_confirmed
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        period = validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        assert period["availability_charge_cents"] == 500000

        excused = validate_success(api.excuse_availability_period(
            period["id"], {"excuse_reason": "AGENCY_RELEASE"}, OPS), 200)
        assert excused["status"] == "EXCUSED"
        assert excused["excuse_reason"] == "AGENCY_RELEASE"
        assert excused["availability_charge_cents"] == 0, "excusing zeroes the charge"

    def test_service_date_season_boundary(self, api):
        """PRD §3.3: "The service date must lie inside the contract's season,
        from `season_start_date` through `season_end_date` inclusive, or the
        offer is rejected with `ERR_SERVICE_DATE_OUTSIDE_SEASON`".

        Design: Corner/validations/availability_service_date_outside_season
        """
        contract = create_active_contract()  # season 2026-06-01..2026-09-30
        aircraft = add_aircraft(contract["id"])

        in_season = validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-09-30",
                available_start="2026-09-30T07:00:00Z",
                available_end="2026-09-30T16:30:00Z"),
            OPS), 201)
        assert in_season["status"] == "CONFIRMED", \
            "season_end_date itself is inclusive"

        resp = api.create_availability_period(
            contract["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-10-01",
                available_start="2026-10-01T07:00:00Z",
                available_end="2026-10-01T16:30:00Z"),
            OPS)
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUTSIDE_SEASON,
                       expected_status=422)

    def test_availability_create_state_beats_constraint(self, api):
        """PRD §2.9: "When several rules would reject the same request, the
        system does not choose arbitrarily: checks run in a fixed priority
        order, and the earliest failing check produces the response." State
        legality is step 7; overlap/uniqueness is step 9.
        PRD §3.1: "Only an `ACTIVE` contract accepts new business: placing a
        resource order, posting an availability period, or creating an invoice
        against a contract in any other state is refused with
        `ERR_CONTRACT_NOT_ACTIVE`."

        Design: Corner/validations/availability_create_state_beats_constraint
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        validate_success(api.suspend_contract(contract["id"], OPS), 200)

        # Duplicate (aircraft, date) on a SUSPENDED contract: state wins.
        resp = api.create_availability_period(
            contract["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-08-03",
                available_start="2026-08-03T08:00:00Z",
                available_end="2026-08-03T12:00:00Z"),
            OPS)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                       expected_status=409)

    def test_confirm_window_expiry_boundary(self, api):
        """PRD §3.3: "An `AgencyDispatcher` confirms an offered day, moving it
        `OFFERED` → `CONFIRMED`, but only while the clock's date is on or
        before the `service_date`; confirming after the day has passed is
        `ERR_CONFIRM_WINDOW_EXPIRED`."

        Design: Corner/validations/confirm_window_expiry_boundary
        """
        cwn = create_active_contract(
            contract_number="CWN-2026-002", agency="CAL_FIRE",
            contract_type="CALL_WHEN_NEEDED",
            daily_availability_rate_cents=600000, flight_hour_rate_cents=320000,
            season_flight_hour_cap_tenths=5000, acceptance_window_minutes=120)
        aircraft = add_aircraft(cwn["id"], tail_number="N200CF", model="S-70I",
                                tank_capacity_gallons=1000)
        p1 = validate_success(api.create_availability_period(
            cwn["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        p2 = validate_success(api.create_availability_period(
            cwn["id"],
            create_availability_period_payload(
                aircraft["id"], service_date="2026-08-05",
                available_start="2026-08-05T07:00:00Z",
                available_end="2026-08-05T16:30:00Z"),
            OPS), 201)

        set_clock("2026-08-04T00:00:00Z")

        resp = api.confirm_availability_period(p1["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_CONFIRM_WINDOW_EXPIRED,
                       expected_status=422)

        ok = validate_success(api.confirm_availability_period(p2["id"], DISPATCH), 200)
        assert ok["status"] == "CONFIRMED", \
            "confirming while the clock date is on or before the service date succeeds"
