"""Sortie logging, flight-hour gates, fatigue, and the season ledger."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_order,
    assert_flight_log,
    create_assignment,
    get_contract,
    get_crew_member,
    list_duty_days,
    log_sortie,
    make_pilot_headers,
    place_order,
    setup_carded_pair,
    setup_on_incident,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]
DISPATCH = TEST_USERS["agency_dispatcher_headers"]


class TestFlightLogStateGate:
    def test_flight_log_on_assigned_assignment_rejected(self, api):
        """PRD §3.6: "Flight logs are the pilot's own record: only a `Pilot`
        may append one, only to their own assignment, and only while that
        assignment is `ON_INCIDENT` — logging against an assignment in any
        other state is `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/flight_log_requires_on_incident_assignment
        """
        ws = setup_carded_pair()
        order = accept_order(place_order(
            ws["contract"]["id"], ws["incident"]["id"])["id"])
        assignment = create_assignment(
            order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")
        assert assignment["status"] == "ASSIGNED", "never launched"

        resp = api.create_flight_log(
            assignment["id"],
            {"logged_date": "2026-08-02", "hobbs_start": 0.0, "hobbs_stop": 1.0},
            make_pilot_headers(ws["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_rejected_log_leaves_empty_log_list(self, api):
        """PRD §3.6: "only while that assignment is `ON_INCIDENT` — logging
        against an assignment in any other state is `ERR_INVALID_STATE`."
        PRD §2.3: "the `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Difficulty/cross_entity_state_dependency/flight_log_requires_on_incident_assignment
        """
        ws = setup_carded_pair()
        order = accept_order(place_order(
            ws["contract"]["id"], ws["incident"]["id"])["id"])
        assignment = create_assignment(
            order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")

        resp = api.create_flight_log(
            assignment["id"],
            {"logged_date": "2026-08-02", "hobbs_start": 0.0, "hobbs_stop": 1.0},
            make_pilot_headers(ws["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        data, meta = validate_paginated(
            api.list_assignment_flight_logs(assignment["id"], OPS))
        assert data == [], "no FlightLog persisted from the rejected call"
        assert meta["total_count"] == 0


class TestFlightLogShape:
    def test_flight_log_hobbs_ordering_invalid(self, api):
        """PRD §3.6: "Each log names its `assignment_id` through the path it is
        filed under and carries the `logged_date` the flight is charged to
        plus the Hobbs meter readings `hobbs_start` and `hobbs_stop`, the stop
        strictly greater than the start."
        PRD §2.9: "the intrinsic orderings: `hobbs_stop` strictly after
        `hobbs_start`, `available_end` strictly after `available_start`,
        `planned_end` strictly after `planned_start`, `period_end` on or after
        `period_start`, `season_end_date` strictly after `season_start_date`,
        and exactly one of an inspection's two subjects set. Any violation is
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/flight_log_hobbs_ordering_invalid
        """
        ws = setup_on_incident()

        resp = api.create_flight_log(
            ws["assignment"]["id"],
            {"logged_date": "2026-08-02", "hobbs_start": 5.0, "hobbs_stop": 5.0},
            make_pilot_headers(ws["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        data, meta = validate_paginated(
            api.list_assignment_flight_logs(ws["assignment"]["id"], OPS))
        assert meta["total_count"] == 0, "no FlightLog persisted"


class TestFlightHourBoundary:
    def test_flight_hour_accepts_exactly_eighty_tenths(self, api):
        """PRD §3.6: "The chronological flight-hour gate sums the pilot's
        `flight_hours_tenths` over that `logged_date` — creating the
        `CrewDutyDay` on the fly if none exists, in which case its
        `duty_start` stays null — and refuses the log with
        `ERR_FLIGHT_HOUR_LIMIT_EXCEEDED` when the day total including the new
        sortie would exceed 80 tenths; exactly 80 is accepted."

        Design: Difficulty/boundary_precision_check/flight_hour_limit_exactly_eighty_tenths
        """
        ws = setup_on_incident()

        first = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                           "2026-08-02", 100.0, 107.9)
        assert_flight_log(first)
        assert first["flight_hours_tenths"] == 79

        second = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                            "2026-08-02", 107.9, 108.0)
        assert second["flight_hours_tenths"] == 1, \
            "79 + 1 lands the day at exactly 80 tenths, which is allowed"

        duty_days = list_duty_days(ws["pilot"]["id"])
        day = next(d for d in duty_days if d["duty_date"] == "2026-08-02")
        assert day["flown_tenths"] == 80

    def test_flight_hour_rejects_eighty_plus_one_tenth(self, api):
        """PRD §3.6: "refuses the log with `ERR_FLIGHT_HOUR_LIMIT_EXCEEDED`
        when the day total including the new sortie would exceed 80 tenths;
        exactly 80 is accepted."

        Design: Difficulty/boundary_precision_check/flight_hour_limit_exactly_eighty_tenths
        """
        ws = setup_on_incident()
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 100.0, 107.9)
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 107.9, 108.0)

        resp = api.create_flight_log(
            ws["assignment"]["id"],
            {"logged_date": "2026-08-02", "hobbs_start": 108.0,
             "hobbs_stop": 108.1},
            make_pilot_headers(ws["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FLIGHT_HOUR_LIMIT_EXCEEDED,
                       expected_status=422)

        duty_days = list_duty_days(ws["pilot"]["id"])
        day = next(d for d in duty_days if d["duty_date"] == "2026-08-02")
        assert day["flown_tenths"] == 80, \
            "the rejected log leaves no partial write"


class TestCrewDutyVariants:
    def _setup_projection_workspace(self):
        """Pilot with 75 flown tenths and one still-ASSIGNED 1.0 h window on
        2026-08-02; a second ACCEPTED order awaits the candidate assignment."""
        ws = setup_carded_pair()
        order1 = accept_order(place_order(
            ws["contract"]["id"], ws["incident"]["id"], aircraft_quantity=2,
            order_number="O-1001")["id"])
        a = create_assignment(order1["id"], ws["aircraft"]["id"],
                              ws["pilot"]["id"],
                              "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z")
        d = create_assignment(order1["id"], ws["aircraft"]["id"],
                              ws["pilot"]["id"],
                              "2026-08-02T14:00:00Z", "2026-08-02T15:00:00Z")
        from test_helpers import launch_assignment, arrive_assignment
        launch_assignment(a["id"], ws["pilot"]["id"])
        arrive_assignment(a["id"], ws["pilot"]["id"])
        log_sortie(a["id"], ws["pilot"]["id"], "2026-08-02", 300.0, 307.5)

        order2 = accept_order(place_order(
            ws["contract"]["id"], ws["incident"]["id"],
            order_number="O-1002")["id"])
        return ws, order2, d

    def test_duty_day_variants_diverge(self, api):
        """PRD §3.5: "The projection adds to the day's recorded `flown_tenths`
        the planned windows — converted to tenths with round-half-up — of
        every one of the pilot's assignments still in `ASSIGNED` whose
        `planned_start` falls on that duty date, so the two variants
        legitimately disagree: with 75 flown tenths and one assigned 1.0-hour
        window, the projection reads 85 while actuals remain 75."

        Design: Difficulty/dual_variant_calc/crew_duty_projection_vs_chronological_actuals
        """
        ws, _order2, _d = self._setup_projection_workspace()

        duty_days = list_duty_days(ws["pilot"]["id"])
        day = next(d for d in duty_days if d["duty_date"] == "2026-08-02")
        assert day["flown_tenths"] == 75, \
            "chronological variant counts only recorded sorties"
        assert day["projected_tenths"] == 85, \
            "forward-looking variant adds the still-ASSIGNED 1.0 h window"

    def test_projection_gate_rejects_over_eighty(self, api):
        """PRD §3.5: "The forward-looking flight-hour projection for the
        pilot's duty day — `projected_tenths` on the `CrewDutyDay` keyed by
        `crew_member_id` and `duty_date` — must remain at or below 80 tenths,
        eight flight hours, *including* the candidate assignment's own planned
        window: a projection of 81 or more is `ERR_FLIGHT_HOUR_LIMIT_EXCEEDED`,
        while exactly 80 passes."

        Design: Difficulty/dual_variant_calc/crew_duty_projection_vs_chronological_actuals
        """
        ws, order2, _d = self._setup_projection_workspace()

        # Candidate 16:00-16:30 (5 tenths): 75 flown + 10 assigned + 5 = 90.
        from test_helpers import get_order
        v = get_order(order2["id"])["version"]
        resp = api.create_assignment(order2["id"], {
            "aircraft_id": ws["aircraft"]["id"], "pilot_id": ws["pilot"]["id"],
            "planned_start": "2026-08-02T16:00:00Z",
            "planned_end": "2026-08-02T16:30:00Z",
            "expected_dispatch_order_version": v,
        }, OPS)
        validate_error(resp, ApiErrorId.ERR_FLIGHT_HOUR_LIMIT_EXCEEDED,
                       expected_status=422)


class TestFatigueCascade:
    def _setup_fatigue_workspace(self):
        """Pilot ON_INCIDENT on order1 with 79 tenths logged; a second order
        FILLED by the same pilot's still-ASSIGNED assignment B on 2026-08-03."""
        ws = setup_carded_pair()
        order1 = accept_order(place_order(
            ws["contract"]["id"], ws["incident"]["id"],
            order_number="O-1001")["id"])
        a = create_assignment(order1["id"], ws["aircraft"]["id"],
                              ws["pilot"]["id"],
                              "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")
        order2 = accept_order(place_order(
            ws["contract"]["id"], ws["incident"]["id"],
            order_number="O-1002")["id"])
        b = create_assignment(order2["id"], ws["aircraft"]["id"],
                              ws["pilot"]["id"],
                              "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
        from test_helpers import launch_assignment, arrive_assignment
        launch_assignment(a["id"], ws["pilot"]["id"])
        arrive_assignment(a["id"], ws["pilot"]["id"])
        log_sortie(a["id"], ws["pilot"]["id"], "2026-08-02", 100.0, 107.9)
        from test_helpers import get_order
        assert get_order(order2["id"])["status"] == "FILLED"
        return ws, a, b, order2

    def test_fatigue_hold_releases_only_assigned_assignments(self, api):
        """PRD §3.6: "the moment a log raises a duty day's `flown_tenths` to
        80 or more, a four-link cascade fires. The duty day absorbs the new
        tenths; the crew member's `duty_status` flips to `FATIGUE_HOLD` with a
        version bump; every assignment of that pilot still in `ASSIGNED` flips
        to `RELEASED` with `release_reason` `FATIGUE` and `released_at`
        stamped from the clock — assignments already `EN_ROUTE` or
        `ON_INCIDENT` are deliberately left flying".

        Design: Difficulty/transitive_cascade/flight_log_fatigue_four_link_cascade
        """
        ws, a, b, _order2 = self._setup_fatigue_workspace()

        # 79 + 1 == 80 <= 80: the trigger log itself is accepted.
        trigger = log_sortie(a["id"], ws["pilot"]["id"],
                             "2026-08-02", 107.9, 108.0)
        assert trigger["flight_hours_tenths"] == 1

        pilot = get_crew_member(ws["pilot"]["id"])
        assert pilot["duty_status"] == "FATIGUE_HOLD", "cascade link 2"

        b_after = validate_success(api.get_assignment(b["id"], OPS))
        assert b_after["status"] == "RELEASED", "cascade link 3"
        assert b_after["release_reason"] == "FATIGUE"
        assert b_after["released_at"] is not None

        a_after = validate_success(api.get_assignment(a["id"], OPS))
        assert a_after["status"] == "ON_INCIDENT", \
            "the flying assignment is deliberately left untouched"

    def test_fatigue_cascade_bubbles_order_fill_band_down(self, api):
        """PRD §3.6: "each released assignment's order recomputes its fill
        band, stepping `FILLED` down to `PARTIALLY_FILLED`, or a zeroed
        `PARTIALLY_FILLED` back to `ACCEPTED`, bumping order versions as it
        goes."
        PRD §3.4: "`filled_count` always equals the number of the order's
        assignments currently in `ASSIGNED`, `EN_ROUTE`, or `ON_INCIDENT`."

        Design: Difficulty/transitive_cascade/flight_log_fatigue_four_link_cascade
        """
        ws, a, _b, order2 = self._setup_fatigue_workspace()

        log_sortie(a["id"], ws["pilot"]["id"], "2026-08-02", 107.9, 108.0)

        order2_after = validate_success(
            api.get_dispatch_order(order2["id"], OPS))
        assert order2_after["filled_count"] == 0, "cascade link 4 bubble-up"
        assert order2_after["status"] == "ACCEPTED", \
            "a zeroed FILLED order collapses back to ACCEPTED"

        duty_days = list_duty_days(ws["pilot"]["id"])
        day = next(d for d in duty_days if d["duty_date"] == "2026-08-02")
        assert day["flown_tenths"] == 80, "cascade link 1 absorbed the tenths"


class TestSeasonFlightCap:
    def test_season_flight_cap_both_gates(self, api):
        """PRD §3.6: "The season gate refuses the log with
        `ERR_SEASON_FLIGHT_CAP_EXCEEDED` when the contract's
        `season_flight_hours_tenths` plus the new tenths would exceed
        `season_flight_hour_cap_tenths`."
        PRD §3.4: "Placement is gated by the season flight-hour cap — the
        contract's `season_flight_hours_tenths` must still be below
        `season_flight_hour_cap_tenths`, otherwise the order is refused with
        `ERR_SEASON_FLIGHT_CAP_EXCEEDED`."

        Design: Corner/validations/season_flight_cap_both_gates
        """
        ws = setup_on_incident(
            contract_overrides={"season_flight_hour_cap_tenths": 20})
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 0.0, 1.5)  # season at 15 tenths

        # 15 + 6 == 21 > 20: the log gate refuses.
        resp = api.create_flight_log(
            ws["assignment"]["id"],
            {"logged_date": "2026-08-02", "hobbs_start": 1.5, "hobbs_stop": 2.1},
            make_pilot_headers(ws["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SEASON_FLIGHT_CAP_EXCEEDED,
                       expected_status=422)

        # 15 + 5 == 20 <= 20: boundary-inclusive acceptance.
        ok = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                        "2026-08-02", 1.5, 2.0)
        assert ok["flight_hours_tenths"] == 5

        # Season now equals the cap: placement refuses new orders.
        resp2 = api.create_dispatch_order(
            {"order_number": "O-1002", "contract_id": ws["contract"]["id"],
             "incident_id": ws["incident"]["id"], "aircraft_quantity": 1},
            DISPATCH)
        validate_error(resp2, ApiErrorId.ERR_SEASON_FLIGHT_CAP_EXCEEDED,
                       expected_status=422)


class TestPerSortieRounding:
    def test_per_sortie_rounding_on_logs(self, api):
        """PRD §3.6: "first the sortie's duration becomes `flight_hours_tenths`
        by rounding the hour difference times ten half up to a whole tenth;
        then `billable_cents` is computed from those tenths at the contract's
        `flight_hour_rate_cents`, again rounded half up to a whole cent."
        PRD §3.6: "two sorties of 1.05 and 0.65 hours at 300,000 cents per
        hour bill 330,000 plus 210,000".

        Design: Difficulty/combinatorial_formula/flight_billing_per_sortie_then_sum_rounding
        """
        ws = setup_on_incident()

        l1 = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                        "2026-08-02", 100.0, 101.05)
        assert l1["flight_hours_tenths"] == 11, "round_half_up(1.05 * 10)"
        assert l1["billable_cents"] == 330000

        l2 = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                        "2026-08-02", 200.0, 200.65)
        assert l2["flight_hours_tenths"] == 7, "round_half_up(0.65 * 10)"
        assert l2["billable_cents"] == 210000

    def test_invoice_sums_per_sortie_amounts(self, api):
        """PRD §3.6: "Summing raw hours first and rounding once is forbidden,
        because it produces different money — two sorties of 1.05 and 0.65
        hours at 300,000 cents per hour bill 330,000 plus 210,000, that is
        540,000 cents, per-sortie, against 510,000 under sum-first."
        PRD §3.8: "With no availability days at all, the penalty is zero."

        Design: Difficulty/combinatorial_formula/flight_billing_per_sortie_then_sum_rounding
        """
        ws = setup_on_incident()
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 100.0, 101.05)
        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 200.0, 200.65)

        from test_helpers import create_draft_invoice
        invoice = create_draft_invoice(ws["contract"]["id"],
                                       "2026-08-02", "2026-08-02")
        assert invoice["flight_subtotal_cents"] == 540000, \
            "330000 + 210000 per-sortie; the sum-first 510000 is forbidden"
        assert invoice["penalty_cents"] == 0
        assert invoice["net_cents"] == 540000


class TestSeasonHoursLedger:
    def test_derived_field_season_hours_reconciliation(self, api):
        """PRD §3.6: "An accepted sortie adds its tenths to the contract's
        season total — bumping the contract's version — refreshes the duty
        day's `flown_tenths` and `projected_tenths`".
        PRD §2.10: "`season_flight_hours_tenths` tracks every sortie hour
        charged against the season cap."

        Design: Corner/complexity_layers/derived_field_season_hours_reconciliation
        """
        ws = setup_on_incident()

        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 100.0, 101.05)
        contract = get_contract(ws["contract"]["id"])
        assert contract["season_flight_hours_tenths"] == 11

        log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                   "2026-08-02", 200.0, 200.65)
        contract = get_contract(ws["contract"]["id"])
        assert contract["season_flight_hours_tenths"] == 18, \
            "11 + 7: the counter reflects each accepted sortie immediately"
