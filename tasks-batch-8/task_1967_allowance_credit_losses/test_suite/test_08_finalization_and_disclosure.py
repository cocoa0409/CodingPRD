"""Finalization, disclosure roll-forward, and the audit cycle (PRD §3.7–§3.8)."""
from test_helpers import (
    ApiErrorId,
    adverse_scenario_payload,
    approve_run,
    assert_disclosure_report,
    assert_rollforward_identity,
    create_approved_factor,
    create_draft_run,
    create_loan_payload,
    create_segment,
    execute_run,
    finalize_payload,
    finalize_run,
    get_run_disclosure_report,
    propose_adjustment,
    reject_adjustment,
    setup_approved_run,
    setup_executed_run,
    setup_finalized_run,
    setup_run_environment,
    submit_run_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)

FACTOR_DOC = (
    "Q2 uncertainty overlay for energy concentration, approved by credit "
    "committee memo Q2-2026-11."
)


class TestFinalizeGates:
    def test_finalize_twice_rejected_terminal_lockdown(self, api, chief_credit_officer_headers):
        """PRD §3.8: "Finalization moves the run `APPROVED` → `FINALIZED`, increments its `version`, and spawns the run's disclosure report — exactly one report per run, created in `PREPARED` and linked through its `run_id`."
        PRD §2.9: "State-transition legality: the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any transition attempted from a state other than its declared source state fails here."

        Design: Corner/state_machines/finalize_twice_rejected_terminal_lockdown
        """
        env = setup_finalized_run()
        res = api.finalize_model_run(env.run["id"], finalize_payload(),
                                     chief_credit_officer_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        rows, meta = validate_paginated(
            api.list_disclosure_reports(env.run["id"], chief_credit_officer_headers)
        )
        assert len(rows) == 1, "no second disclosure report may be created"
        assert meta["total_count"] == 1

    def test_finalize_with_pending_adjustment_rejected(self, api, chief_credit_officer_headers):
        """PRD §3.8: "Finalization seals the quarter. A `ChiefCreditOfficer` finalizes an `APPROVED` run, but only when no adjustment of the run remains `PENDING` — a lingering proposal blocks the transition with `ERR_ADJUSTMENTS_PENDING` (HTTP 409), which is what the widened rejection gate of §3.7 exists to clear."
        PRD §3.7: "Rejection moves an adjustment `PENDING` → `REJECTED` and never touches the run's totals; precisely because it is fiscally inert, rejection remains available even after the run has reached `APPROVED` — where the parent-run gate widens to `EXECUTED`, `UNDER_REVIEW`, or `APPROVED` — so that a stale pending proposal can always be cleared out of the way of finalization."

        Design: Corner/validations/finalize_with_pending_adjustment_rejected
        """
        env = setup_executed_run(executor_user_id="analyst-1")
        adjustment = propose_adjustment(
            env.run["id"], 20, env.run["version"], user_id="analyst-1",
            rationale="Small overlay",
        )
        submit_run_for_review(env.run["id"], user_id="analyst-1")
        approve_run(env.run["id"], user_id="cco-1")

        blocked = api.finalize_model_run(env.run["id"], finalize_payload(),
                                         chief_credit_officer_headers)
        validate_error(blocked, ApiErrorId.ERR_ADJUSTMENTS_PENDING, 409)

        rejected = reject_adjustment(adjustment["id"], user_id="cco-1")
        assert rejected["status"] == "REJECTED"

        finalized = validate_success(
            api.finalize_model_run(env.run["id"], finalize_payload(),
                                   chief_credit_officer_headers), 200
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["management_adjustment_cents"] == 0, (
            "a rejected adjustment contributes nothing to run totals"
        )


class TestRollForward:
    def test_rollforward_provision_and_beginning_selector(self, api):
        """PRD §3.8: "Its `ending_allowance_cents` is the run's `total_allowance_cents` at finalization. Its `beginning_allowance_cents` is selected from settled history: among all `FINALIZED` runs whose `as_of_period` quarter index is strictly below the finalizing run's, the one with the greatest quarter index supplies its `total_allowance_cents`; when no such run exists — the first quarter ever finalized — the beginning allowance is zero. The `provision_cents` is then the ending allowance minus the beginning allowance plus the period's gross charge-offs minus the period's recoveries: the provision is whatever the income statement must absorb so that, after charge-offs and recoveries flow through, the allowance lands on the new estimate."

        Design: Corner/calculations/rollforward_provision_and_beginning_selector
        """
        # Run1: 60/40 weighted on 10000000 PRIME -> allowance 55000, finalized 0/0.
        env1 = setup_finalized_run(
            loan_specs=[{"amortized_cost_cents": 10_000_000, "risk_rating": "PASS"}],
            scenario_specs=[{}, adverse_scenario_payload()],
            weights_bps=[6_000, 4_000],
        )
        report1 = get_run_disclosure_report(env1.run["id"])
        assert_disclosure_report(report1)
        assert report1["beginning_allowance_cents"] == 0
        assert report1["ending_allowance_cents"] == 55_000
        assert report1["provision_cents"] == 55_000
        assert_rollforward_identity(report1)

        # +25 bps APPROVED factor covering only 2026-Q2.
        create_approved_factor(
            env1.segments[0]["id"], factor_code="ECONOMIC_UNCERTAINTY",
            adjustment_bps=25, effective_from_period="2026-Q2",
            effective_to_period="2026-Q2", documentation_text=FACTOR_DOC,
        )

        run_2 = create_draft_run(
            env1.model["id"],
            [{"scenario_id": env1.scenarios[0]["id"], "weight_bps": 6_000},
             {"scenario_id": env1.scenarios[1]["id"], "weight_bps": 4_000}],
            as_of_period="2026-Q2",
        )
        execute_run(run_2["id"], user_id="analyst-1")
        submit_run_for_review(run_2["id"], user_id="analyst-1")
        approve_run(run_2["id"], user_id="cco-1")
        finalize_run(run_2["id"], period_charge_offs_cents=30_000,
                     period_recoveries_cents=5_000)

        report2 = get_run_disclosure_report(run_2["id"])
        assert report2["beginning_allowance_cents"] == 55_000  # run1's total
        assert report2["ending_allowance_cents"] == 80_000     # 55000 + 25000
        assert report2["provision_cents"] == 50_000            # 80000 - 55000 + 30000 - 5000
        assert_rollforward_identity(report2)


class TestAuditCycle:
    def test_disclosure_signoff_from_prepared_rejected(self, api, external_auditor_headers):
        """PRD §3.8: "The audit cycle belongs to the report's own lifecycle. A `CreditAnalyst` submits a `PREPARED` report, moving it `PREPARED` → `UNDER_AUDIT_REVIEW`. An `ExternalAuditor` then either signs it off or sends it back."
        PRD §2.9: "State-transition legality: the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any transition attempted from a state other than its declared source state fails here."

        Design: Corner/state_machines/disclosure_signoff_from_prepared_rejected
        """
        env = setup_finalized_run()
        report = env.report
        assert report["status"] == "PREPARED"
        res = api.sign_off_disclosure_report(
            report["id"], {"audit_reference": "AUD-2026-001"}, external_auditor_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        reread = validate_success(
            api.get_disclosure_report(report["id"], external_auditor_headers), 200
        )
        assert reread["status"] == "PREPARED"

    def test_disclosure_signoff_forbidden_for_analyst_allowed_for_auditor(
        self, api, credit_analyst_headers, external_auditor_headers
    ):
        """PRD §3.8: "Sign-off requires a non-empty `audit_reference` — the auditor's workpaper pointer — and an empty one is rejected with `ERR_INVALID_REQUEST`; an accepted sign-off stores the reference and moves the report `UNDER_AUDIT_REVIEW` → `RELEASED`, which is terminal."
        PRD §2.1: "A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/disclosure_signoff_forbidden_for_analyst_allowed_for_auditor
        """
        env = setup_finalized_run()
        report = env.report
        submitted = validate_success(
            api.submit_disclosure_for_audit(report["id"], credit_analyst_headers), 200
        )
        assert submitted["status"] == "UNDER_AUDIT_REVIEW"

        forbidden = api.sign_off_disclosure_report(
            report["id"], {"audit_reference": "AUD-2026-001"}, credit_analyst_headers
        )
        validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

        released = validate_success(api.sign_off_disclosure_report(
            report["id"], {"audit_reference": "AUD-2026-001"}, external_auditor_headers
        ), 200)
        assert released["status"] == "RELEASED"
        assert released["audit_reference"] == "AUD-2026-001"


class TestReverseReachability:
    def test_reverse_reachability_lists(self, api, credit_analyst_headers):
        """PRD §3.2: "The loans booked into a segment, and the qualitative factors attached to it, are each reachable as lists hanging off the segment."
        PRD §3.7: "A run's adjustments can be listed with a `status` filter."
        PRD §3.8: "A run's reports can be listed to retrieve the zero-or-one report it owns."

        Design: Corner/endpoints/reverse_reachability_lists
        """
        env = setup_executed_run()
        segment = env.segments[0]
        loan = env.loans[0]
        adjustment = propose_adjustment(env.run["id"], 20, env.run["version"],
                                        rationale="Small overlay")

        loans, _ = validate_paginated(
            api.list_segment_loans(segment["id"], credit_analyst_headers)
        )
        assert [row["id"] for row in loans] == [loan["id"]]

        adjustments, _ = validate_paginated(
            api.list_management_adjustments(env.run["id"], credit_analyst_headers)
        )
        assert [row["id"] for row in adjustments] == [adjustment["id"]]
        assert adjustments[0]["status"] == "PENDING"

        reports, _ = validate_paginated(
            api.list_disclosure_reports(env.run["id"], credit_analyst_headers)
        )
        assert reports == [], "a report exists only after finalization"
