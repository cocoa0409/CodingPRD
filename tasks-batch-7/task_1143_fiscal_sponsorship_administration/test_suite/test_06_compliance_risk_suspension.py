"""Compliance reviews, risk incidents, oversight posture gates, and the suspension
cascade (PRD §2.8, §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_active_bundle,
    create_findings_review,
    create_paid_disbursement,
    create_received_donation,
    create_submitted_disbursement,
    create_vetted_engagement,
    get_fund,
    get_project,
    incident_transition_payload,
    make_compliance_officer_headers,
    make_finance_officer_headers,
    make_project_lead_headers,
    make_sponsor_admin_headers,
    pledge_donation,
    remediate_payload,
    report_incident,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIncidentLifecycle:
    def test_incident_happy_path_then_terminal(self, api):
        """PRD §3.6: "`TRIAGE` moves `REPORTED` to `TRIAGED` (the score recomputes
        because open-set membership participates in the calculation), `MITIGATE` moves
        `TRIAGED` to `MITIGATING`, `RESOLVE` moves any of `REPORTED`, `TRIAGED`, or
        `MITIGATING` to `RESOLVED`, and `DISMISS` moves `REPORTED` or `TRIAGED` to
        `DISMISSED` — a mitigating incident cannot be dismissed, and any action from a
        state outside its from-set is rejected with `ERR_INCIDENT_STATE_INVALID`."

        Design: Corner/state_machines/sm_incident_happy_path_then_terminal
        """
        bundle = create_active_bundle("user_c_ri", project_name="RI", contact_email="ri@x.org")
        pid = bundle["project_id"]
        incident = report_incident(pid, severity="LOW", category="SAFETY",
                                   description="slip hazard")
        co = make_compliance_officer_headers()

        s1 = validate_success(api.transition_risk_incident(
            incident["id"], incident_transition_payload(action="TRIAGE"), co))
        assert s1["status"] == "TRIAGED"
        s2 = validate_success(api.transition_risk_incident(
            incident["id"], incident_transition_payload(action="MITIGATE"), co))
        assert s2["status"] == "MITIGATING"
        s3 = validate_success(api.transition_risk_incident(
            incident["id"], incident_transition_payload(action="RESOLVE", note="fixed"), co))
        assert s3["status"] == "RESOLVED"

        resp = api.transition_risk_incident(
            incident["id"], incident_transition_payload(action="TRIAGE"), co)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_STATE_INVALID)


class TestRemediationBounds:
    def test_remediation_overcount_rejected(self, api):
        """PRD §3.6: "each call supplies a `remediated_count` of at least one and at
        most the current `open_findings_count`, else `ERR_REMEDIATION_EXCEEDS_OPEN`.
        When the count leaves findings open, the review stays `FINDINGS_ISSUED` with
        `open_findings_count` reduced by that count; when the count exactly exhausts
        the open findings, `open_findings_count` becomes zero and the review moves to
        `REMEDIATED`."

        Design: Corner/validations/v_remediation_overcount_rejected
        """
        bundle = create_active_bundle("user_c_v5", project_name="RM", contact_email="rm@x.org")
        review = create_findings_review(bundle["project_id"], 2, "MEDIUM",
                                        review_type="SCHEDULED")
        co = make_compliance_officer_headers()
        resp = api.remediate_review(review["id"], remediate_payload(remediated_count=3), co)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_EXCEEDS_OPEN)

        done = validate_success(api.remediate_review(
            review["id"], remediate_payload(remediated_count=2), co))
        assert done["status"] == "REMEDIATED"
        assert done["open_findings_count"] == 0


class TestRiskPostureBandsAndGates:
    def test_risk_score_band_boundaries_and_gates(self, api):
        """PRD §2.8: "The score is the sum of severity weights over open incidents — 40
        for `CRITICAL`, 20 for `HIGH`, 8 for `MEDIUM`, 3 for `LOW` — plus five points
        per open finding"
        PRD §2.8: "The posture bands are inclusive at their lower edge: a score of
        exactly 50 or more is `SEVERE`, exactly 25 up to 49 is `RESTRICTED`, and below
        25 is `NORMAL`."
        PRD §2.8: "`RESTRICTED` blocks two operations: activating a staff engagement,
        and beginning exit due diligence. `SEVERE` blocks those same two and
        additionally blocks receiving a donation and submitting a disbursement. All
        four rejections carry `ERR_SEVERE_POSTURE_BLOCKS_SPEND` (HTTP 422)."
        HIGH (20) -> NORMAL; +1 open finding -> 25 -> RESTRICTED blocks activate;
        +CRITICAL (40) -> 65 -> SEVERE blocks receive.

        Design: Corner/calculations/c_risk_score_band_boundaries_and_gates
        """
        bundle = create_active_bundle("user_c_f5", project_name="F5", contact_email="f5@x.org")
        pid = bundle["project_id"]
        engagement = create_vetted_engagement(pid, "wf5@x.org", rate_cents=1000)
        donation = pledge_donation(pid, 10000)

        report_incident(pid, severity="HIGH", category="FINANCIAL",
                        description="cash handling")
        project = get_project(pid)
        assert project["risk_score"] == 20
        assert project["oversight_posture"] == "NORMAL"

        create_findings_review(pid, 1, "LOW")
        project = get_project(pid)
        assert project["risk_score"] == 25, "20 + 5 per open finding"
        assert project["oversight_posture"] == "RESTRICTED", "25 hits the inclusive band edge"

        resp = api.activate_engagement(engagement["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_SEVERE_POSTURE_BLOCKS_SPEND)

        report_incident(pid, severity="CRITICAL", category="REGULATORY",
                        description="irs notice")
        project = get_project(pid)
        assert project["risk_score"] == 65
        assert project["oversight_posture"] == "SEVERE"

        resp = api.receive_donation(donation["id"], make_finance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_SEVERE_POSTURE_BLOCKS_SPEND)
        after = validate_success(api.get_donation(donation["id"], make_finance_officer_headers()))
        assert after["status"] == "PLEDGED"


class TestSuspensionCascade:
    def test_suspend_conditional_cascade_skips_terminal(self, api):
        """PRD §3.4: "whenever the project is suspended — manually or via the
        escalation cascade of §3.6 — every request in `SUBMITTED`, `PENDING_SPONSOR`,
        or `APPROVED_FOR_PAYMENT` is auto-rejected with `auto_reject_reason` set to
        `SUSPENSION` and its commitment released, after which the fund's available
        balance is recomputed."
        A PAID (terminal) sibling is untouched: available ends at 460,000 - 30,000
        disbursed + 20,000 released = 430,000.

        Design: Corner/state_machines/sm_suspend_conditional_cascade_skips_terminal
        """
        bundle = create_active_bundle("user_c_sc", project_name="SC", contact_email="sc@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 500000)
        paid = create_paid_disbursement(pid, 30000, purpose="one", payee_name="A",
                                        spend_date="2026-06-01")
        submitted = create_submitted_disbursement(pid, 20000, purpose="two", payee_name="B",
                                                  spend_date="2026-06-02")

        validate_success(api.suspend_project(pid, {"reason": "hold"},
                                             make_sponsor_admin_headers()))

        after_paid = validate_success(api.get_disbursement(paid["id"], make_sponsor_admin_headers()))
        assert after_paid["status"] == "PAID", "terminal requests are skipped by the cascade"
        after_sub = validate_success(api.get_disbursement(submitted["id"], make_sponsor_admin_headers()))
        assert after_sub["status"] == "REJECTED"
        assert after_sub["auto_reject_reason"] == "SUSPENSION"
        fund = get_fund(bundle["fund_account_id"])
        assert fund["committed_cents"] == 0
        assert fund["available_cents"] == 430000

    def test_escalate_suspends_project_and_freezes_fund(self, api):
        """PRD §3.6: "Escalation, by contrast, moves a `FINDINGS_ISSUED` review to
        `ESCALATED`, which is terminal for the review, and fires the full suspension
        cascade: the project moves from `ACTIVE` to `SUSPENDED` with
        `suspension_reason` recorded as `ESCALATED_REVIEW`, the fund moves from
        `ACTIVE` to `FROZEN`, and every in-flight disbursement is auto-rejected with
        commitment release exactly as in §3.4."

        Design: Difficulty/transitive_cascade/escalate_suspends_project_rejects_inflight_releases_funds
        """
        bundle = create_active_bundle("user_app_j", project_name="Kappa", contact_email="k@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 300000)
        submitted = create_submitted_disbursement(pid, 50000, purpose="supplies",
                                                  payee_name="SupplyCo", spend_date="2026-06-05")
        review = create_findings_review(pid, 1, "MEDIUM")

        escalated = validate_success(api.escalate_review(
            review["id"], {"reason": "unremediated fraud risk"},
            make_compliance_officer_headers()))
        assert escalated["status"] == "ESCALATED"

        project = get_project(pid)
        assert project["status"] == "SUSPENDED"
        assert project["suspension_reason"] == "ESCALATED_REVIEW"
        fund = get_fund(bundle["fund_account_id"])
        assert fund["status"] == "FROZEN"
        after_sub = validate_success(api.get_disbursement(submitted["id"],
                                                          make_sponsor_admin_headers()))
        assert after_sub["status"] == "REJECTED"

    def test_escalate_releases_commitment_into_fund_totals(self, api):
        """PRD §3.6: "every in-flight disbursement is auto-rejected with commitment
        release exactly as in §3.4"
        PRD §3.4: "The commitment is released on every exit from the pipeline other
        than payment: compliance return, rejection at either gate, cancellation from
        `SUBMITTED`, and the suspension cascade all subtract the amount from
        `committed_cents`, post a `COMMITMENT_RELEASE` entry, and release the tranche
        commitment when one was taken."
        Received 300,000 (fee 24,000); committed 50,000 released on escalate ->
        committed 0, available back to 276,000.

        Design: Difficulty/transitive_cascade/escalate_suspends_project_rejects_inflight_releases_funds
        """
        bundle = create_active_bundle("user_app_j2", project_name="Kappa2",
                                      contact_email="k2@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 300000)
        submitted = create_submitted_disbursement(pid, 50000, purpose="supplies",
                                                  payee_name="SupplyCo", spend_date="2026-06-05")
        review = create_findings_review(pid, 1, "MEDIUM")

        validate_success(api.escalate_review(
            review["id"], {"reason": "unremediated fraud risk"},
            make_compliance_officer_headers()))

        after_sub = validate_success(api.get_disbursement(submitted["id"],
                                                          make_sponsor_admin_headers()))
        assert after_sub["status"] == "REJECTED"
        assert after_sub["auto_reject_reason"] == "SUSPENSION"

        fund = get_fund(bundle["fund_account_id"])
        assert fund["committed_cents"] == 0
        assert fund["available_cents"] == 276000

        entries, _ = validate_paginated(api.list_ledger_entries(
            make_compliance_officer_headers(),
            params={"disbursement_id": submitted["id"], "entry_type": "COMMITMENT_RELEASE"}))
        assert len(entries) == 1, "the auto-reject posts a COMMITMENT_RELEASE entry"
