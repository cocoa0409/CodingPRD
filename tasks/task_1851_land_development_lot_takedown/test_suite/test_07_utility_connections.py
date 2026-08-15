"""Utility providers, impact-fee indexation, and connection scheduling."""
from test_helpers import (
    CLERK,
    DEV,
    ApiErrorId,
    assert_connection,
    create_acquired_parcel,
    create_connection,
    create_connection_payload,
    create_phase,
    create_provider,
    list_phase_lots,
    set_clock,
    setup_connection_scenario,
    validate_error,
    validate_success,
    walk_phase_to_recorded,
)


class TestConnectionSchedulingOrder:
    def test_schedule_past_date_wins_over_capacity(self, api):
        """PRD §2.8: "Requests are screened against a fixed, ordered validation cascade so that the same failure always surfaces as the same error, regardless of how many rules it would violate."
        PRD §2.8: "8. **Temporal rules** — clock and deadline checks such as the contingency deadline and the connection scheduling date; violations yield `ERR_CONTINGENCY_EXPIRED` or `ERR_SCHEDULE_DATE_IN_PAST` (409)."
        PRD §2.8: "9. **Uniqueness, overlap, and capacity** — builder license uniqueness, provider name uniqueness, the one-open-loan rule, phase window overlap, provider daily capacity, the seated-board minimum, and the HOA control threshold (409)."

        Design: Difficulty/priority_pair_validation_conflict/connection_schedule_temporal_vs_constraint
        """
        scenario = setup_connection_scenario(num_lots=2, max_connections_per_day=1)
        provider = scenario["provider"]
        first = create_connection(scenario["lots"][0]["id"], provider["id"],
                                  "2026-08-10T00:00:00Z")
        validate_success(api.schedule_connection(first["id"], CLERK))

        set_clock("2026-08-15T00:00:00Z")
        second = create_connection(scenario["lots"][1]["id"], provider["id"],
                                   "2026-08-10T00:00:00Z")
        # both conditions hold: 2026-08-10 is now a past day AND the day's slot
        # is already full — the temporal rule is checked first
        resp = api.schedule_connection(second["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_DATE_IN_PAST)

    def test_schedule_capacity_full_alone(self, api):
        """PRD §3.9: "Second, the provider must have capacity left on that day: count the provider's connections on the same calendar day in `SCHEDULED` or `CONNECTED` status, and when that count has already reached `max_connections_per_day` the schedule is rejected with `ERR_PROVIDER_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/connection_schedule_temporal_vs_constraint
        """
        scenario = setup_connection_scenario(num_lots=2, max_connections_per_day=1)
        provider = scenario["provider"]
        first = create_connection(scenario["lots"][0]["id"], provider["id"],
                                  "2026-08-10T00:00:00Z")
        validate_success(api.schedule_connection(first["id"], CLERK))
        second = create_connection(scenario["lots"][1]["id"], provider["id"],
                                   "2026-08-10T00:00:00Z")
        # the date is valid at the default clock; capacity is the only violation
        resp = api.schedule_connection(second["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_CAPACITY_EXCEEDED)


class TestProviderDailyCapacity:
    def test_provider_capacity_exact_boundary(self, api):
        """PRD §3.9: "Second, the provider must have capacity left on that day: count the provider's connections on the same calendar day in `SCHEDULED` or `CONNECTED` status, and when that count has already reached `max_connections_per_day` the schedule is rejected with `ERR_PROVIDER_CAPACITY_EXCEEDED`. The boundary is exact: when the count sits one below the maximum the schedule succeeds and the day becomes full."

        Design: Difficulty/resource_temporal_overlap/provider_daily_capacity_aggregate
        """
        scenario = setup_connection_scenario(num_lots=3, max_connections_per_day=2)
        provider = scenario["provider"]
        connections = [
            create_connection(scenario["lots"][i]["id"], provider["id"],
                              "2026-08-20T00:00:00Z")
            for i in range(3)
        ]
        first = validate_success(
            api.schedule_connection(connections[0]["id"], CLERK))
        assert first["status"] == "SCHEDULED"  # used 0 < 2
        second = validate_success(
            api.schedule_connection(connections[1]["id"], CLERK))
        assert second["status"] == "SCHEDULED"  # used 1 < 2 — day becomes full
        resp = api.schedule_connection(connections[2]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_CAPACITY_EXCEEDED)

    def test_provider_capacity_independent_per_calendar_day(self, api):
        """PRD §3.9: "Second, the provider must have capacity left on that day: count the provider's connections on the same calendar day in `SCHEDULED` or `CONNECTED` status, and when that count has already reached `max_connections_per_day` the schedule is rejected with `ERR_PROVIDER_CAPACITY_EXCEEDED`."
        PRD §3.9: "Scheduling consumes one slot of the provider's daily capacity."

        Design: Difficulty/resource_temporal_overlap/provider_daily_capacity_aggregate
        """
        scenario = setup_connection_scenario(num_lots=3, max_connections_per_day=2)
        provider = scenario["provider"]
        for i in range(2):
            conn = create_connection(scenario["lots"][i]["id"], provider["id"],
                                     "2026-08-20T00:00:00Z")
            validate_success(api.schedule_connection(conn["id"], CLERK))
        # 2026-08-20 is now full; 2026-08-21 is an independent bucket
        next_day = create_connection(scenario["lots"][2]["id"], provider["id"],
                                     "2026-08-21T00:00:00Z")
        scheduled = validate_success(
            api.schedule_connection(next_day["id"], CLERK))
        assert scheduled["status"] == "SCHEDULED"


class TestImpactFees:
    def test_impact_fee_indexed_at_default_clock(self, api):
        """PRD §3.9: "The fee indexes a type-specific base by whole years elapsed since the ordinance epoch of 2024-01-01: the elapsed time in days between that epoch and the current clock's date, divided by 365 and rounded down, clamped at zero, gives the year count. The base fees are 250,000 cents for `WATER`, 300,000 cents for `SEWER`, and 175,000 cents for `ELECTRIC`, and the fee is the base multiplied by one plus 300 basis points over ten thousand, that factor raised to the year count — a three-percent annual indexation, compounded — with the result rounded half-up to whole cents as the only rounding step. At the startup clock of 2026-08-01 the year count is two, so a water connection's fee computes to 265,225 cents."

        Design: Corner/calculations/impact_fee_indexation_at_default_clock
        """
        scenario = setup_connection_scenario(num_lots=2, max_connections_per_day=4)
        water = scenario["provider"]
        sewer = create_provider(provider_name="City Sewer", utility_type="SEWER",
                                max_connections_per_day=4)
        water_conn = create_connection(scenario["lots"][0]["id"], water["id"],
                                       "2026-08-20T00:00:00Z")
        sewer_conn = create_connection(scenario["lots"][1]["id"], sewer["id"],
                                       "2026-08-20T00:00:00Z")
        assert_connection(water_conn)
        # 250000 * 1.03^2 at year count two (startup clock 2026-08-01)
        assert water_conn["impact_fee_cents"] == 265225
        # 300000 * 1.03^2
        assert sewer_conn["impact_fee_cents"] == 318270


class TestConnectionStateGuards:
    def test_cancel_connected_connection_rejected(self, api):
        """PRD §3.9: "The developer may cancel from either `REQUESTED` or `SCHEDULED` into terminal `CANCELLED`; cancelling a scheduled connection frees the provider's daily slot for that day. Wrong-state attempts on any of these transitions surface `ERR_CONNECTION_INVALID_STATE`."

        Design: Corner/errors/error_cancel_connected_connection_returns_invalid_state
        """
        scenario = setup_connection_scenario(
            num_lots=1, max_connections_per_day=4,
            provider_overrides={"provider_name": "City Electric",
                                "utility_type": "ELECTRIC"})
        conn = create_connection(scenario["lots"][0]["id"],
                                 scenario["provider"]["id"], "2026-08-20T00:00:00Z")
        validate_success(api.schedule_connection(conn["id"], CLERK))
        connected = validate_success(api.mark_connected(conn["id"], CLERK))
        assert connected["status"] == "CONNECTED"
        resp = api.cancel_connection(conn["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_CONNECTION_INVALID_STATE)

    def test_connection_requires_active_phase(self, api):
        """PRD §3.9: "The lot's phase must be `ACTIVE` — lots in earlier phases are not ready for connections, and the request is rejected with `ERR_PHASE_NOT_READY_FOR_CONNECTIONS`."

        Design: Corner/errors/error_phase_not_ready_for_connections
        """
        parcel = create_acquired_parcel(parcel_name="NRP")
        phase = create_phase(parcel["id"], planned_lot_count=1)
        walk_phase_to_recorded(phase["id"], 1)  # PLAT_RECORDED, never activated
        provider = create_provider()
        lot = list_phase_lots(phase["id"])[0]
        resp = api.create_connection(
            create_connection_payload(lot["id"], provider["id"]), DEV)
        validate_error(resp, ApiErrorId.ERR_PHASE_NOT_READY_FOR_CONNECTIONS)
