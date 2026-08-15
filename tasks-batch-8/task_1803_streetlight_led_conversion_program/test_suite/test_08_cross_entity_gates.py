"""Cross-entity state dependency instances: dispatch gated by parent route
state, and billing-line period close gated by account posture."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_active_program,
    create_crew,
    create_district,
    dispatch_work_order,
    generate_lines,
    get_account,
    get_route,
    get_work_order,
    list_lines,
    make_field_supervisor_headers,
    setup_cleared_pole,
    setup_effective_rate_schedule,
    setup_released_route,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]

UTIL_RATES = {"T1": 900, "T2": 1300, "T3": 1800, "T4": 2400, "T5": 3000}


class TestDispatchBlockedWhileRouteSuspended:
    def _setup(self):
        """ARTERIAL district; two UTILITY_OWNED poles attested; two-stop route
        RELEASED; wo1 dispatched (route auto RELEASED -> IN_PROGRESS); route
        manually SUSPENDED."""
        program = create_active_program()
        district = create_district(program["id"], zone="ARTERIAL")
        crew = create_crew(program["id"])
        poles = [setup_cleared_pole(program, district, crew, pole_number=f"V-0{i}",
                                    ownership_type="UTILITY_OWNED", nameplate_wattage=250)
                 for i in (1, 2)]
        route, stops, wos = setup_released_route(
            program, district, crew, poles, start="2026-08-03", end="2026-08-04")
        dispatch_work_order(wos[0]["id"], crew["id"], wattage=90, cct=3000,
                            shielding="SEMI_CUTOFF")
        resp = api_client.suspend_route(route["id"], PM)
        assert resp.status_code == 200, f"Setup failed: suspend -> {resp.text}"
        return program, crew, route, wos

    def test_dispatch_rejected_while_parent_route_suspended(self, api):
        """PRD section 3.4: "The route, when the order is route-linked, must be
        RELEASED or IN_PROGRESS; a SUSPENDED route rejects with
        ERR_ROUTE_SUSPENDED".

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_while_route_suspended
        """
        _program, crew, route, wos = self._setup()
        resp = api.dispatch_work_order(
            wos[1]["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_SUSPENDED, expected_status=409)
        assert get_work_order(wos[1]["id"])["execution_status"] == "PENDING"

    def test_resume_readmits_identical_dispatch(self, api):
        """PRD section 3.3: "Resume moves SUSPENDED -> IN_PROGRESS and is never
        automatic; it requires twice the blocked count to be strictly less than
        stop_count"; PRD section 3.3: "moves the route RELEASED -> IN_PROGRESS on
        the route's first dispatch" (§3.4 dispatch side effect).

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_while_route_suspended
        """
        _program, crew, route, wos = self._setup()
        # First dispatch auto-moved the route RELEASED -> IN_PROGRESS
        assert get_route(route["id"])["status"] == "SUSPENDED"
        resp = api_client.resume_route(route["id"], PM)
        resumed = validate_success(resp)
        assert resumed["status"] == "IN_PROGRESS"  # blocked_stop_count == 0 passes the gate
        resp = api.dispatch_work_order(
            wos[1]["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        dispatched = validate_success(resp)
        assert dispatched["execution_status"] == "DISPATCHED"


class TestPeriodCloseBlockedWhileAccountFrozen:
    def _setup(self):
        """UTILITY_OWNED pole 250W attested; UTILITY_OWNED schedule EFFECTIVE;
        account AC-U with one ESTIMATED line (1800); account then FROZEN."""
        program = create_active_program()
        district = create_district(program["id"], zone="RESIDENTIAL")
        crew = create_crew(program["id"])
        pole = setup_cleared_pole(program, district, crew, pole_number="W-01",
                                  ownership_type="UTILITY_OWNED", nameplate_wattage=250)
        setup_effective_rate_schedule(program["id"], "UTILITY_OWNED", tier_rates=UTIL_RATES)
        acct = create_account(district["id"], "UTILITY_OWNED", account_number="AC-U")
        generate_lines(acct["id"])
        resp = api_client.freeze_tariff_account(acct["id"], BA)
        assert resp.status_code == 200, f"Setup failed: freeze -> {resp.text}"
        return program, acct, pole

    def test_close_period_rejected_while_account_frozen(self, api):
        """PRD section 3.5: "line generation and period close both require
        `OPEN` (`ERR_ACCOUNT_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/period_close_blocked_while_account_frozen
        """
        _program, acct, _pole = self._setup()
        resp = api.close_period(acct["id"], BA)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN, expected_status=409)
        # While frozen nothing moved
        account = get_account(acct["id"])
        assert account["status"] == "FROZEN"
        assert account["current_period"] == "2026-08"
        lines = list_lines(account_id=acct["id"], period="2026-08")
        assert lines[0]["status"] == "ESTIMATED"

    def test_unfreeze_lets_identical_close_succeed_and_advance_period(self, api):
        """PRD section 3.5: "Closing the period moves the account's `ESTIMATED`
        lines of `current_period` to `BILLED`, recomputes `ytd_billed_cents`";
        "resets `current_period_estimated_cents` to zero, and advances
        `current_period` by one month"; "Freezing moves `OPEN` → `FROZEN` and
        unfreezing returns it".

        Design: Difficulty/cross_entity_state_dependency/period_close_blocked_while_account_frozen
        """
        _program, acct, _pole = self._setup()
        resp = api_client.unfreeze_tariff_account(acct["id"], BA)
        validate_success(resp)
        resp = api.close_period(acct["id"], BA)
        closed = validate_success(resp)
        assert closed["status"] == "OPEN"
        assert closed["current_period"] == "2026-09"
        # utility whole-month: no conversion, full T3 rate 1800 billed
        assert closed["ytd_billed_cents"] == 1800
        assert closed["current_period_estimated_cents"] == 0
        line = list_lines(account_id=acct["id"], period="2026-08")[0]
        assert line["status"] == "BILLED" and line["charge_cents"] == 1800
