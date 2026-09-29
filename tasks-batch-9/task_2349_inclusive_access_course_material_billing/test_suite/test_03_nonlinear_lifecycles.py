"""Lifecycles that loop and lifecycles that branch: the bounded opt-out cycle,
and the detour through DISPUTED that changes which money gets settled.
"""

from test_helpers import (
    AcademicTermStatus,
    AccessStatus,
    BillingStatus,
    ComplianceStatus,
    DisclosureReportStatus,
    OptOutRequestStatus,
    ReconciliationRunStatus,
    ReconciliationStatus,
    SectionIaStatus,
    ApiErrorId,
    assert_money,
    assert_ratio,
    fixtures,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOptOutCycleTermination:
    """Two complete grant/rescind/re-file cycles, then a hard stop."""

    @staticmethod
    def _two_completed_cycles(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        charge_id = scenario["charge_ids"][0]
        student_id = scenario["student_ids"][0]

        fixtures.set_clock(api, "2026-08-25T10:00:00Z")
        request = fixtures.file_opt_out(api, charge_id, student_id, "OWNS_COPY")

        # Cycle one.
        fixtures.set_clock(api, "2026-08-26T10:00:00Z")
        fixtures.grant_opt_out(api, request["id"])
        fixtures.set_clock(api, "2026-08-27T10:00:00Z")
        fixtures.rescind_opt_out(api, request["id"], student_id)
        fixtures.set_clock(api, "2026-08-28T10:00:00Z")
        fixtures.resubmit_opt_out(api, request["id"], student_id, "ALTERNATE_SOURCE")

        # Cycle two.
        fixtures.set_clock(api, "2026-08-29T10:00:00Z")
        fixtures.grant_opt_out(api, request["id"])
        fixtures.set_clock(api, "2026-08-30T10:00:00Z")
        fixtures.rescind_opt_out(api, request["id"], student_id)
        fixtures.set_clock(api, "2026-08-31T10:00:00Z")
        fixtures.resubmit_opt_out(api, request["id"], student_id, "OWNS_COPY")

        # A third grant and rescind are still legal; only the re-file is capped.
        fixtures.set_clock(api, "2026-09-01T10:00:00Z")
        fixtures.grant_opt_out(api, request["id"])
        fixtures.set_clock(api, "2026-09-02T10:00:00Z")
        fixtures.rescind_opt_out(api, request["id"], student_id)
        fixtures.set_clock(api, "2026-09-03T10:00:00Z")

        scenario["request_id"] = request["id"]
        return scenario

    def test_third_reentry_into_submitted_is_refused_at_the_cycle_limit(self, api):
        """PRD §3.6: "The full cycle `SUBMITTED` → `GRANTED` → `RESCINDED` →
        `SUBMITTED` may therefore run at most twice, and a third attempt is
        rejected with `ERR_OPT_OUT_CYCLE_LIMIT`."

        Design: Difficulty/non_linear_state_machine/nonlinear_opt_out_cycle_terminates_at_max_opt_out_cycles
        """
        scenario = self._two_completed_cycles(api)

        # 2026-09-03T10:00:00Z is still inside the 2026-09-04T23:59:59.999Z window,
        # so the cycle limit — not the window — must be what refuses this re-file.
        response = api.resubmit_opt_out_request(
            scenario["request_id"], {"reason_code": "OWNS_COPY"},
            make_student_headers(scenario["student_ids"][0]),
        )
        validate_error(response, ApiErrorId.OPT_OUT_CYCLE_LIMIT.value)

        request = fixtures.read_opt_out(api, scenario["request_id"])
        assert request["status"] == OptOutRequestStatus.RESCINDED.value
        assert request["cycle_count"] == 2

    def test_both_charge_dimensions_return_to_their_pre_cycle_values(self, api,
                                                                    bursar_officer,
                                                                    registrar):
        """PRD §3.6: "Both conserved quantities of §2.7 are back at their pre-grant
        values when this completes, with exactly two extra ledger rows on the
        charge."

        Design: Difficulty/non_linear_state_machine/nonlinear_opt_out_cycle_terminates_at_max_opt_out_cycles
        """
        scenario = self._two_completed_cycles(api)
        charge_id = scenario["charge_ids"][0]

        charge = validate_success(api.get_charge(charge_id, bursar_officer))
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert_money(charge["net_billed_cents"], 9450)
        assert charge["access_status"] == AccessStatus.RESTORED.value
        assert_money(charge["refunded_amount_cents"], 0)

        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(charge_id, bursar_officer)
        )
        # One INITIAL_POST, three OPT_OUT_REFUND, three OPT_IN_RECHARGE.
        assert meta["total_count"] == 7
        assert_money(sum(entry["amount_cents"] for entry in entries), 9450)

        student = validate_success(
            api.get_student(scenario["student_ids"][0], registrar)
        )
        assert_money(student["bursar_balance_cents"], 9450)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["provisioned_access_count"] == 2
        assert section["revoked_access_count"] == 0
        assert_ratio(section["participation_rate"], 1.0000)
        # At the low point the rate was exactly 0.5000, which stays BILLED.
        assert section["ia_status"] == SectionIaStatus.BILLED.value


class TestDisputedSettlementBranch:
    """COMPUTED cannot reach SETTLED over tolerance; it must detour via DISPUTED."""

    @staticmethod
    def _locked_term_with_an_over_tolerance_run(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        report = fixtures.create_disclosure_report(api, scenario["term_id"], "CA")

        fixtures.set_clock(api, "2026-12-15T09:00:00Z")
        fixtures.lock_term_billing(api, scenario["term_id"])
        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"], agreement["version"],
            publisher_reported_count=2, publisher_reported_amount_cents=17500,
        )
        scenario["report_id"] = report["id"]
        scenario["run_id"] = run["id"]
        scenario["run"] = run
        return scenario

    def test_direct_settle_is_refused_when_variance_exceeds_tolerance(self, api,
                                                                     program_admin):
        """PRD §3.8: "It requires the run to be `COMPUTED`, the agreement's
        `reconciliation_status` to be `COMPUTED`, and the absolute value of
        `variance_cents` to be at most five dollars — 500 cents — with a larger
        variance rejected as `ERR_VARIANCE_TOLERANCE_EXCEEDED` and required to be
        disputed first."

        Design: Difficulty/non_linear_state_machine/nonlinear_disputed_branch_join_writes_publisher_figure_on_settle
        """
        scenario = self._locked_term_with_an_over_tolerance_run(api)
        run = scenario["run"]

        assert_money(run["gross_invoice_cents"], 16632)
        assert_money(run["rebate_cents"], 499)
        assert_money(run["settlement_amount_cents"], 16133)
        assert_money(run["variance_cents"], 1367)

        response = api.settle_reconciliation_run(scenario["run_id"], program_admin)
        validate_error(response, ApiErrorId.VARIANCE_TOLERANCE_EXCEEDED.value)

        unchanged = fixtures.read_run(api, scenario["run_id"])
        assert unchanged["status"] == ReconciliationRunStatus.COMPUTED.value

    def test_conceded_branch_writes_the_publisher_figure_and_closes_the_term(
            self, api, program_admin, compliance_officer):
        """PRD §3.8: "Its first hop moves the agreement's `reconciliation_status`
        to `SETTLED` but writes the agreement's `settled_amount_cents` as the
        run's `publisher_reported_amount_cents` — the publisher's figure is
        conceded."

        Design: Difficulty/non_linear_state_machine/nonlinear_disputed_branch_join_writes_publisher_figure_on_settle
        """
        scenario = self._locked_term_with_an_over_tolerance_run(api)

        disputed = validate_success(
            api.dispute_reconciliation_run(
                scenario["run_id"],
                {"dispute_note": "Publisher counted a section we never flagged."},
                program_admin,
            )
        )
        assert disputed["status"] == ReconciliationRunStatus.DISPUTED.value
        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.DISPUTED.value

        # A DISPUTED agreement still counts as a current reconciliation.
        certified = validate_success(
            api.certify_disclosure_report(scenario["report_id"], compliance_officer)
        )
        assert certified["status"] == DisclosureReportStatus.CERTIFIED.value
        assert_money(certified["total_list_price_cents"], 36000)
        assert_money(certified["total_net_billed_cents"], 18900)
        assert_money(certified["average_net_cost_cents"], 9450)
        assert_ratio(certified["savings_pct"], 0.4750)
        assert certified["compliance_status"] == ComplianceStatus.COMPLIANT.value

        settled = validate_success(
            api.settle_reconciliation_run(scenario["run_id"], program_admin)
        )
        assert settled["status"] == ReconciliationRunStatus.SETTLED.value

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        # The publisher's 17500, not the campus computation of 16133.
        assert_money(agreement["settled_amount_cents"], 17500)
        assert agreement["reconciliation_status"] == ReconciliationStatus.SETTLED.value

        term = fixtures.read_term(api, scenario["term_id"])
        assert term["status"] == AcademicTermStatus.CLOSED.value

        report = fixtures.read_report(api, scenario["report_id"])
        assert report["status"] == DisclosureReportStatus.PUBLISHED.value
        assert report["published_at"] == "2026-12-15T09:00:00.000Z"
