"""Inspection booking, findings, repair cycles, and rework gates
(PRD §2.8, §2.10, §3.7, §3.8)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    build_user_headers, create_inspection_finding_payload,
    create_repair_order_payload, create_inspector_payload,
    new_ctx,
    setup_ctx_entry_in_progress, setup_ctx_entry_complete,
    setup_ctx_inspection_accepted,
    add_inspector, create_inspection, run_inspection,
    begin_and_verify_flush, contractor_headers, inspector_headers,
    fresh_inspector_version, get_job,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]

CRITICAL_SHELL = {"severity": "CRITICAL",
                  "description": "shell thinning below minimum",
                  "requires_repair": True}


class TestCriticalFindingGates:
    def test_repair_ordered_critical_blocks_flush_until_resolved(self, api):
        """PRD §3.8: "Moving `INSPECTION_ACCEPTED` to `FLUSH_IN_PROGRESS` — the owning supervisor's act — is barred while any `CRITICAL` finding on the accepted inspection stands in `OPEN` or `REPAIR_ORDERED`, failing which `ERR_CRITICAL_FINDINGS_OPEN`."
        PRD §3.7: "Acceptance here is blocked only by `OPEN` critical findings; the later flush and return-to-service gates of §3.8 are stricter and also count `REPAIR_ORDERED` ones."

        Design: Difficulty/cross_entity_state_dependency/begin_flush_blocked_by_repair_ordered_critical
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        create_inspection(ctx)
        inspection = ctx["inspection"]
        validate_success(api.start_inspection(
            inspection["id"], inspector_headers(ctx)), 200)
        finding = validate_success(api.create_inspection_finding(
            create_inspection_finding_payload(inspection["id"],
                                              **CRITICAL_SHELL),
            inspector_headers(ctx)), 201)
        validate_success(api.report_inspection(
            inspection["id"], inspector_headers(ctx)), 200)
        # Repair order flips the finding OPEN -> REPAIR_ORDERED before accept.
        repair = validate_success(api.create_repair_order(
            create_repair_order_payload(finding["id"]), OPERATOR), 201)
        accepted = validate_success(
            api.accept_inspection(inspection["id"], OPERATOR), 200)
        assert accepted["status"] == "ACCEPTED"
        assert get_job(ctx)["status"] == "INSPECTION_ACCEPTED"

        res = api.begin_flush(ctx["job"]["id"], contractor_headers(ctx))
        validate_error(res, ApiErrorId.ERR_CRITICAL_FINDINGS_OPEN)

        validate_success(api.start_repair(repair["id"], contractor_headers(ctx)), 200)
        validate_success(api.complete_repair(repair["id"], contractor_headers(ctx)),
                         200)
        validate_success(api.verify_repair(repair["id"], inspector_headers(ctx)), 200)
        finding_after = validate_success(
            api.get_inspection_finding(finding["id"], OPERATOR), 200)
        assert finding_after["status"] == "RESOLVED"

        flushing = validate_success(
            api.begin_flush(ctx["job"]["id"], contractor_headers(ctx)), 200)
        assert flushing["status"] == "FLUSH_IN_PROGRESS"

    def test_open_critical_finding_blocks_inspection_accept(self, api):
        """PRD §3.7: "then the critical-findings rule, which rejects acceptance with `ERR_CRITICAL_FINDINGS_OPEN` (HTTP 409) while any `CRITICAL` finding of this inspection remains `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/begin_flush_blocked_by_repair_ordered_critical
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        create_inspection(ctx)
        run_inspection(ctx, findings=[CRITICAL_SHELL], accept=False)
        res = api.accept_inspection(ctx["inspection"]["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_CRITICAL_FINDINGS_OPEN)
        after = validate_success(
            api.get_inspection(ctx["inspection"]["id"], OPERATOR), 200)
        assert after["status"] == "REPORTED"


class TestInspectorCalendar:
    def _ctx_with_first_inspection(self, api):
        ctx = setup_ctx_entry_in_progress()
        add_inspector(ctx)
        first = create_inspection(ctx, "2026-05-03T00:00:00Z",
                                  "2026-05-03T08:00:00Z")
        return ctx, first

    def test_back_to_back_adjacency_allowed(self, api):
        """PRD §2.8: "On an inspector's calendar, only true intersection matters: a new inspection overlapping an existing `SCHEDULED` or `IN_PROGRESS` inspection of the same inspector is rejected with `ERR_INSPECTOR_UNAVAILABLE` (HTTP 409), while back-to-back adjacency — the new start exactly equal to an existing end — is explicitly allowed."
        PRD §3.7: "Booking advances the inspector's `version` by one and lands the inspection in `SCHEDULED`."

        Design: Difficulty/resource_temporal_overlap/inspector_calendar_back_to_back_semantics
        """
        ctx, first = self._ctx_with_first_inspection(api)
        v_before = fresh_inspector_version(ctx["inspector"]["id"])
        second = create_inspection(ctx, "2026-05-03T08:00:00Z",
                                   "2026-05-03T16:00:00Z")
        assert second["status"] == "SCHEDULED"
        v_after = fresh_inspector_version(ctx["inspector"]["id"])
        assert v_after == v_before + 1

    def test_one_minute_overlap_rejected(self, api):
        """PRD §2.8: "On an inspector's calendar, only true intersection matters: a new inspection overlapping an existing `SCHEDULED` or `IN_PROGRESS` inspection of the same inspector is rejected with `ERR_INSPECTOR_UNAVAILABLE` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/inspector_calendar_back_to_back_semantics
        """
        ctx, _ = self._ctx_with_first_inspection(api)
        create_inspection(ctx, "2026-05-03T08:00:00Z", "2026-05-03T16:00:00Z")
        inspector_id = ctx["inspector"]["id"]
        res = api.create_inspection(
            {"job_id": ctx["job"]["id"], "inspector_id": inspector_id,
             "scheduled_start": "2026-05-03T15:59:00Z",
             "scheduled_end": "2026-05-03T17:00:00Z",
             "expected_inspector_version": fresh_inspector_version(inspector_id)},
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_INSPECTOR_UNAVAILABLE)


class TestInspectionReportCycle:
    def test_reject_amend_cycle_then_accept(self, api):
        """PRD §3.7: "Rejection instead moves `REPORTED` to `REJECTED`, and the assigned inspector may amend a rejected report — `REJECTED` back to `REPORTED` — to re-file it."
        PRD §3.7: "Acceptance moves the job `INSPECTION_IN_PROGRESS` to `INSPECTION_ACCEPTED` automatically."

        Design: Corner/state_machines/inspection_reject_amend_cycle
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        create_inspection(ctx)
        run_inspection(ctx, accept=False)
        inspection = ctx["inspection"]
        assert inspection["status"] == "REPORTED"

        rejected = validate_success(
            api.reject_inspection(inspection["id"], OPERATOR), 200)
        assert rejected["status"] == "REJECTED"
        amended = validate_success(
            api.amend_inspection(inspection["id"], inspector_headers(ctx)), 200)
        assert amended["status"] == "REPORTED"
        accepted = validate_success(
            api.accept_inspection(inspection["id"], OPERATOR), 200)
        assert accepted["status"] == "ACCEPTED"
        assert get_job(ctx)["status"] == "INSPECTION_ACCEPTED"

    def test_accept_by_reporting_inspector_violates_segregation(self, api):
        """PRD §3.7: "Acceptance is the terminal operator's gate and evaluates two checks in order: segregation of duties first — the acceptor's `X-User-ID` must differ from `reported_by_user_id`, failing which `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/rbac/inspection_accept_sod_same_user_rejected
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        create_inspection(ctx)
        run_inspection(ctx, accept=False)
        res = api.accept_inspection(
            ctx["inspection"]["id"],
            build_user_headers(ctx["inspector"]["id"], "TerminalOperator"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(
            api.get_inspection(ctx["inspection"]["id"], OPERATOR), 200)
        assert after["status"] == "REPORTED"

    def test_start_by_wrong_inspector_forbidden(self, api):
        """PRD §3.7: "Starting the inspection belongs to the assigned `API653Inspector`: the caller's `X-User-ID` must equal the inspection's `inspector_id` (`ERR_FORBIDDEN_FOR_ROLE` otherwise)"

        Design: Corner/rbac/inspection_start_by_wrong_inspector_forbidden
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        other = validate_success(api.create_inspector(
            create_inspector_payload(name="InspB", certification_level="BOTH"),
            ADMIN), 201)
        create_inspection(ctx)
        res = api.start_inspection(
            ctx["inspection"]["id"],
            build_user_headers(other["id"], "API653Inspector"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = validate_success(
            api.get_inspection(ctx["inspection"]["id"], OPERATOR), 200)
        assert after["status"] == "SCHEDULED"


class TestFindingDisposition:
    def test_minor_finding_accepted_as_risk_then_inspection_accepted(self, api):
        """PRD §3.7: "A `TerminalOperator` may accept a finding as risk, moving `OPEN` to `ACCEPTED_RISK`, but only for `MINOR` and `MAJOR` severities"
        PRD §3.7: "the critical-findings rule, which rejects acceptance with `ERR_CRITICAL_FINDINGS_OPEN` (HTTP 409) while any `CRITICAL` finding of this inspection remains `OPEN`."

        Design: Corner/state_machines/finding_accept_risk_minor
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        create_inspection(ctx)
        run_inspection(ctx, findings=[{"severity": "MINOR",
                                       "description": "surface rust specks",
                                       "requires_repair": False}],
                       accept=False)
        finding = ctx["findings"][0]
        accepted_risk = validate_success(
            api.accept_risk_finding(finding["id"], OPERATOR), 200)
        assert accepted_risk["status"] == "ACCEPTED_RISK"
        accepted = validate_success(
            api.accept_inspection(ctx["inspection"]["id"], OPERATOR), 200)
        assert accepted["status"] == "ACCEPTED"

    def test_critical_finding_cannot_be_risk_accepted(self, api):
        """PRD §3.7: "A `TerminalOperator` may accept a finding as risk, moving `OPEN` to `ACCEPTED_RISK`, but only for `MINOR` and `MAJOR` severities — a `CRITICAL` finding rejects the attempt with `ERR_FINDING_NOT_RISK_ACCEPTABLE` (HTTP 409)."

        Design: Corner/validations/accept_risk_on_critical_finding_rejected
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        create_inspection(ctx)
        run_inspection(ctx, findings=[CRITICAL_SHELL], accept=False)
        finding = ctx["findings"][0]
        res = api.accept_risk_finding(finding["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_FINDING_NOT_RISK_ACCEPTABLE)
        after = validate_success(
            api.get_inspection_finding(finding["id"], OPERATOR), 200)
        assert after["status"] == "OPEN"


class TestRepairCycle:
    def test_repair_reject_loops_back_then_verify_resolves_finding(self, api):
        """PRD §3.7: "Verification marks the order `VERIFIED` — its terminal state — and resolves the finding from `REPAIR_ORDERED` to `RESOLVED`; rejection instead returns the order `COMPLETED` to `IN_PROGRESS` for another work pass."

        Design: Corner/state_machines/repair_reject_cycle_returns_to_in_progress
        """
        ctx = setup_ctx_entry_complete()
        add_inspector(ctx)
        create_inspection(ctx)
        run_inspection(ctx, findings=[CRITICAL_SHELL], accept=False)
        finding = ctx["findings"][0]
        repair = validate_success(api.create_repair_order(
            create_repair_order_payload(finding["id"]), OPERATOR), 201)
        validate_success(api.start_repair(repair["id"], contractor_headers(ctx)), 200)
        validate_success(api.complete_repair(repair["id"], contractor_headers(ctx)),
                         200)

        rejected = validate_success(
            api.reject_repair(repair["id"], inspector_headers(ctx)), 200)
        assert rejected["status"] == "IN_PROGRESS"

        validate_success(api.complete_repair(repair["id"], contractor_headers(ctx)),
                         200)
        verified = validate_success(
            api.verify_repair(repair["id"], inspector_headers(ctx)), 200)
        assert verified["status"] == "VERIFIED"
        finding_after = validate_success(
            api.get_inspection_finding(finding["id"], OPERATOR), 200)
        assert finding_after["status"] == "RESOLVED"


class TestReworkGate:
    def test_order_rework_without_findings_rejected(self, api):
        """PRD §3.7: "Once the inspection has been accepted, a `TerminalOperator` may order rework, but only while at least one finding on the accepted inspection stands in `OPEN` or `REPAIR_ORDERED` — with nothing reworkable outstanding, the request is rejected with `ERR_NO_REWORKABLE_FINDINGS` (HTTP 409)."

        Design: Corner/validations/order_rework_without_findings_rejected
        """
        ctx = setup_ctx_inspection_accepted()  # no findings recorded
        res = api.order_rework(ctx["job"]["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_NO_REWORKABLE_FINDINGS)
        assert get_job(ctx)["status"] == "INSPECTION_ACCEPTED"
