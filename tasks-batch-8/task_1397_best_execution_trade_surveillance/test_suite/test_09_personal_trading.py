"""Personal-account trading: identity stamping, lifecycle timestamps,
execution window, holding period, restricted-list interplay, and the
validation priority ladder (PRD §2.10, §3.2, §3.6, §3.9)."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    approve_trade,
    create_restricted_entry_payload,
    make_covered_employee_headers,
    make_employee,
    make_order,
    make_personal_trade,
    ops_run,
    reconcile_trade,
    report_trade_execution,
    set_clock,
    setup_venue_with_active_arrangement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestPreclearanceIdentity:
    def test_personal_trade_employee_id_taken_from_identity(self, api):
        """PRD §3.6: "the trade's `employee_id` is always taken from the
        caller's `X-User-ID` — it is never accepted from the request body.
        New requests land in `PRECLEARANCE_REQUESTED`."

        Design: Corner/entities/personal_trade_employee_id_taken_from_identity
        """
        employee = make_employee(employee_ref="EMP-100", full_name="Ida Self")
        resp = api.create_personal_trade(
            {"symbol": "ACME", "side": "BUY", "quantity": 25},
            make_covered_employee_headers(employee["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["employee_id"] == employee["id"], "server-stamped from X-User-ID"
        assert data["status"] == "PRECLEARANCE_REQUESTED"

    def test_employee_cannot_approve_own_preclearance_returns_403(self, api):
        """PRD §3.6: "Decision-making belongs to a `ComplianceAdmin`."
        PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint — or, for transition endpoints, not permitted for
        the requested transition target — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/employee_cannot_approve_own_preclearance_returns_403
        """
        employee = make_employee(employee_ref="EMP-R2", full_name="Self Approve")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        resp = api.personal_trade_transition(
            trade["id"], {"to_status": "APPROVED"},
            make_covered_employee_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_employee_cannot_report_others_trade_returns_403(self, api):
        """PRD §3.6: "the caller's `X-User-ID` must equal the trade's
        `employee_id` (else `ERR_NOT_RESOURCE_OWNER`)".

        Design: Corner/rbac/employee_cannot_report_others_trade_returns_403
        """
        owner = make_employee(employee_ref="EMP-RA", full_name="Owner A")
        other = make_employee(employee_ref="EMP-RB", full_name="Other B")
        trade = make_personal_trade(owner["id"], symbol="ACME", side="BUY", quantity=10)
        approve_trade(trade["id"])
        resp = api.personal_trade_transition(
            trade["id"],
            {"to_status": "EXECUTION_REPORTED",
             "executed_price_cents": 10000,
             "executed_at": "2026-08-01T00:00:00Z"},
            make_covered_employee_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestLifecycleFields:
    def test_personal_trade_happy_path_stamps_lifecycle_fields(self, api):
        """PRD §3.6: "An approved trade stamps `decided_at` with the logical
        now and sets `expires_at` to the now plus 48 hours". PRD §3.6: "A
        `ComplianceAdmin` then reconciles the reported execution, moving the
        trade to the terminal `RECONCILED` and stamping `reconciled_at`."

        Design: Corner/state_machines/personal_trade_happy_path_stamps_lifecycle_fields
        """
        set_clock("2026-08-05T10:00:00Z")
        employee = make_employee(employee_ref="EMP-120", full_name="Happy Path")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=50)

        approved = approve_trade(trade["id"])
        assert _parse(approved["decided_at"]) == datetime(2026, 8, 5, 10, 0, tzinfo=_parse(approved["decided_at"]).tzinfo)
        assert _parse(approved["expires_at"]) == _parse(approved["decided_at"]) + timedelta(hours=48)

        reported = report_trade_execution(
            trade["id"], employee["id"], 10000, "2026-08-05T12:00:00Z")
        assert reported["status"] == "EXECUTION_REPORTED"

        reconciled = reconcile_trade(trade["id"])
        assert reconciled["status"] == "RECONCILED"
        # The clock never moved past 2026-08-05T10:00:00Z, so the reconcile
        # stamp equals the logical now.
        assert _parse(reconciled["reconciled_at"]) == _parse(approved["decided_at"])

    def test_trade_report_outside_preclearance_window_rejected(self, api):
        """PRD §3.6: "the reported `executed_at` must lie inside the closed
        window from `decided_at` through `expires_at`, both bounds inclusive
        (else `ERR_EXECUTION_WINDOW_VIOLATION`)".

        Design: Corner/state_machines/trade_report_outside_preclearance_window_rejected
        """
        set_clock("2026-08-05T10:00:00Z")
        employee = make_employee(employee_ref="EMP-121", full_name="Win Late")
        t1 = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=50)
        t2 = make_personal_trade(employee["id"], symbol="BBB", side="BUY", quantity=50)
        approve_trade(t1["id"])
        approve_trade(t2["id"])  # both expire at 2026-08-07T10:00:00Z

        resp = api.personal_trade_transition(
            t1["id"],
            {"to_status": "EXECUTION_REPORTED", "executed_price_cents": 10000,
             "executed_at": "2026-08-07T10:00:01Z"},
            make_covered_employee_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_EXECUTION_WINDOW_VIOLATION)

        ok = report_trade_execution(t2["id"], employee["id"], 10000, "2026-08-07T10:00:00Z")
        assert ok["status"] == "EXECUTION_REPORTED", "exactly at expires_at is inside the closed window"

    def test_approved_trade_expires_via_ops_run(self, api):
        """PRD §3.6: "The ops-run checkpoint moves every `APPROVED` trade
        whose `expires_at` has passed to `EXPIRED`." PRD §2.4: the checkpoint
        response reports per-category tallies including
        `preclearances_expired`.

        Design: Corner/state_machines/approved_trade_expires_via_ops_run
        """
        set_clock("2026-08-05T10:00:00Z")
        employee = make_employee(employee_ref="EMP-122", full_name="Will Expire")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=50)
        approve_trade(trade["id"])  # expires 2026-08-07T10:00:00Z

        set_clock("2026-08-07T10:00:01Z")
        tally = ops_run()
        assert tally["preclearances_expired"] == 1
        trades, meta = validate_paginated(api.list_employee_personal_trades(employee["id"], CA))
        assert meta["total_count"] == 1
        assert trades[0]["status"] == "EXPIRED"


class TestHoldingPeriod:
    def test_min_holding_period_exactly_30_days_boundary(self, api):
        """PRD §3.6: "no `RECONCILED` `BUY` trade of the same employee in the
        same symbol may have executed within the trailing thirty days, with
        executions thirty full days (2,592,000 seconds) or more in the past
        being permissible (`ERR_MIN_HOLDING_PERIOD`, HTTP 409)."

        Design: Corner/validations/min_holding_period_exactly_30_days_boundary
        """
        set_clock("2026-08-01T11:00:00Z")
        employee = make_employee(employee_ref="EMP-170", full_name="Hold Period")
        buy = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=50)
        approve_trade(buy["id"])
        report_trade_execution(buy["id"], employee["id"], 10000, "2026-08-01T12:00:00Z")
        reconcile_trade(buy["id"])

        sell = make_personal_trade(employee["id"], symbol="ACME", side="SELL", quantity=50)
        # 29 days 23:59:59 after the BUY execution: still inside the window.
        set_clock("2026-08-31T11:59:59Z")
        resp = api.personal_trade_transition(sell["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp, ApiErrorId.ERR_MIN_HOLDING_PERIOD)
        # Exactly 30*86400 seconds after: permissible.
        set_clock("2026-08-31T12:00:00Z")
        ok = validate_success(api.personal_trade_transition(sell["id"], {"to_status": "APPROVED"}, CA))
        assert ok["status"] == "APPROVED"


class TestRestrictedList:
    def test_restricted_entry_inverted_window_returns_422(self, api):
        """PRD §3.9: "`effective_from` must lie strictly in the future at
        creation and `effective_to` strictly after `effective_from`, with
        violations rejected as `ERR_INVALID_WINDOW`."

        Design: Corner/entities/restricted_entry_inverted_window_returns_422
        """
        resp = api.create_restricted_entry(create_restricted_entry_payload(
            effective_from="2026-09-20T00:00:00Z",
            effective_to="2026-09-10T00:00:00Z",
        ), CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_restricted_entry_backdated_window_returns_422(self, api):
        """PRD §3.9: "`effective_from` must lie strictly in the future at
        creation and `effective_to` strictly after `effective_from`, with
        violations rejected as `ERR_INVALID_WINDOW`."

        Design: Corner/entities/restricted_entry_backdated_window_returns_422
        """
        # Default clock is 2026-08-01T00:00:00Z (PRD §2.4); 2026-07-01 is past.
        resp = api.create_restricted_entry(create_restricted_entry_payload(
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-09-10T00:00:00Z",
        ), CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_exact_one_day_gap_allowed(self, api):
        """PRD §3.9: "the new entry's window, widened by 86,400 seconds (one
        day) on both ends, must not intersect the plain window of any
        `SCHEDULED` or `ACTIVE` entry for the same symbol — a gap of exactly
        one day is allowed, one second less is rejected with
        `ERR_RESTRICTED_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/restricted_list_buffer_gap_boundary
        """
        validate_success(api.create_restricted_entry(create_restricted_entry_payload(
            symbol="ACME", restriction_kind="ALL",
            effective_from="2026-09-10T00:00:00Z", effective_to="2026-09-20T00:00:00Z",
        ), CA), expected_status=201)
        resp = api.create_restricted_entry(create_restricted_entry_payload(
            symbol="ACME", restriction_kind="EMPLOYEE_ONLY",
            effective_from="2026-09-21T00:00:00Z", effective_to="2026-09-25T00:00:00Z",
        ), CA)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED", "the exact one-day gap is allowed"

    def test_one_second_less_gap_rejected(self, api):
        """PRD §3.9: "a gap of exactly one day is allowed, one second less is
        rejected with `ERR_RESTRICTED_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/restricted_list_buffer_gap_boundary
        """
        validate_success(api.create_restricted_entry(create_restricted_entry_payload(
            symbol="ACME", restriction_kind="ALL",
            effective_from="2026-09-10T00:00:00Z", effective_to="2026-09-20T00:00:00Z",
        ), CA), expected_status=201)
        resp = api.create_restricted_entry(create_restricted_entry_payload(
            symbol="ACME", restriction_kind="CLIENT_ONLY",
            effective_from="2026-09-20T23:59:59Z", effective_to="2026-09-26T00:00:00Z",
        ), CA)
        validate_error(resp, ApiErrorId.ERR_RESTRICTED_WINDOW_CONFLICT)

    def test_restricted_activation_denies_pending_preclearance(self, api):
        """PRD §3.9: "The ops-run checkpoint activates a scheduled entry once
        the logical now reaches its `effective_from` while remaining short of
        `effective_to`, and activation immediately denies every still-pending
        personal-trade preclearance in that symbol with `denial_reason`
        `RESTRICTED_LIST`."

        Design: Corner/state_machines/restricted_activation_denies_pending_preclearance
        """
        employee = make_employee(employee_ref="EMP-130", full_name="Pen Ding")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=50)
        entry = validate_success(api.create_restricted_entry(create_restricted_entry_payload(
            symbol="ACME", restriction_kind="ALL",
            effective_from="2026-08-10T00:00:00Z", effective_to="2026-08-20T00:00:00Z",
        ), CA), expected_status=201)

        set_clock("2026-08-12T00:00:00Z")
        tally = ops_run()
        assert tally["restricted_activated"] == 1
        assert tally["preclearances_denied"] == 1

        entry_after = validate_success(api.get_restricted_entry(entry["id"], CA))
        assert entry_after["status"] == "ACTIVE"
        trades, _meta = validate_paginated(api.list_employee_personal_trades(employee["id"], CA))
        by_id = {t["id"]: t for t in trades}
        assert by_id[trade["id"]]["status"] == "DENIED"
        assert by_id[trade["id"]]["denial_reason"] == "RESTRICTED_LIST"

    def test_restricted_kind_selectivity_employee_only_vs_client_only(self, api):
        """PRD §3.9: "The `restriction_kind` scopes the block:
        `EMPLOYEE_ONLY` blocks personal-trade preclearance, `CLIENT_ONLY`
        blocks client order routing, and `ALL` blocks both."

        Design: Corner/validations/restricted_kind_selectivity_employee_only_vs_client_only
        """
        employee = make_employee(employee_ref="EMP-160", full_name="Kind Select")
        for symbol, kind in (("ACME", "EMPLOYEE_ONLY"), ("BETA", "CLIENT_ONLY")):
            validate_success(api.create_restricted_entry(create_restricted_entry_payload(
                symbol=symbol, restriction_kind=kind,
                effective_from="2026-08-10T00:00:00Z", effective_to="2026-08-20T00:00:00Z",
            ), CA), expected_status=201)
        set_clock("2026-08-12T00:00:00Z")
        ops_run()  # both entries flip to ACTIVE

        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        t_acme = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        t_beta = make_personal_trade(employee["id"], symbol="BETA", side="BUY", quantity=10)
        o_acme = make_order(client_ref="K1", symbol="ACME", side="BUY", quantity=10,
                            order_type="MARKET")
        o_beta = make_order(client_ref="K2", symbol="BETA", side="BUY", quantity=10,
                            order_type="MARKET")

        resp_emp = api.personal_trade_transition(t_acme["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp_emp, ApiErrorId.ERR_SYMBOL_RESTRICTED)

        ok_beta = validate_success(api.personal_trade_transition(t_beta["id"], {"to_status": "APPROVED"}, CA))
        assert ok_beta["status"] == "APPROVED", "CLIENT_ONLY does not block preclearance"

        ok_route = validate_success(api.order_transition(
            o_acme["id"], {"to_status": "ROUTED", "arrangement_id": arrangement["id"]}, OPS))
        assert ok_route["status"] == "ROUTED", "EMPLOYEE_ONLY does not block client routing"

        resp_cli = api.order_transition(
            o_beta["id"], {"to_status": "ROUTED", "arrangement_id": arrangement["id"]}, OPS)
        validate_error(resp_cli, ApiErrorId.ERR_SYMBOL_RESTRICTED)


class TestValidationPriority:
    def test_denied_trade_approve_returns_invalid_state(self, api):
        """PRD §2.10: "then state admissibility of the requested transition
        including terminal lockdown (`ERR_INVALID_STATE`), and finally the
        business gates specific to the workflow in the orders stated in §3."
        PRD §3.6: "`DENIED`, `RECONCILED`, and `EXPIRED` are all terminal."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_denied_trade_decide
        """
        employee = make_employee(employee_ref="EMP-601", full_name="Lou Lapsed",
                                 attestation_due_at="2026-07-01T00:00:00Z")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        validate_success(api.personal_trade_transition(
            trade["id"], {"to_status": "DENIED", "denial_reason": "COMPLIANCE_HOLD"}, CA))

        resp = api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] != "ERR_ATTESTATION_LAPSED", (
            "state admissibility precedes the business gates, so the terminal-state "
            "error wins even though the employee is also attestation-LAPSED")

    def test_employee_created_lapsed_from_past_deadline(self, api):
        """PRD §3.1: "Its initial value is computed at creation against the
        logical clock: if the supplied `attestation_due_at` has already been
        reached or passed, the employee starts `LAPSED`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_denied_trade_decide
        """
        employee = make_employee(employee_ref="EMP-601", full_name="Lou Lapsed",
                                 attestation_due_at="2026-07-01T00:00:00Z")
        assert employee["attestation_status"] == "LAPSED", (
            "the 2026-07-01 deadline is already past at the default clock 2026-08-01")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        validate_success(api.personal_trade_transition(
            trade["id"], {"to_status": "DENIED", "denial_reason": "COMPLIANCE_HOLD"}, CA))
        # The dual failure (terminal DENIED state + LAPSED attestation) still
        # resolves to the state error.
        resp = api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
