"""Boundary precision instances: SLA breach strictly-greater at the exact
window, and CCT cap equality at the kelvin boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_program,
    create_crew,
    create_district,
    create_pole,
    create_ticket,
    get_district,
    get_work_order,
    list_work_orders_for_route,
    make_field_supervisor_headers,
    resolve_ticket,
    set_clock,
    setup_cleared_pole,
    setup_released_route,
    triage_and_dispatch_ticket,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestSlaBreachStrictlyGreaterAtExactWindow:
    def _setup_two_standard_tickets(self):
        """Two UTILITY_OWNED 90W poles (T1 -> STANDARD 96h); both tickets
        reported at the default clock 2026-08-01T00:00:00Z, triaged and
        dispatched."""
        program = create_active_program()
        district = create_district(program["id"], zone="RESIDENTIAL")
        crew = create_crew(program["id"])
        p1 = create_pole(district["id"], pole_number="T-01", ownership_type="UTILITY_OWNED",
                         fixture_class="COBRA_HEAD", nameplate_wattage=90)
        p2 = create_pole(district["id"], pole_number="T-02", ownership_type="UTILITY_OWNED",
                         fixture_class="COBRA_HEAD", nameplate_wattage=90)
        ta = create_ticket(p1["id"], reporter_user_id="citizen-1",
                           description="out A", hazard_flag=False)
        tb = create_ticket(p2["id"], reporter_user_id="citizen-1",
                           description="out B", hazard_flag=False)
        triage_and_dispatch_ticket(ta["id"], crew["id"])
        triage_and_dispatch_ticket(tb["id"], crew["id"])
        return crew, ta, tb

    def test_resolution_at_exactly_96h_is_not_a_breach(self, api):
        """PRD section 3.6: "sla_breached is true only when the elapsed time
        from reported_at to resolved_at strictly exceeds sla_hours — landing
        exactly on the SLA is not a breach."; "The SLA is 24 hours for CRITICAL,
        48 for HIGH, 96 for STANDARD."

        Design: Difficulty/boundary_precision_check/sla_breach_strictly_greater_at_exact_window
        """
        crew, ta, _tb = self._setup_two_standard_tickets()
        set_clock("2026-08-05T00:00:00Z")  # exactly reported_at + 96h
        resolved = resolve_ticket(ta["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")
        assert resolved["sla_hours"] == 96
        assert resolved["priority"] == "STANDARD"
        assert resolved["sla_breached"] is False  # 96h00m elapsed is NOT > 96h

    def test_resolution_at_97h_breaches(self, api):
        """PRD section 3.6: "sla_breached is true only when the elapsed time
        from reported_at to resolved_at strictly exceeds sla_hours".

        Design: Difficulty/boundary_precision_check/sla_breach_strictly_greater_at_exact_window
        """
        crew, _ta, tb = self._setup_two_standard_tickets()
        set_clock("2026-08-05T01:00:00Z")  # reported_at + 97h
        resolved = resolve_ticket(tb["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")
        assert resolved["sla_hours"] == 96
        assert resolved["priority"] == "STANDARD"
        assert resolved["sla_breached"] is True  # 97h00m elapsed IS > 96h


class TestCctCapEqualityAllowedOneOverRejected:
    def _setup(self):
        """RURAL district (cap 2200, full-cutoff required); two UTILITY_OWNED
        250W poles attested; route 2026-08-03..04 with both, RELEASED."""
        program = create_active_program()
        district = create_district(program["id"], zone="RURAL")
        crew = create_crew(program["id"])
        p1 = setup_cleared_pole(program, district, crew, pole_number="K-01",
                                ownership_type="UTILITY_OWNED", nameplate_wattage=250)
        p2 = setup_cleared_pole(program, district, crew, pole_number="K-02",
                                ownership_type="UTILITY_OWNED", nameplate_wattage=250)
        route, stops, wos = setup_released_route(
            program, district, crew, [p1, p2], start="2026-08-03", end="2026-08-04")
        return district, crew, wos

    def test_dispatch_at_exactly_the_cap_is_allowed(self, api):
        """PRD section 3.4: "the dark-sky gate: `new_cct_kelvin` must not exceed
        the district's `cct_cap_kelvin`"; PRD section 2.6: "The district's
        `cct_cap_kelvin` is 3000 for `RESIDENTIAL`, 4000 for `ARTERIAL`, 2700
        for `DOWNTOWN`, and 2200 for `RURAL`."

        Design: Difficulty/boundary_precision_check/cct_cap_equality_allowed_one_over_rejected
        """
        district, crew, wos = self._setup()
        resp = api.dispatch_work_order(
            wos[0]["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 2200, "shielding": "FULL_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        dispatched = validate_success(resp)
        assert dispatched["execution_status"] == "DISPATCHED"  # 2200K == cap is allowed (<=)
        assert get_district(district["id"])["cct_cap_kelvin"] == 2200

    def test_dispatch_one_kelvin_over_is_rejected(self, api):
        """PRD section 3.4: "`new_cct_kelvin` must not exceed the district's
        `cct_cap_kelvin` unless the pole holds an `APPROVED` `CCT_WAIVER` whose
        `requested_cct_kelvin` covers the requested value and whose
        `valid_until` has not passed".

        Design: Difficulty/boundary_precision_check/cct_cap_equality_allowed_one_over_rejected
        """
        district, crew, wos = self._setup()
        resp = api.dispatch_work_order(
            wos[1]["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 2201, "shielding": "FULL_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CCT_EXCEEDS_ZONE_CAP, expected_status=422)
        assert get_work_order(wos[1]["id"])["execution_status"] == "PENDING"
