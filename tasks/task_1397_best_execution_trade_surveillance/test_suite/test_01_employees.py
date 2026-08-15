"""Covered employees: creation defaults, attestation dimension, employment
dimension, termination cascade, and the preclearance gates they feed
(PRD §3.1, §3.6)."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    approve_trade,
    assert_employee,
    is_valid_uuid,
    make_covered_employee_headers,
    make_employee,
    make_lexicon_active,
    make_comm_item,
    make_personal_trade,
    ops_run,
    publish_policy,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestEmployeeCreation:
    def test_create_employee_applies_system_defaults(self, api):
        """PRD §3.1: "A `ComplianceAdmin` onboards a covered employee by
        supplying the employee's `full_name`, an external `employee_ref`, a
        `department`, and an `attestation_due_at` deadline." PRD §3.1:
        "otherwise the employee starts `CURRENT`."

        Design: Corner/entities/create_employee_applies_system_defaults
        """
        resp = api.create_employee({
            "full_name": "Ada New",
            "employee_ref": "EMP-001",
            "department": "TRADING",
            "attestation_due_at": "2027-01-01T00:00:00Z",
        }, CA)
        data = validate_success(resp, expected_status=201)
        assert_employee(data)
        assert data["employment_status"] == "ACTIVE", "employees are born ACTIVE"
        # 2027-01-01 is more than 30 days past the default clock 2026-08-01.
        assert data["attestation_status"] == "CURRENT"
        assert data["version"] == 1, "a fresh resource carries version 1"
        assert data["open_case_count"] == 0
        assert data["training_overdue_count"] == 0
        assert data["last_attested_at"] is None
        assert is_valid_uuid(data["id"])

    def test_duplicate_employee_ref_rejected(self, api):
        """PRD §3.1: "The `employee_ref` must be unique across all employees;
        a duplicate is rejected with `ERR_DUPLICATE_EMPLOYEE_REF` (HTTP 409)."

        Design: Corner/entities/duplicate_employee_ref_rejected
        """
        make_employee(employee_ref="EMP-900", full_name="First One")
        resp = api.create_employee({
            "full_name": "Second One",
            "employee_ref": "EMP-900",
            "department": "COMPLIANCE",
            "attestation_due_at": "2027-01-01T00:00:00Z",
        }, CA)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_REF)


class TestEmployeeParallelDimensions:
    def test_attestation_dimension_gates_preclearance(self, api):
        """PRD §3.1: "an employee in `CURRENT` moves to `DUE` once the logical
        now reaches thirty days before the deadline while still short of it, an
        employee in `DUE` moves to `LAPSED` once the now reaches the deadline".
        PRD §3.6: "the employee's `attestation_status` must not be `LAPSED`
        (`ERR_ATTESTATION_LAPSED`)".

        Design: Difficulty/non_linear_state_machine/employee_parallel_dimensions_gate_preclearance
        """
        employee = make_employee(
            employee_ref="EMP-401", full_name="Pat Parallel",
            department="OPERATIONS",
            attestation_due_at="2026-09-10T00:00:00Z",
        )
        # 2026-09-01 is 9 days before the 2026-09-10 deadline -> CURRENT to DUE.
        set_clock("2026-09-01T00:00:00Z")
        run1 = ops_run()
        assert run1["attestations_due"] == 1, "due-window sweep must flip exactly one employee"
        # 2026-09-11 is past the deadline -> DUE to LAPSED.
        set_clock("2026-09-11T00:00:00Z")
        run2 = ops_run()
        assert run2["attestations_lapsed"] == 1

        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        resp = api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_LAPSED)

        # Self-service attestation cycles LAPSED -> CURRENT (PRD §3.1).
        att = validate_success(api.attest(employee["id"], make_covered_employee_headers(employee["id"])))
        assert att["attestation_status"] == "CURRENT"

    def test_employment_dimension_gates_preclearance_independently(self, api):
        """PRD §3.6: "the employee's `employment_status` must be `ACTIVE`
        (`ERR_EMPLOYEE_NOT_ACTIVE`); the employee's `attestation_status` must
        not be `LAPSED` (`ERR_ATTESTATION_LAPSED`)".

        Design: Difficulty/non_linear_state_machine/employee_parallel_dimensions_gate_preclearance
        """
        employee = make_employee(
            employee_ref="EMP-401", full_name="Pat Parallel",
            department="OPERATIONS",
            attestation_due_at="2026-09-10T00:00:00Z",
        )
        set_clock("2026-09-01T00:00:00Z")
        ops_run()
        set_clock("2026-09-11T00:00:00Z")
        ops_run()
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)

        # Clear the attestation dimension, then exercise the employment gate.
        validate_success(api.attest(employee["id"], make_covered_employee_headers(employee["id"])))
        validate_success(api.employment_transition(employee["id"], {"to_status": "ON_LEAVE"}, CA))
        resp = api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)

        # Reinstatement closes the cycle: both gates now pass.
        validate_success(api.employment_transition(employee["id"], {"to_status": "ACTIVE"}, CA))
        ok = validate_success(api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA))
        assert ok["status"] == "APPROVED"


class TestLapsedAttestationPreclearance:
    def test_lapsed_attestation_blocks_approval(self, api):
        """PRD §3.1: "if the supplied `attestation_due_at` has already been
        reached or passed, the employee starts `LAPSED`". PRD §3.6: "the
        employee's `attestation_status` must not be `LAPSED`
        (`ERR_ATTESTATION_LAPSED`)".

        Design: Difficulty/cross_entity_state_dependency/preclearance_blocked_by_lapsed_attestation
        """
        employee = make_employee(employee_ref="EMP-901", full_name="Uma Gate",
                                 attestation_due_at="2026-07-01T00:00:00Z")
        assert employee["attestation_status"] == "LAPSED"
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)

        resp = api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_LAPSED)

        trades, meta = validate_paginated(
            api.list_employee_personal_trades(employee["id"], CA))
        assert meta["total_count"] == 1
        assert trades[0]["status"] == "PRECLEARANCE_REQUESTED", "rejected approval must not move the trade"

    def test_attest_then_approve_sets_expiry_window(self, api):
        """PRD §3.1: "A successful attestation sets `attestation_status` to
        `CURRENT`, stamps `last_attested_at` with the logical now (it remains
        null until the first attestation), and pushes `attestation_due_at`
        forward to the now plus 365 days".
        PRD §3.6: "An approved trade stamps `decided_at` with the logical now
        and sets `expires_at` to the now plus 48 hours".

        Design: Difficulty/cross_entity_state_dependency/preclearance_blocked_by_lapsed_attestation
        """
        employee = make_employee(employee_ref="EMP-901", full_name="Uma Gate",
                                 attestation_due_at="2026-07-01T00:00:00Z")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        owner = make_covered_employee_headers(employee["id"])

        att = validate_success(api.attest(employee["id"], owner))
        assert att["attestation_status"] == "CURRENT"
        assert _parse(att["attestation_due_at"]) == _parse(att["last_attested_at"]) + timedelta(days=365)

        ok = validate_success(api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA))
        assert ok["status"] == "APPROVED"
        assert _parse(ok["expires_at"]) == _parse(ok["decided_at"]) + timedelta(hours=48)
        # The default logical clock is 2026-08-01T00:00:00Z (PRD §2.4), and it
        # was never advanced in this test.
        assert _parse(ok["decided_at"]) == datetime(2026, 8, 1, tzinfo=timezone.utc)


class TestTerminationAndAttestLockout:
    def test_employee_termination_cascades_trades_and_training(self, api):
        """PRD §3.1: "Termination is a compensating event with three cascades,
        all fired at once: every personal trade of the employee still awaiting
        a decision (in `PRECLEARANCE_REQUESTED`) is denied with `denial_reason`
        set to `EMPLOYMENT_ENDED`; every approved-but-unexecuted trade (in
        `APPROVED`) is flipped to `EXPIRED`; and every training assignment of
        the employee in `ASSIGNED` or `OVERDUE` is cancelled."

        Design: Corner/state_machines/employee_termination_cascades_trades_and_training
        """
        employee = make_employee(employee_ref="EMP-140", full_name="Term Inee")
        t1 = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=50)
        t2 = make_personal_trade(employee["id"], symbol="BBB", side="BUY", quantity=50)
        approve_trade(t2["id"])
        publish_policy(version_label="v2026.1")

        resp = api.employment_transition(employee["id"], {"to_status": "TERMINATED"}, CA)
        data = validate_success(resp)
        assert data["employment_status"] == "TERMINATED"

        trades, _ = validate_paginated(api.list_employee_personal_trades(employee["id"], CA))
        by_id = {t["id"]: t for t in trades}
        assert by_id[t1["id"]]["status"] == "DENIED"
        assert by_id[t1["id"]]["denial_reason"] == "EMPLOYMENT_ENDED"
        assert by_id[t2["id"]]["status"] == "EXPIRED"

        assignments, meta = validate_paginated(
            api.list_training_assignments(CA, params={"employee_id": employee["id"]}))
        assert meta["total_count"] == 1
        assert assignments[0]["status"] == "CANCELLED"

    def test_attest_on_terminated_employee_rejected(self, api):
        """PRD §3.1: "Attestation is refused for a terminated employee with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/attest_on_terminated_employee_rejected
        """
        employee = make_employee(employee_ref="EMP-141", full_name="Gone Already",
                                 attestation_due_at="2026-07-01T00:00:00Z")
        validate_success(api.employment_transition(employee["id"], {"to_status": "TERMINATED"}, CA))
        resp = api.attest(employee["id"], make_covered_employee_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_employee_cannot_attest_for_other_returns_403(self, api):
        """PRD §3.1: "A `CoveredEmployee` attests for their own record — the
        path identifier must equal the caller's `X-User-ID`, otherwise
        `ERR_NOT_RESOURCE_OWNER`".

        Design: Corner/rbac/employee_cannot_attest_for_other_returns_403
        """
        owner = make_employee(employee_ref="EMP-RE", full_name="Owner A")
        other = make_employee(employee_ref="EMP-RF", full_name="Other B")
        resp = api.attest(owner["id"], make_covered_employee_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestOpenCaseGate:
    def test_open_case_blocks_new_preclearance(self, api):
        """PRD §3.6: "the employee's `open_case_count` must be zero
        (`ERR_OPEN_SURVEILLANCE_CASE`)". PRD §3.8: "a score of 100 or more
        lands it directly in `ESCALATED` and immediately opens a surveillance
        case on the author".

        Design: Corner/errors/open_case_blocks_new_preclearance
        """
        employee = make_employee(employee_ref="EMP-180", full_name="Case Blocked")
        make_lexicon_active([{"term": "guarantee", "weight": 100}])
        make_comm_item(employee["id"], "guarantee", channel="CHAT")

        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=10)
        resp = api.personal_trade_transition(trade["id"], {"to_status": "APPROVED"}, CA)
        validate_error(resp, ApiErrorId.ERR_OPEN_SURVEILLANCE_CASE)

        refreshed = validate_success(api.get_employee(employee["id"], CA))
        assert refreshed["open_case_count"] == 1, "comm auto-escalation opened one case"
