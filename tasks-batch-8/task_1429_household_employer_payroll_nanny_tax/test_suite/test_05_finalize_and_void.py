"""Pay run finalization gates, FICA/FUTA boundaries, and paycheck voiding."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_worker,
    bind_policy,
    classify_worker,
    create_agreement,
    create_approved_timesheet,
    create_filing,
    create_pay_run,
    create_policy,
    create_rule_pack,
    create_worker,
    get_employer,
    get_worker,
    get_tax_accounts_by_type,
    lapse_policy,
    line_amount,
    list_worker_paychecks,
    make_payroll_admin_headers,
    make_work_entries,
    prepare_filing,
    setup_active_worker,
    setup_calculated_pay_run,
    setup_finalized_pay_run,
    setup_registered_employer,
    terminate_worker,
    validate_error,
    validate_paginated,
    validate_success,
    void_paycheck,
)


class TestFicaCoverageBoundary:
    def _setup_three_workers(self, api):
        """Three ACTIVE workers whose single weekly checks land below, just below,
        and exactly at the FICA coverage threshold: 150000, 279950, 280000."""
        create_rule_pack("BB", sit_rate=0.0)
        employer = setup_registered_employer("BB")
        specs = [("W One", 3000), ("W Two", 5599), ("W Three", 5600)]
        workers = []
        for name, guarantee in specs:
            w = create_worker(
                employer["id"], full_name=name, ssn="123456789", work_state_code="BB"
            )
            classify_worker(employer["id"], w["id"], "EMPLOYEE")
            create_agreement(employer["id"], w["id"], guaranteed_minutes_per_week=guarantee)
            activate_worker(employer["id"], w["id"])
            workers.append(get_worker(w["id"]))
        return employer, workers

    def test_exactly_at_threshold_covers_one_cent_below_does_not(self, api):
        """PRD §3.8: "The coverage test is exact — at least 280000 triggers — and is evaluated in `pay_date` ascending order, with `created_at` ascending as tiebreaker."
        PRD §3.6: "FICA coverage at calculate time is evaluated on the projected year-to-date figure: the worker is treated as covered when `cash_wages_ytd_cents` plus the gross of this run's already-calculated paychecks for the same worker plus this paycheck's `gross_cents` is at least 280000 cents (the FICA coverage threshold — $2,800 of cash wages in the calendar year)."

        Design: Difficulty/boundary_precision_check/fica_coverage_boundary_exact
        """
        employer, workers = self._setup_three_workers(api)
        w1, w2, w3 = workers
        run = setup_finalized_pay_run(employer["id"])

        # W1: gross 150000 (< 280000) -> no FICA lines.
        c1 = list_worker_paychecks(w1["id"])[0]
        assert c1["gross_cents"] == 150000
        assert line_amount(c1["withholding_lines"], "SS_EE") is None
        assert line_amount(c1["withholding_lines"], "MEDICARE_EE") is None
        assert c1["net_pay_cents"] == 150000

        # W2: gross 279950 (50 cents under) -> not covered.
        c2 = list_worker_paychecks(w2["id"])[0]
        assert c2["gross_cents"] == 279950
        assert line_amount(c2["withholding_lines"], "SS_EE") is None
        assert c2["net_pay_cents"] == 279950

        # W3: gross exactly 280000 -> covered: SS 17360, Medicare 4060.
        c3 = list_worker_paychecks(w3["id"])[0]
        assert c3["gross_cents"] == 280000
        assert line_amount(c3["withholding_lines"], "SS_EE") == 17360
        assert line_amount(c3["withholding_lines"], "MEDICARE_EE") == 4060
        assert c3["net_pay_cents"] == 258580

    def test_crossing_check_withholds_retroactive_catch_up(self, api):
        """PRD §3.8: "At finalize, the computed lines are applied: `cash_wages_ytd_cents` advances by gross; when this check is the crossing check, **all** wages paid this year become FICA wages — including earlier checks whose FICA base was zero at issue — with their gross withheld on this check as the catch-up base, still capped by the remaining SS wage-base room."

        Design: Difficulty/boundary_precision_check/fica_coverage_boundary_exact
        """
        employer, workers = self._setup_three_workers(api)
        w1, w2, w3 = workers
        setup_finalized_pay_run(employer["id"], "2026-01-05", "2026-01-12", "2026-01-12")
        terminate_worker(employer["id"], w2["id"])
        terminate_worker(employer["id"], w3["id"])
        run2 = setup_finalized_pay_run(employer["id"], "2026-01-12", "2026-01-19", "2026-01-19")

        # W1's second check: projected YTD 300000 >= 280000, and the base includes
        # the retroactive catch-up of check 1's 150000 -> base 300000.
        resp = api.list_pay_run_paychecks(run2["id"], make_payroll_admin_headers())
        checks, _meta = validate_paginated(resp)
        assert len(checks) == 1
        c = checks[0]
        assert c["gross_cents"] == 150000
        assert line_amount(c["withholding_lines"], "SS_EE") == 18600
        assert line_amount(c["withholding_lines"], "MEDICARE_EE") == 4350
        assert c["net_pay_cents"] == 127050


class TestFutaQuarterTriggerBoundary:
    def _setup_employer_with_wages(self, api, legal_name, fein, hourly_rate, guarantee):
        employer = setup_registered_employer("FF", legal_name=legal_name, fein=fein)
        w = create_worker(employer["id"], full_name=f"{legal_name} W", ssn="123456789",
                          work_state_code="FF")
        classify_worker(employer["id"], w["id"], "EMPLOYEE")
        create_agreement(employer["id"], w["id"], hourly_rate_cents=hourly_rate,
                         guaranteed_minutes_per_week=guarantee)
        activate_worker(employer["id"], w["id"])
        setup_finalized_pay_run(employer["id"])
        filing = create_filing(employer["id"], 2026, 1)
        return employer, filing

    def test_one_cent_under_trigger_futa_does_not_apply(self, api):
        """PRD §3.8: "FUTA applies for a quarter when the household's total cash wages with `pay_date` inside the quarter reach 100000 cents ($1,000) — the boundary is exact, at-least triggers."

        Design: Difficulty/boundary_precision_check/futa_quarter_trigger_boundary
        """
        create_rule_pack("FF", min_wage_cents=60, sit_rate=0.0)
        # 1 cent/min x 99999 min -> quarterly wages 99999, one cent under.
        _e1, filing = self._setup_employer_with_wages(api, "Fam F1", "123456789", 60, 99999)
        prepared = prepare_filing(filing["id"], "admin-1")
        assert prepared["total_cash_wages_cents"] == 99999
        assert prepared["futa_applies"] is False
        assert prepared["futa_due_cents"] == 0

    def test_exactly_at_trigger_futa_applies(self, api):
        """PRD §3.8: "FUTA applies for a quarter when the household's total cash wages with `pay_date` inside the quarter reach 100000 cents ($1,000) — the boundary is exact, at-least triggers."
        PRD §3.10: "Preparation works from either `OPEN` or `REJECTED` status (any other from-state yields `ERR_INVALID_STATE`) and recomputes the filing's figures from the current ledger: `total_cash_wages_cents` (household cash wages with `pay_date` inside the quarter over `ISSUED` paychecks), `futa_applies` (whether `total_cash_wages_cents` reaches the 100000-cent FUTA quarterly trigger — the boundary is exact), `futa_due_cents` and `suta_due_cents` (quarterly accruals over per-worker remaining wage bases), and `estimated_federal_payment_cents` (the safe-harbor quarterly figure)."

        Design: Difficulty/boundary_precision_check/futa_quarter_trigger_boundary
        """
        create_rule_pack("FF", min_wage_cents=60, sit_rate=0.0)
        # 50 cents/min x 2000 min -> quarterly wages exactly 100000.
        _e2, filing = self._setup_employer_with_wages(api, "Fam F2", "223456789", 3000, 2000)
        prepared = prepare_filing(filing["id"], "admin-1")
        assert prepared["total_cash_wages_cents"] == 100000
        assert prepared["futa_applies"] is True
        assert prepared["futa_due_cents"] == 600


class TestFinalizeGates:
    def _setup_restricted_employer_with_open_run(self, api):
        """Workers'-comp-mandated state, no policy: the employer posture is
        RESTRICTED; the pay run is left OPEN (never calculated)."""
        create_rule_pack("EE", workers_comp_required=True, sit_rate=0.0)
        employer, worker, _a = setup_active_worker(
            "EE",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY",),
        )
        run = create_pay_run(employer["id"], "2026-01-05", "2026-01-12", "2026-01-12")
        return employer, worker, run

    def test_finalize_open_run_returns_invalid_state_not_safety_errors(self, api):
        """PRD §2.8: "**State-machine preconditions** — the target transition's `from`-state and any parent-status gates; failure yields `ERR_INVALID_STATE`, with the pay-run-finalize staleness gate surfacing as `ERR_PAYRUN_STALE`."
        PRD §2.8: "**Business safety** — compliance posture and workers' compensation coverage gates on pay-run finalize; failures yield `ERR_EMPLOYER_RESTRICTED` or `ERR_WORKERS_COMP_REQUIRED` respectively."

        Design: Difficulty/priority_pair_validation_conflict/finalize_wrong_state_beats_workers_comp_safety
        """
        _e, _w, run = self._setup_restricted_employer_with_open_run(api)
        resp = api.finalize_pay_run(run["id"], make_payroll_admin_headers())
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] != "ERR_EMPLOYER_RESTRICTED"
        assert err["error_id"] != "ERR_WORKERS_COMP_REQUIRED"

    def test_restricted_posture_confirmed_while_state_gate_wins(self, api):
        """PRD §2.9: "The posture is `RESTRICTED` when any `ACTIVE` worker's work-state rule pack has `workers_comp_required` set to true and no `WorkersCompPolicy` in `BOUND` or `ACTIVE` status has a `[coverage_start, coverage_end]` window that covers the logical-clock current date."
        PRD §3.6: "The preconditions fire in pipeline order: the run must be in `CALCULATED` (else `ERR_INVALID_STATE`); `recalc_status` must be `CURRENT` (else `ERR_PAYRUN_STALE`, HTTP 409);"

        Design: Difficulty/priority_pair_validation_conflict/finalize_wrong_state_beats_workers_comp_safety
        """
        employer, _w, run = self._setup_restricted_employer_with_open_run(api)
        assert get_employer(employer["id"])["compliance_posture"] == "RESTRICTED"
        resp = api.finalize_pay_run(run["id"], make_payroll_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWorkersCompPosture:
    def test_lapsing_only_covering_policy_flips_posture_restricted(self, api):
        """PRD §3.11: "A `PayrollAdmin` may lapse a policy from either `BOUND` or `ACTIVE`; the lapse recomputes the employer's posture and may force it to `RESTRICTED` when the state mandates coverage and no other `BOUND` or `ACTIVE` policy covers today."

        Design: Corner/state_machines/policy_lapse_flips_posture_restricted
        """
        create_rule_pack("EE", workers_comp_required=True, sit_rate=0.0)
        employer, worker, _a = setup_active_worker(
            "EE", agencies=("NEW_HIRE_DIRECTORY",)
        )
        policy = create_policy(employer["id"], "EE", "2026-01-01", "2026-12-31")
        bind_policy(policy["id"])
        # The BOUND policy covers the default clock date 2026-08-01 -> CLEAR.
        assert get_employer(employer["id"])["compliance_posture"] == "CLEAR"

        lapse_policy(policy["id"])
        assert get_employer(employer["id"])["compliance_posture"] == "RESTRICTED"


class TestFinalizeImmediateConsistency:
    def test_finalize_response_and_paycheck_reflect_final_state(self, api):
        """PRD §4: "Endpoints that modify an existing resource — including all state transitions, sweeps, and approvals — return HTTP **200** with the updated resource in `data`."
        PRD §3.6: "On success, member paychecks transition `CALCULATED → ISSUED`; `deposit_status` moves `PENDING → SENT`; `stub_status` moves `PENDING → DELIVERED`, or `PENDING → NOT_REQUIRED` when the work-state pack's `pay_stub_required` is false."

        Design: Corner/consistency_model/finalize_response_reflects_state_immediately
        """
        employer, worker, _a = setup_active_worker(
            "AA",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        run = setup_calculated_pay_run(employer["id"])
        resp = api.finalize_pay_run(run["id"], make_payroll_admin_headers())
        data = validate_success(resp, 200)
        assert data["status"] == "FINALIZED"
        assert data["total_net_cents"] == 114000

        resp = api.list_pay_run_paychecks(run["id"], make_payroll_admin_headers())
        checks, _meta = validate_paginated(resp)
        assert len(checks) == 1
        assert checks[0]["status"] == "ISSUED"
        assert checks[0]["deposit_status"] == "SENT"
        assert checks[0]["stub_status"] == "DELIVERED"


class TestPaycheckVoid:
    def _setup_two_issued_paychecks(self, api):
        """Two ISSUED paychecks of 120000 each: W1 via a 2400-minute timesheet,
        W2 via the guarantee fallback."""
        create_rule_pack("BB", sit_rate=0.0)
        employer, w1, _a = setup_active_worker(
            "BB",
            worker_overrides={"full_name": "Pam One", "ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        create_approved_timesheet(
            employer["id"], w1["id"], "2026-01-05", "2026-01-12",
            make_work_entries("2026-01-05", [600, 600, 600, 600]),
        )
        w2 = create_worker(employer["id"], full_name="Pam Two", ssn="123456789",
                           work_state_code="BB")
        classify_worker(employer["id"], w2["id"], "EMPLOYEE")
        create_agreement(employer["id"], w2["id"], guaranteed_minutes_per_week=2400)
        activate_worker(employer["id"], w2["id"])
        run = setup_finalized_pay_run(employer["id"])
        return employer, w1, w2, run

    def test_void_flips_paycheck_and_recomputes_payrun_totals(self, api):
        """PRD §3.6: "Voiding transitions the paycheck `ISSUED → VOIDED`; `deposit_status` moves to `REVERSAL_PENDING` when it was `SENT`."
        PRD §3.6: "The parent pay run's totals are recomputed over non-`VOIDED` paychecks (the compensating invariant is that `total_net_cents` equals the sum of non-`VOIDED` `net_pay_cents`)."

        Design: Difficulty/compensating_invariant/paycheck_void_conserves_payrun_totals
        """
        employer, w1, w2, run = self._setup_two_issued_paychecks(api)
        target = list_worker_paychecks(w1["id"])[0]
        resp = api.void_paycheck(target["id"], make_payroll_admin_headers())
        voided = validate_success(resp, 200)
        assert voided["status"] == "VOIDED"
        assert voided["deposit_status"] == "REVERSAL_PENDING"

        resp = api.get_pay_run(run["id"], make_payroll_admin_headers())
        run_after = validate_success(resp, 200)
        assert run_after["total_net_cents"] == 120000
        assert run_after["total_gross_cents"] == 120000
        # Surviving check only: FUTA 720 + SUTA 2400 = 3120.
        assert run_after["total_employer_tax_cents"] == 3120

    def test_void_reverses_worker_wages_and_tax_accruals(self, api):
        """PRD §3.6: "The worker's `cash_wages_ytd_cents`, `ss_wages_paid_ytd_cents`, and `futa_wages_ytd_cents` are decremented by this paycheck's contribution, and `fica_covered` is re-evaluated; if coverage is lost, accrued FICA lines for the year's checks are reversed through `TaxLiabilityAccount`."
        PRD §3.6: "Account `accrued_cents` are decremented per line, `balance_cents` recomputed, and the employer's `compliance_posture` recomputed."

        Design: Difficulty/compensating_invariant/paycheck_void_conserves_payrun_totals
        """
        employer, w1, w2, run = self._setup_two_issued_paychecks(api)
        target = list_worker_paychecks(w1["id"])[0]
        void_paycheck(target["id"])

        w1_after = get_worker(w1["id"])
        assert w1_after["cash_wages_ytd_cents"] == 0

        accounts = get_tax_accounts_by_type(employer["id"], 2026)
        assert accounts["FUTA_ER"]["accrued_cents"] == 720
        assert accounts["SUTA_ER"]["accrued_cents"] == 2400

    def test_void_from_calculated_returns_invalid_state(self, api):
        """PRD §3.6: "A `PayrollAdmin` may void an `ISSUED` paycheck whose parent pay run is `FINALIZED`. (Voiding a `CALCULATED` paycheck is not supported — recalculate the run instead.)"

        Design: Corner/state_machines/paycheck_void_from_calculated_returns_invalid_state
        """
        employer, worker, _a = setup_active_worker(
            "AA", agreement_overrides={"guaranteed_minutes_per_week": 2400}
        )
        run = setup_calculated_pay_run(employer["id"])
        resp = api.list_pay_run_paychecks(run["id"], make_payroll_admin_headers())
        checks, _meta = validate_paginated(resp)
        assert checks[0]["status"] == "CALCULATED"
        resp = api.void_paycheck(checks[0]["id"], make_payroll_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
