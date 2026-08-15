"""Volume audits: the appeal/reopen cycle, the provisional-vs-final dual
variant of tier resolution, and the retroactive adjudication cascade.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    bootstrap_coop,
    create_active_member,
    create_onboarded_supplier,
    create_open_program,
    enroll_member,
    setup_member_with_open_program,
    setup_finalized_accrual_scenario,
    submit_report,
    get_accrual_for_enrollment,
    open_audit_on_report,
    drive_audit_to_accepted,
    open_accepted_audit,
    resolve_audit,
    current_quarter,
    make_member_rep_headers,
    TIER_SCHEDULE_T1,
)


class TestAppealReopenCycle:
    def test_appeal_reopen_cycle_can_traverse_twice(self, api, auditor_headers):
        """PRD §3.5: "An appealed audit is sent back to the field: the
        auditor reopens fieldwork, cycling the audit from `APPEALED` back to
        `FIELDWORK` for another pass through findings. This cycle may repeat
        as often as the parties require."

        Two full FINDINGS_ISSUED -> APPEALED -> FIELDWORK -> FINDINGS_ISSUED
        loops leave the audit in APPEALED, with one version increment per
        transition (PRD §2.4).

        Design: Difficulty/non_linear_state_machine/volume_audit_appeal_reopen_cycle
        """
        scenario = setup_member_with_open_program(
            program_code="P-CYC", tier_schedule=[{"min_qty": 0, "rate_bps": 200}]
        )
        report = submit_report(scenario["enrollment"], scenario["member"], 0, 50, 50000)
        audit = open_audit_on_report(report)
        v0 = audit["version"]
        member_headers = make_member_rep_headers(scenario["member"]["id"])

        get_success_data(api.begin_fieldwork(audit["id"], auditor_headers))
        get_success_data(api.issue_findings(audit["id"], auditor_headers))
        # Loop 1: appeal -> reopen -> issue
        appealed1 = validate_success(api.appeal_audit(audit["id"], member_headers), 200)
        assert appealed1["status"] == "APPEALED"
        reopened = validate_success(api.reopen_fieldwork(audit["id"], auditor_headers), 200)
        assert reopened["status"] == "FIELDWORK"
        get_success_data(api.issue_findings(audit["id"], auditor_headers))
        # Loop 2: appeal again
        appealed2 = validate_success(api.appeal_audit(audit["id"], member_headers), 200)
        assert appealed2["status"] == "APPEALED"
        # create -> begin -> issue -> appeal -> reopen -> issue -> appeal = 6 mutations
        assert appealed2["version"] == v0 + 6, (
            f"one version increment per transition: expected {v0 + 6}, got "
            f"{appealed2['version']}"
        )

    def test_audit_completes_to_resolved_after_appeal_cycle(
        self, api, auditor_headers
    ):
        """PRD §3.5: "At `FINDINGS_ISSUED` the member chooses: its own
        `MemberRep` may accept the findings, moving the audit to `ACCEPTED`,
        or appeal them, moving it to `APPEALED`".
        PRD §3.5: "The auditor resolves an `ACCEPTED` audit — any other
        source state fails with `ERR_INVALID_STATE` — by attesting the final
        figures in the payload".

        After one appeal/reopen cycle the audit can still be driven to the
        terminal RESOLVED state, proving the cycle does not corrupt the
        machine.

        Design: Difficulty/non_linear_state_machine/volume_audit_appeal_reopen_cycle
        """
        scenario = setup_member_with_open_program(
            program_code="P-CYC2", tier_schedule=[{"min_qty": 0, "rate_bps": 200}]
        )
        report = submit_report(scenario["enrollment"], scenario["member"], 0, 50, 50000)
        audit = open_audit_on_report(report)
        member_headers = make_member_rep_headers(scenario["member"]["id"])

        get_success_data(api.begin_fieldwork(audit["id"], auditor_headers))
        get_success_data(api.issue_findings(audit["id"], auditor_headers))
        get_success_data(api.appeal_audit(audit["id"], member_headers))
        get_success_data(api.reopen_fieldwork(audit["id"], auditor_headers))
        get_success_data(api.issue_findings(audit["id"], auditor_headers))
        accepted = validate_success(api.accept_findings(audit["id"], member_headers), 200)
        assert accepted["status"] == "ACCEPTED"
        resolved = resolve_audit(accepted, audited_qty=50, audited_cents=50000)
        assert resolved["status"] == "RESOLVED"
        # audited == self-reported -> severity NONE per PRD §3.5:
        # "When `audited_cents` equals the report's `self_report_cents`
        # exactly, the severity is `NONE`."
        assert resolved["finding_severity"] == "NONE"


class TestProvisionalVsFinalDualVariant:
    def _scenario_with_accepted_audit(self):
        scenario = setup_member_with_open_program(
            program_code="PROG-1", tier_schedule=TIER_SCHEDULE_T1
        )
        report = submit_report(scenario["enrollment"], scenario["member"], 0, 120, 200000)
        audit = open_accepted_audit(report, scenario["member"])
        scenario["report"] = report
        scenario["audit"] = audit
        return scenario

    def test_final_variant_diverges_from_provisional_on_audit(
        self, api, auditor_headers
    ):
        """PRD §3.4: "The system finds or creates the `RebateAccrual` for
        that enrollment and quarter — the accrual starts in `OPEN` status
        with all computed amounts at 0 — and computes
        `provisional_rebate_cents` from the self-reported figures".
        PRD §3.5: "the rebate accrual for that enrollment and quarter is
        recomputed under the final variant of tier resolution — the eligible
        quantity and cents are now the audited values rather than the
        self-reported ones, and the result replaces `final_rebate_cents`."

        Self-report 120 qty / 200000 cents over tiers
        [{0,200},{100,500},{500,800}] gives provisional
        floor(200000*500/10000) = 10000; audited 80 qty / 150000 cents falls
        to the {0,200} tier, giving final floor(150000*200/10000) = 3000.

        Design: Difficulty/dual_variant_calc/accrual_provisional_vs_final_diverge_on_audit
        """
        scenario = self._scenario_with_accepted_audit()
        accrual_before = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual_before["provisional_rebate_cents"] == 10000
        assert accrual_before["tier_applied_min_qty"] == 100

        resolve_audit(scenario["audit"], audited_qty=80, audited_cents=150000)

        accrual_after = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual_after["provisional_rebate_cents"] == 10000, (
            "the provisional amount is computed at submission and is not "
            "rewritten by the audit"
        )
        assert accrual_after["final_rebate_cents"] == 3000, (
            f"final variant uses audited figures: expected 3000, got "
            f"{accrual_after['final_rebate_cents']}"
        )
        assert (
            accrual_after["provisional_rebate_cents"]
            != accrual_after["final_rebate_cents"]
        )

    def test_audit_resolve_adjudicates_report_and_marks_material(
        self, api, auditor_headers, admin_headers
    ):
        """PRD §3.5: "When the figures differ, the absolute difference
        divided by `self_report_cents` yields a discrepancy ratio: a ratio
        strictly greater than zero and at most five hundredths — five
        percent — is `MINOR`, and anything beyond that band is `MATERIAL`."
        PRD §3.5: "the audited purchase report transitions from `SUBMITTED`
        to `ADJUDICATED`, its `audited_qty` and `audited_cents` populated
        from the attestation and its `version` incremented."
        PRD §3.5: "when the finding is `MATERIAL`, the member's
        `prior_audit_findings_count` increments by one".

        |150000 - 200000| / 200000 = 0.25 > 0.05 -> MATERIAL.

        Design: Difficulty/dual_variant_calc/accrual_provisional_vs_final_diverge_on_audit
        """
        scenario = self._scenario_with_accepted_audit()
        resolved = resolve_audit(scenario["audit"], audited_qty=80, audited_cents=150000)
        assert resolved["status"] == "RESOLVED"
        assert resolved["finding_severity"] == "MATERIAL"
        assert resolved["resolved_quarter_index"] == 0

        report_after = get_success_data(
            api.get_purchase_report(scenario["report"]["id"], auditor_headers)
        )
        assert report_after["status"] == "ADJUDICATED"
        assert report_after["audited_qty"] == 80
        assert report_after["audited_cents"] == 150000

        member_after = get_success_data(
            api.get_member(scenario["member"]["id"], admin_headers)
        )
        assert member_after["prior_audit_findings_count"] == 1


class TestAuditResolveCascade:
    def _finalized_scenario_with_accepted_audit(self):
        """Report in quarter 0, distribution drafted for quarter 0, quarter
        closed so the accrual is FINALIZED, then an audit opened and driven
        to ACCEPTED. No disbursement — the accrual is FINALIZED at resolve
        time."""
        scenario = setup_finalized_accrual_scenario(
            qty=120,
            cents=200000,
            tier_schedule=[{"min_qty": 0, "rate_bps": 200}, {"min_qty": 100, "rate_bps": 500}],
            program_code="P-CAS1",
        )
        audit = open_accepted_audit(scenario["report"], scenario["member"])
        scenario["audit"] = audit
        return scenario

    def test_resolve_recomputes_final_and_reopens_finalized_accrual(
        self, api, auditor_headers
    ):
        """PRD §3.5: "If the recomputed final amount differs from the
        accrual's prior final amount and the accrual had already been
        `FINALIZED`, the accrual is pulled back from `FINALIZED` to `OPEN` —
        with its `version` incremented — so that the next quarter close
        re-finalizes it on the corrected evidence."
        PRD §3.5: "the audited purchase report transitions from `SUBMITTED`
        to `ADJUDICATED`, its `audited_qty` and `audited_cents` populated
        from the attestation and its `version` incremented."

        Hop 1: report SUBMITTED -> ADJUDICATED with audited fields. Hop 2:
        final_rebate_cents recomputed to floor(100000*200/10000) = 2000
        (audited qty 50 selects the {0,200} tier). Hop 3: the FINALIZED
        accrual is pulled back to OPEN.

        Design: Difficulty/transitive_cascade/audit_resolve_cascades_to_redistribution
        """
        scenario = self._finalized_scenario_with_accepted_audit()
        accrual_before = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual_before["status"] == "FINALIZED"
        assert accrual_before["final_rebate_cents"] == 10000

        resolved = resolve_audit(scenario["audit"], audited_qty=50, audited_cents=100000)
        assert resolved["status"] == "RESOLVED"

        report_after = get_success_data(
            api.get_purchase_report(scenario["report"]["id"], auditor_headers)
        )
        assert report_after["status"] == "ADJUDICATED"
        assert report_after["audited_qty"] == 50
        assert report_after["audited_cents"] == 100000

        accrual_after = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual_after["final_rebate_cents"] == 2000, (
            f"final recomputed from audited figures: expected 2000, got "
            f"{accrual_after['final_rebate_cents']}"
        )
        assert accrual_after["status"] == "OPEN", (
            "a FINALIZED accrual whose recomputed final differs is pulled "
            "back to OPEN"
        )
        assert accrual_after["version"] > accrual_before["version"]

    def test_resolve_material_increments_findings_and_stamps_resolution_quarter(
        self, api, auditor_headers, admin_headers
    ):
        """PRD §3.5: "Resolution stamps `resolved_quarter_index` with the
        current quarter and computes `finding_severity` from the gap between
        attestation and self-report."
        PRD §3.5: "when the finding is `MATERIAL`, the member's
        `prior_audit_findings_count` increments by one, which pushes future
        distribution holdbacks into the elevated band described in §3.6."

        |100000 - 200000| / 200000 = 0.5 > 0.05 -> MATERIAL; the resolve
        happens while the co-op sits in quarter 1 (after one close).

        Design: Difficulty/transitive_cascade/audit_resolve_cascades_to_redistribution
        """
        scenario = self._finalized_scenario_with_accepted_audit()
        assert current_quarter() == 1

        resolved = resolve_audit(scenario["audit"], audited_qty=50, audited_cents=100000)
        assert resolved["finding_severity"] == "MATERIAL"
        assert resolved["resolved_quarter_index"] == 1

        member_after = get_success_data(
            api.get_member(scenario["member"]["id"], admin_headers)
        )
        assert member_after["prior_audit_findings_count"] == 1

        accrual_after = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual_after["final_rebate_cents"] == 2000
