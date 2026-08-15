"""Non-linear state machine instances: the outage reopen cycle with priority
escalation on a frozen SLA clock, and the work order's parallel execution/QC
dimensions through the QC-fail rework loop."""
from test_helpers import (
    TEST_USERS,
    create_active_program,
    create_crew,
    create_district,
    create_pole,
    create_ticket,
    dispatch_and_complete,
    find_salvage_item_for_pole,
    get_pole,
    get_ticket,
    get_work_order,
    list_work_orders_for_route,
    make_citizen_reporter_headers,
    make_field_supervisor_headers,
    make_qa_inspector_headers,
    resolve_ticket,
    set_clock,
    setup_cleared_pole,
    setup_released_route,
    triage_and_dispatch_ticket,
    validate_success,
)
from test_helpers import (
    dispatch_work_order as fx_dispatch_work_order,
)

PM = TEST_USERS["program_manager_headers"]
QA1 = TEST_USERS["qa_inspector_headers"]


class TestOutageReopenCycleEscalatesPriorityKeepsClock:
    def _setup(self):
        """STANDARD ticket (T1 pole, RESIDENTIAL, no hazard) resolved at +48h
        under the default 96h window, then reopened."""
        program = create_active_program()
        district = create_district(program["id"], zone="RESIDENTIAL")
        crew = create_crew(program["id"])
        pole = create_pole(district["id"], pole_number="O-01", ownership_type="UTILITY_OWNED",
                           fixture_class="COBRA_HEAD", nameplate_wattage=90)
        ticket = create_ticket(pole["id"], reporter_user_id="citizen-1",
                               description="lamp out", hazard_flag=False)
        triage_and_dispatch_ticket(ticket["id"], crew["id"])
        set_clock("2026-08-03T00:00:00Z")
        first = resolve_ticket(ticket["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")
        return program, district, crew, pole, first

    def test_reopen_escalates_priority_without_resetting_sla_clock(self, api):
        """PRD section 3.6: "it increments reopen_count by one, escalates priority
        exactly one level (STANDARD to HIGH, HIGH to CRITICAL, CRITICAL
        unchanged), and recomputes sla_hours from the escalated priority, while
        deliberately leaving reported_at untouched so the next resolution still
        measures from the original report."

        Design: Difficulty/non_linear_state_machine/outage_reopen_cycle_escalates_priority_keeps_clock
        """
        _program, _district, crew, _pole, first = self._setup()
        # First resolution at 48h elapsed: 48 <= 96 is not a breach under STANDARD
        assert first["sla_breached"] is False

        resp = api.reopen_ticket(first["id"], make_citizen_reporter_headers("citizen-1"))
        reopened = validate_success(resp)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        assert reopened["priority"] == "HIGH"
        assert reopened["sla_hours"] == 48
        assert reopened["reported_at"] == "2026-08-01T00:00:00Z"

    def test_cycle_completes_and_second_resolution_breaches_escalated_window(self, api):
        """PRD section 3.6: "A reopened ticket is triaged again, re-asserting the
        escalated values" and "sla_breached is true only when the elapsed time
        from reported_at to resolved_at strictly exceeds sla_hours".

        Design: Difficulty/non_linear_state_machine/outage_reopen_cycle_escalates_priority_keeps_clock
        """
        _program, _district, crew, _pole, first = self._setup()
        api.reopen_ticket(first["id"], make_citizen_reporter_headers("citizen-1"))
        # REOPENED -> TRIAGED -> DISPATCHED -> RESOLVED
        resp = api.triage_ticket(first["id"], PM)
        triaged = validate_success(resp)
        assert triaged["status"] == "TRIAGED"
        assert triaged["priority"] == "HIGH" and triaged["sla_hours"] == 48
        resp = api.dispatch_ticket(first["id"], {"crew_id": crew["id"]}, PM)
        validate_success(resp)
        set_clock("2026-08-04T02:00:00Z")
        second = resolve_ticket(first["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")
        # 74 elapsed hours > escalated 48h HIGH window
        assert second["status"] == "RESOLVED"
        assert second["sla_breached"] is True


class TestWorkOrderParallelDimsQcFailReworkLoop:
    def _setup_completed_work_order(self):
        """One MUNICIPAL pole 250W audit-accepted; conversion work order
        dispatched and completed (pole CONVERTED, qc AWAITING_QC)."""
        program = create_active_program()
        district = create_district(program["id"], zone="RESIDENTIAL")
        crew = create_crew(program["id"])
        pole = setup_cleared_pole(program, district, crew, pole_number="Q-01",
                                  ownership_type="MUNICIPAL", nameplate_wattage=250,
                                  audited_wattage=250)
        route, stops, wos = setup_released_route(
            program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
        wo = dispatch_and_complete(wos[0]["id"], crew["id"], wattage=90, cct=2700,
                                   shielding="FULL_CUTOFF")
        return program, district, crew, pole, stops[0], wo

    def test_qc_fail_moves_execution_only_and_rework_leaves_qc_dimension(self, api):
        """PRD section 3.4: "A fail moves QC to QC_FAILED, execution COMPLETED ->
        REWORK_PENDING, and a conversion order's pole CONVERTED -> REWORK";
        "dispatch from REWORK_PENDING updates the fixture fields from the new
        payload and posts nothing"; "Every completion moves the QC dimension to
        AWAITING_QC — from NONE on a first completion, from QC_FAILED on a rework
        completion".

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dims_qc_fail_rework_loop
        """
        _program, _d, crew, pole, _stop, wo = self._setup_completed_work_order()
        resp = api.qc_fail_work_order(wo["id"], QA1)
        validate_success(resp)
        mid = get_work_order(wo["id"])
        assert mid["execution_status"] == "REWORK_PENDING"
        assert mid["qc_status"] == "QC_FAILED"
        assert get_pole(pole["id"])["status"] == "REWORK"

        fx_dispatch_work_order(wo["id"], crew["id"], wattage=90, cct=2700,
                               shielding="FULL_CUTOFF")
        re = get_work_order(wo["id"])
        # Execution dimension moved; qc dimension UNCHANGED through rework dispatch
        assert re["execution_status"] == "DISPATCHED"
        assert re["qc_status"] == "QC_FAILED"

    def test_rework_completion_resets_qc_and_qc_pass_verifies_pole(self, api):
        """PRD section 3.4: "A pass moves QC to QC_PASSED: a conversion order's
        pole goes CONVERTED -> VERIFIED"; "At the first completion of each work
        order only — the moment est_reconciled flips — exactly one salvage item
        is auto-created for the removed fixture ... rework re-completions create
        none."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dims_qc_fail_rework_loop
        """
        _program, _d, crew, pole, _stop, wo = self._setup_completed_work_order()
        api.qc_fail_work_order(wo["id"], QA1)
        fx_dispatch_work_order(wo["id"], crew["id"], wattage=90, cct=2700,
                               shielding="FULL_CUTOFF")
        resp = api.complete_work_order(wo["id"], make_field_supervisor_headers(crew["id"]))
        reworked = validate_success(resp)
        assert reworked["execution_status"] == "COMPLETED"
        assert reworked["qc_status"] == "AWAITING_QC"
        assert get_pole(pole["id"])["status"] == "CONVERTED"

        resp = api.qc_pass_work_order(wo["id"], QA1)
        passed = validate_success(resp)
        assert passed["qc_status"] == "QC_PASSED"
        assert passed["execution_status"] == "COMPLETED"
        assert get_pole(pole["id"])["status"] == "VERIFIED"

        # Exactly one salvage item exists for the pole — rework re-completion created none
        resp = api.list_salvage_items(PM, params={"pole_id": pole["id"]})
        items = resp.json()["data"]
        assert len(items) == 1, f"expected exactly one salvage item, got {len(items)}"
