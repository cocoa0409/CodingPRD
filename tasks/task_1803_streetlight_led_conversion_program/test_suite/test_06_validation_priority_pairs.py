"""Validation priority pair conflicts (PRD section 2.10 pipeline order):
state beats fiscal, state beats safety, safety beats constraint."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_program,
    create_crew,
    create_district,
    dispatch_work_order,
    get_program,
    get_work_order,
    make_field_supervisor_headers,
    setup_cleared_pole,
    setup_released_route,
    validate_error,
)

PM = TEST_USERS["program_manager_headers"]


class TestStateBeatsFiscalDispatchSuspendedRouteEmptyBudget:
    def _setup(self):
        """Budget 8000; two UTILITY_OWNED poles attested; two-stop route
        RELEASED; wo1 dispatched (est 4500 debited -> balance 3500); route
        manually SUSPENDED."""
        program = create_active_program(budget=8000)
        district = create_district(program["id"], zone="ARTERIAL")
        crew = create_crew(program["id"])
        poles = [setup_cleared_pole(program, district, crew, pole_number=f"X-0{i}",
                                    ownership_type="UTILITY_OWNED", nameplate_wattage=250)
                 for i in (1, 2)]
        route, stops, wos = setup_released_route(
            program, district, crew, poles, start="2026-08-03", end="2026-08-04")
        dispatch_work_order(wos[0]["id"], crew["id"], wattage=90, cct=3000,
                            shielding="SEMI_CUTOFF")
        resp = api_client.suspend_route(route["id"], PM)
        assert resp.status_code == 200, f"Setup failed: suspend -> {resp.text}"
        return program, crew, route, wos

    def test_suspended_route_dispatch_surfaces_state_error_not_fiscal(self, api):
        """PRD section 2.10: "a failure at any stage short-circuiting the rest —
        so when several rules could fire on one request, the earliest stage
        decides the error the caller sees", with stage "9. Target state" before
        "14. The fiscal gate is evaluated last: ERR_PROGRAM_BUDGET_EXCEEDED."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_dispatch_suspended_route_empty_budget
        """
        program, crew, route, wos = self._setup()
        # wo2's dispatch violates BOTH route state (SUSPENDED) AND the fiscal gate
        # (estimate 4500 > balance 3500); the state error must win.
        resp = api.dispatch_work_order(
            wos[1]["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_SUSPENDED, expected_status=409)

    def test_rejected_dispatch_posts_no_budget(self, api):
        """PRD section 2.5: "Dispatching a work order from `PENDING` debits
        `estimated_labor_cost_cents`" — and a rejected dispatch never reaches the
        posting; the balance stays exactly where the first dispatch left it.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_dispatch_suspended_route_empty_budget
        """
        program, crew, route, wos = self._setup()
        api.dispatch_work_order(
            wos[1]["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        assert get_work_order(wos[1]["id"])["execution_status"] == "PENDING"
        assert get_program(program["id"])["budget_balance_cents"] == 3500


class TestStateBeatsSafetyDispatchCancelledWorkOrderBadCct:
    def _setup(self):
        """One UTILITY_OWNED pole attested on an ARTERIAL route; its work order
        cancelled while PENDING (execution CANCELLED, stop SKIPPED)."""
        program = create_active_program()
        district = create_district(program["id"], zone="ARTERIAL")
        crew = create_crew(program["id"])
        pole = setup_cleared_pole(program, district, crew, pole_number="Y-01",
                                  ownership_type="UTILITY_OWNED", nameplate_wattage=250)
        route, stops, wos = setup_released_route(
            program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
        resp = api_client.cancel_work_order(wos[0]["id"], PM)
        assert resp.status_code == 200, f"Setup failed: cancel -> {resp.text}"
        return program, crew, wos[0]

    def test_cancelled_order_dispatch_surfaces_state_error_not_cct(self, api):
        """PRD section 2.10: stage "9. Target state: the target resource's own
        state must permit the transition" precedes "10. Dark-sky CCT, then
        shielding", and "a failure at any stage short-circuiting the rest".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_dispatch_cancelled_work_order_bad_cct
        """
        _program, crew, wo = self._setup()
        # 5000K violates the 4000K ARTERIAL cap AND the order is CANCELLED;
        # the state error must win.
        resp = api.dispatch_work_order(
            wo["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 5000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_DISPATCHABLE, expected_status=409)

    def test_rejected_dispatch_leaves_order_cancelled(self, api):
        """PRD section 3.4: "The work order itself must be dispatchable
        (`ERR_WORK_ORDER_NOT_DISPATCHABLE`)"; a rejected dispatch mutates nothing.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_dispatch_cancelled_work_order_bad_cct
        """
        _program, crew, wo = self._setup()
        api.dispatch_work_order(
            wo["id"],
            {"new_fixture_wattage": 90, "new_cct_kelvin": 5000, "shielding": "SEMI_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        assert get_work_order(wo["id"])["execution_status"] == "CANCELLED"


class TestSafetyBeatsConstraintDispatchCctAndWattageViolations:
    def _setup(self):
        """RESIDENTIAL (cap 3000K); MUNICIPAL pole audit-accepted at 250W;
        route RELEASED (work order PENDING)."""
        program = create_active_program()
        district = create_district(program["id"], zone="RESIDENTIAL")
        crew = create_crew(program["id"])
        pole = setup_cleared_pole(program, district, crew, pole_number="Z-01",
                                  ownership_type="MUNICIPAL", nameplate_wattage=250,
                                  audited_wattage=250)
        route, stops, wos = setup_released_route(
            program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
        return program, crew, wos[0]

    def test_cct_violation_surfaces_over_wattage_reduction_violation(self, api):
        """PRD section 2.10: "10. Dark-sky CCT, then shielding:
        ERR_CCT_EXCEEDS_ZONE_CAP before ERR_SHIELDING_REQUIRED" precedes
        "12. Uniqueness, capacity, and business constraints, in this relative
        order: ... ERR_INSUFFICIENT_WATTAGE_REDUCTION".

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_dispatch_cct_and_wattage_violations
        """
        _program, crew, wo = self._setup()
        # 5000K > 3000K cap AND 240W vs 250W effective is only a 4% reduction;
        # the safety error must win.
        resp = api.dispatch_work_order(
            wo["id"],
            {"new_fixture_wattage": 240, "new_cct_kelvin": 5000, "shielding": "FULL_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CCT_EXCEEDS_ZONE_CAP, expected_status=422)

    def test_rejected_dispatch_posts_nothing(self, api):
        """PRD section 3.4: "the dark-sky gate: `new_cct_kelvin` must not exceed
        the district's `cct_cap_kelvin`"; the rejected dispatch leaves the work
        order PENDING and the budget intact.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_dispatch_cct_and_wattage_violations
        """
        program, crew, wo = self._setup()
        api.dispatch_work_order(
            wo["id"],
            {"new_fixture_wattage": 240, "new_cct_kelvin": 5000, "shielding": "FULL_CUTOFF"},
            make_field_supervisor_headers(crew["id"]),
        )
        assert get_work_order(wo["id"])["execution_status"] == "PENDING"
        assert get_program(program["id"])["budget_balance_cents"] == 10000000
