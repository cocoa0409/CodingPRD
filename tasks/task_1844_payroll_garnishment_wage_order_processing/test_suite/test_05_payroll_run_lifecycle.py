"""Payroll run lifecycle: half-open period adjacency, terminal lockdown on
void/pay, empty-run and deduction-bound rejections, Texas hours requirement."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_payroll_run_payload,
    create_statement_payload,
    employer_version,
    get_payroll_run,
    list_order_events,
    make_employer,
    make_employee,
    make_open_run,
    make_state_rule,
    pay_run_payload,
    set_clock,
    setup_employer_with_employee,
    setup_paid_single_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import SPECIALIST


class TestPeriodAdjacency:
    def test_abutting_period_start_rejected(self, api):
        """PRD §3.5: "The run window must be internally sound and externally
        disjoint: `period_end` on or after `period_start`, and `period_start`
        strictly after the `period_end` of the employer's latest non-voided
        run, so that consecutive windows neither overlap nor even abut. A
        violation is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409)."
        A start equal to the previous run's period_end (2026-08-15) abuts and
        is rejected.

        Design: Difficulty/resource_temporal_overlap/payroll_run_period_adjacency_half_open
        """
        set_clock()
        emp = make_employer()
        make_open_run(emp["id"])
        resp = api_client.create_payroll_run(
            create_payroll_run_payload(
                emp["id"],
                employer_version(emp["id"]),
                period_start="2026-08-15",
                period_end="2026-08-31",
                pay_date="2026-08-31",
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)

    def test_day_after_period_end_accepted(self, api):
        """PRD §3.5: "`period_start` strictly after the `period_end` of the
        employer's latest non-voided run, so that consecutive windows neither
        overlap nor even abut. A violation is rejected with
        `ERR_PERIOD_OVERLAP` (HTTP 409). A new run is born `OPEN`, and its
        creation appends an audit entry (action `run.create`)."
        Starting 2026-08-16 — one day after the previous period_end — is
        strictly after it and legal.

        Design: Difficulty/resource_temporal_overlap/payroll_run_period_adjacency_half_open
        """
        set_clock()
        emp = make_employer()
        make_open_run(emp["id"])
        resp = api_client.create_payroll_run(
            create_payroll_run_payload(
                emp["id"],
                employer_version(emp["id"]),
                period_start="2026-08-16",
                period_end="2026-08-31",
                pay_date="2026-08-31",
            ),
            SPECIALIST,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "OPEN"
        assert data["period_start"] == "2026-08-16"


class TestTerminalRunLockdown:
    def test_void_paid_run_rejected(self, api):
        """PRD §3.5: "A run that should never have been opened can be voided,
        but only while `OPEN` and only while no statement in it has posted a
        withholding event; a run carrying posted events is rejected with
        `ERR_RUN_HAS_POSTED_EVENTS` (HTTP 409)."
        PRD §2.9: "including any mutation aimed at a terminal-state resource,
        is rejected with `ERR_INVALID_STATE` (HTTP 409)."
        Voiding a PAID (terminal) run is a state violation.

        Design: Corner/state_machines/run_void_with_posted_events_rejected
        """
        base = setup_paid_single_order()
        resp = api_client.void_run(base["run"]["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_payroll_run(base["run"]["id"])["status"] == "PAID"

    def test_second_pay_rejected_events_posted_once(self, api):
        """PRD §3.6: "Payment executes the withholding waterfall independently
        for every statement in the run, posts one `WITHHOLD` withholding event
        per awarded order — idempotently, at most one event per pairing of
        `pay_statement_id` and `garnishment_order_id` — finalizes each
        statement, moves the run to the terminal `PAID` state, increments the
        employer's `version`, and appends one audit entry per statement (action
        `run.pay`)."
        The second pay hits the terminal PAID state and is rejected, so exactly
        one WITHHOLD event exists for the order.

        Design: Corner/state_machines/pay_run_idempotent_second_pay_rejected
        """
        base = setup_paid_single_order()
        resp = api_client.pay_run(
            base["run"]["id"],
            pay_run_payload(employer_version(base["employer"]["id"])),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        events = list_order_events(base["order"]["id"])
        withholds = [e for e in events if e["event_type"] == "WITHHOLD"]
        assert len(withholds) == 1
        assert withholds[0]["amount_cents"] == 10000


class TestRunPreconditions:
    def test_pay_empty_run_rejected(self, api):
        """PRD §3.6: "A `payroll_specialist` pays an `OPEN` run, carrying
        `expected_employer_version` per §2.7; a run with no statements at all
        is rejected with `ERR_RUN_EMPTY` (HTTP 422)."

        Design: Corner/errors/run_empty_pay_rejected
        """
        set_clock()
        make_state_rule("CA")
        emp = make_employer()
        make_employee(emp["id"])
        run = make_open_run(emp["id"])
        resp = api_client.pay_run(
            run["id"], pay_run_payload(employer_version(emp["id"])), SPECIALIST
        )
        validate_error(resp, ApiErrorId.ERR_RUN_EMPTY)
        assert get_payroll_run(run["id"])["status"] == "OPEN"

    @pytest.mark.parametrize("deductions", [50000, 50001])
    def test_invalid_deductions_rejected(self, api, deductions):
        """PRD §3.5: "The deduction bounds are strict:
        `mandatory_deductions_cents` must be non-negative and strictly less
        than `gross_earnings_cents`, else the create is rejected with
        `ERR_INVALID_DEDUCTIONS` (HTTP 422)."
        Deductions equal to (and greater than) the 50000 gross are both
        rejected.

        Design: Corner/errors/invalid_deductions_rejected
        """
        set_clock()
        make_state_rule("CA")
        emp = make_employer()
        ee = make_employee(emp["id"])
        run = make_open_run(emp["id"])
        resp = api_client.create_statement(
            run["id"],
            create_statement_payload(
                ee["id"],
                gross_earnings_cents=50000,
                mandatory_deductions_cents=deductions,
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DEDUCTIONS)

    def test_tx_statement_requires_hours_worked(self, api):
        """PRD §3.5: "The hours rule is state-conditional: for an employee
        whose `work_state_code` is `TX`, `hours_worked` is required and must
        be greater than zero, because the Texas hourly floor test consumes it;
        for every other state the field is ignored, and a missing Texas hours
        value is rejected with `ERR_PERIOD_OVERLAP`."

        Design: Corner/entities/statetement_tx_requires_hours_worked
        """
        base = setup_employer_with_employee(
            state_code="TX",
            state_rule_overrides={
                "hourly_floor_cents": 1000,
                "fee_deductible_from_wages": False,
            },
            employee_overrides={"work_state_code": "TX", "hourly_rate_cents": 2000},
        )
        run = make_open_run(base["employer"]["id"])
        resp = api_client.create_statement(
            run["id"],
            create_statement_payload(
                base["employee"]["id"],
                gross_earnings_cents=100000,
                mandatory_deductions_cents=25000,
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)
