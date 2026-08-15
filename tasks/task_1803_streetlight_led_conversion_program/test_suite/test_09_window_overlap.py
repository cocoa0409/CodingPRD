"""Resource temporal overlap instances: half-open rate schedule windows vs
closed crew route windows — opposite adjacency semantics on two resources."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_program,
    create_crew,
    create_district,
    create_rate_schedule_payload,
    create_route,
    get_route,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]

MUNI_RATES = {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600}


class TestRateScheduleHalfOpenWindowAdjacency:
    def _setup(self):
        """ACTIVE program; MUNICIPAL schedule A [2026-01-01, 2026-07-01) FILED."""
        program = create_active_program()
        resp = api_client.create_rate_schedule(
            create_rate_schedule_payload(
                program["id"], ownership_class="MUNICIPAL",
                effective_from="2026-01-01", effective_until="2026-07-01",
                tier_rates=MUNI_RATES,
            ), BA)
        rs_a = validate_success(resp, expected_status=201)
        resp = api_client.file_rate_schedule(rs_a["id"], BA)
        validate_success(resp)
        return program, rs_a

    def test_adjacent_window_files_cleanly(self, api):
        """PRD section 2.7: "Rate schedule windows are half-open:
        `effective_from` is inclusive, `effective_until` is exclusive"; "pure
        adjacency — one window's `effective_until` equal to the other's
        `effective_from`, or vice versa — is allowed."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_window_adjacency
        """
        program, _rs_a = self._setup()
        resp = api_client.create_rate_schedule(
            create_rate_schedule_payload(
                program["id"], ownership_class="MUNICIPAL",
                effective_from="2026-07-01",
                tier_rates={"T1": 720, "T2": 1120, "T3": 1520, "T4": 2020, "T5": 2620},
            ), BA)
        rs_b = validate_success(resp, expected_status=201)
        resp = api_client.file_rate_schedule(rs_b["id"], BA)
        filed = validate_success(resp)
        # adjacency until==from is NOT an overlap under half-open semantics
        assert filed["status"] == "FILED"

    def test_overlapping_window_rejected_and_left_draft(self, api):
        """PRD section 2.7: "filing a schedule whose window so overlaps a FILED
        or EFFECTIVE sibling of the same program and ownership class is rejected
        with ERR_RATE_WINDOW_OVERLAP".

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_window_adjacency
        """
        program, _rs_a = self._setup()
        resp = api_client.create_rate_schedule(
            create_rate_schedule_payload(
                program["id"], ownership_class="MUNICIPAL",
                effective_from="2026-06-15",
                tier_rates={"T1": 710, "T2": 1110, "T3": 1510, "T4": 2010, "T5": 2610},
            ), BA)
        rs_c = validate_success(resp, expected_status=201)
        resp = api_client.file_rate_schedule(rs_c["id"], BA)
        # 2026-06-15 < 2026-07-01 intersects A's interior
        validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP, expected_status=409)
        resp = api_client.get_rate_schedule(rs_c["id"], BA)
        assert validate_success(resp)["status"] == "DRAFT"  # rejected file leaves it unfiled


class TestCrewRouteClosedIntervalSharedDayConflict:
    def _setup(self):
        """ACTIVE program, ARTERIAL district, crew; route A [2026-08-03,
        2026-08-05] PLANNED."""
        program = create_active_program()
        district = create_district(program["id"], zone="ARTERIAL")
        crew = create_crew(program["id"])
        route_a = create_route(district["id"], crew["id"],
                               start="2026-08-03", end="2026-08-05")
        return program, district, crew, route_a

    def test_back_to_back_windows_do_not_conflict(self, api):
        """PRD section 2.7: "Crew route windows are closed intervals. Both
        window_start_date and window_end_date are inclusive ... two
        non-CANCELLED routes assigned to the same crew may not share a single
        calendar day".

        Design: Difficulty/resource_temporal_overlap/crew_route_closed_interval_shared_day_conflict
        """
        _program, district, crew, route_a = self._setup()
        route_b = create_route(district["id"], crew["id"],
                               start="2026-08-06", end="2026-08-08")
        # windows [03,05] and [06,08] share no calendar day: both create cleanly
        assert get_route(route_a["id"])["status"] == "PLANNED"
        assert get_route(route_b["id"])["status"] == "PLANNED"

    def test_shared_single_day_is_a_conflict(self, api):
        """PRD section 2.7: "routes whose windows merely touch on the same day
        are in conflict, and the second creation is rejected with
        ERR_ROUTE_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/crew_route_closed_interval_shared_day_conflict
        """
        _program, district, crew, _route_a = self._setup()
        create_route(district["id"], crew["id"], start="2026-08-06", end="2026-08-08")
        resp = api_client.create_route(
            {
                "district_id": district["id"],
                "crew_id": crew["id"],
                "window_start_date": "2026-08-05",
                "window_end_date": "2026-08-07",
                "traffic_control_required": False,
            },
            PM,
        )
        # 08-05 is inside BOTH closed windows [03,05] and [05,07]
        validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_OVERLAP, expected_status=409)
        resp = api_client.list_routes(PM, params={"crew_id": crew["id"]})
        data = resp.json()["data"]
        assert len(data) == 2, "creation rejected atomically: no third route exists"
