"""Suspension/resumption cycles and retirement with replacement (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_metric,
    assert_instant_equal,
    complete_engagement,
    create_approved_model,
    create_finding,
    create_model,
    create_model_with_approved_doc,
    create_draft_report,
    create_retired_pair,
    create_suspended_tier1_model,
    get_model,
    open_engagement,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]


def _complete_retest_engagement(model_id, period_start="2026-08-20T00:00:00Z",
                                period_end="2026-08-23T00:00:00Z", assessed="HIGH"):
    """Open and complete a retest engagement (completed_at = the current logical
    clock), satisfying the HIGH|CRITICAL close gate."""
    eng = open_engagement(model_id, period_start=period_start, period_end=period_end,
                          scope_outcomes_analysis=False)
    return complete_engagement(eng["id"], outcome="EFFECTIVE", assessed_complexity=assessed)


class TestSuspendResumeCycle:
    def test_clock_escalation_suspends_tier1_model_and_pauses_metric(self, api):
        """PRD §3.6: "Escalation can cascade: when the escalating finding has severity
        `HIGH` or `CRITICAL`, and its model is `TIER_1`, and the model is currently
        `APPROVED_FOR_USE`, the model is immediately suspended and every `ACTIVE`
        monitoring metric on it is paused, as detailed in §3.8."

        CRITICAL finding created at 2026-08-02 on an approved TIER_1 model: due
        2026-08-16, escalates once now > 2026-08-23; at the 2026-08-24 sweep the
        finding is ESCALATED, the model SUSPENDED, the metric PAUSED.

        Design: Difficulty/non_linear_state_machine/model_suspend_resume_cycle_restores_approved
        """
        scenario = create_suspended_tier1_model(severity="CRITICAL",
                                                finding_time="2026-08-02T00:00:00Z",
                                                sweep_to="2026-08-24T00:00:00Z",
                                                metric_names=("psi",))
        model = scenario["model"]
        assert model["status"] == "SUSPENDED"
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert findings[0]["status"] == "ESCALATED"
        metric = validate_success(api.get_metric(scenario["metrics"]["psi"]["id"], OWNER_A))
        assert metric["status"] == "PAUSED"

    def test_closing_escalated_finding_resumes_model_cycle(self, api):
        """PRD §3.8: "Immediately after any finding on a `SUSPENDED` model transitions
        to `CLOSED`, the auto-resume check runs: if no finding remains on the model
        with status `OPEN`, `OVERDUE`, or `ESCALATED` and severity `HIGH` or
        `CRITICAL`, the model returns to `APPROVED_FOR_USE` and every `PAUSED` metric
        returns to `ACTIVE`."

        The full cycle APPROVED_FOR_USE -> SUSPENDED -> APPROVED_FOR_USE: a retest
        engagement completed at 2026-08-24 (after the finding's 2026-08-02 created_at)
        satisfies the CRITICAL close gate, and closing restores model and metric.

        Design: Difficulty/non_linear_state_machine/model_suspend_resume_cycle_restores_approved
        """
        scenario = create_suspended_tier1_model(severity="CRITICAL",
                                                finding_time="2026-08-02T00:00:00Z",
                                                sweep_to="2026-08-24T00:00:00Z",
                                                metric_names=("psi",))
        model_id = scenario["model"]["id"]
        _complete_retest_engagement(model_id)
        closed = validate_success(
            api.close_finding(model_id, scenario["finding"]["id"], OFFICER)
        )
        assert closed["status"] == "CLOSED"
        assert get_model(model_id)["status"] == "APPROVED_FOR_USE", "auto-resume completed the cycle"
        metric = validate_success(api.get_metric(scenario["metrics"]["psi"]["id"], OWNER_A))
        assert metric["status"] == "ACTIVE"


class TestEscalationCascade:
    def test_high_escalation_suspends_tier1_model(self, api):
        """PRD §3.6: "Escalation can cascade: when the escalating finding has severity
        `HIGH` or `CRITICAL`, and its model is `TIER_1`, and the model is currently
        `APPROVED_FOR_USE`, the model is immediately suspended and every `ACTIVE`
        monitoring metric on it is paused, as detailed in §3.8."

        HIGH finding created at the 2026-08-01 default clock on a TIER_1 model: due
        2026-08-31 (30 days), escalates once now > 2026-09-07; the 2026-09-08 sweep
        suspends the model (hop 1: ESCALATED; hop 2: SUSPENDED).

        Design: Difficulty/transitive_cascade/clock_escalation_suspends_model_pauses_metrics
        """
        scenario = create_suspended_tier1_model(severity="HIGH",
                                                finding_time="2026-08-01T00:00:00Z",
                                                sweep_to="2026-09-08T00:00:00Z",
                                                metric_names=("psi", "auc"))
        findings, _ = validate_paginated(api.list_findings(scenario["model"]["id"], OFFICER))
        assert findings[0]["status"] == "ESCALATED", "hop 1: 2026-09-08 > due 2026-08-31 + 7d grace"
        assert scenario["model"]["status"] == "SUSPENDED", "hop 2: HIGH escalation on a TIER_1 model"

    def test_escalation_pauses_every_active_metric(self, api):
        """PRD §3.8: "Suspension pauses the model's monitoring: every `ACTIVE` metric
        transitions to `PAUSED`, and a paused metric admits no new readings."
        PRD §3.6: "When a sweep finds an `OVERDUE` finding whose deadline plus a grace
        of seven days is strictly in the past, the finding becomes `ESCALATED` and
        `escalated_at` is stamped".

        Hop 3 applies to every ACTIVE metric (psi and auc), and the escalation stamps
        escalated_at with the sweep's logical now.

        Design: Difficulty/transitive_cascade/clock_escalation_suspends_model_pauses_metrics
        """
        scenario = create_suspended_tier1_model(severity="HIGH",
                                                finding_time="2026-08-01T00:00:00Z",
                                                sweep_to="2026-09-08T00:00:00Z",
                                                metric_names=("psi", "auc"))
        for name in ("psi", "auc"):
            metric = validate_success(api.get_metric(scenario["metrics"][name]["id"], OWNER_A))
            assert metric["status"] == "PAUSED", f"metric {name} must be paused"
        findings, _ = validate_paginated(api.list_findings(scenario["model"]["id"], OFFICER))
        assert_instant_equal(findings[0]["escalated_at"], "2026-09-08T00:00:00Z", "escalated_at")

    def test_escalated_high_finding_on_tier2_does_not_suspend(self, api):
        """PRD §3.6: "Escalation can cascade: when the escalating finding has severity
        `HIGH` or `CRITICAL`, and its model is `TIER_1`, and the model is currently
        `APPROVED_FOR_USE`, the model is immediately suspended and every `ACTIVE`
        monitoring metric on it is paused, as detailed in §3.8."

        The same HIGH escalation on a TIER_2 model escalates the finding but leaves the
        model APPROVED_FOR_USE and its metric ACTIVE.

        Design: Corner/cross_cutting_complexity_layers/escalated_high_finding_on_tier2_does_not_suspend
        """
        ctx = create_approved_model(name="T2Esc M", declared_complexity="MEDIUM",
                                    usage_scope="SINGLE_DESK", exposure_amount=100,
                                    assessed_complexity="MEDIUM")
        model = ctx["model"]
        assert model["risk_tier"] == "TIER_2"
        metric = add_metric(model["id"], "psi", "ABOVE_IS_BREACH", 0.25,
                            owner_headers=ctx["owner_headers"])
        finding = create_finding(model["id"], severity="HIGH", title="tier2 escalation")
        assert_instant_equal(finding["remediation_due_at"], "2026-09-15T00:00:00Z",
                             "round(30 * 1.5) = 45 days at pinned TIER_2")
        set_clock("2026-09-23T00:00:00Z")
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert findings[0]["status"] == "ESCALATED", "2026-09-23 > 2026-09-15 + 7d"
        assert get_model(model["id"])["status"] == "APPROVED_FOR_USE", (
            "escalation suspension requires TIER_1"
        )
        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["status"] == "ACTIVE"


class TestSuspendResumeConservation:
    def test_suspend_pauses_all_metrics_conserving_count(self, api):
        """PRD §3.8: "Suspension pauses the model's monitoring: every `ACTIVE` metric
        transitions to `PAUSED`, and a paused metric admits no new readings."

        Suspending moves both metrics ACTIVE -> PAUSED; the count of the model's
        metrics in {ACTIVE, PAUSED} stays 2.

        Design: Difficulty/compensating_invariant/suspend_resume_conserves_metric_activation
        """
        scenario = create_suspended_tier1_model(severity="CRITICAL",
                                                finding_time="2026-08-02T00:00:00Z",
                                                sweep_to="2026-08-24T00:00:00Z",
                                                metric_names=("psi", "auc"))
        model_id = scenario["model"]["id"]
        assert scenario["model"]["status"] == "SUSPENDED"
        metrics, _ = validate_paginated(api.list_metrics(model_id, OWNER_A))
        assert len(metrics) == 2
        live = [m for m in metrics if m["status"] in ("ACTIVE", "PAUSED")]
        assert len(live) == 2
        assert all(m["status"] == "PAUSED" for m in metrics)

    def test_resume_reactivates_same_metrics(self, api):
        """PRD §3.8: "Immediately after any finding on a `SUSPENDED` model transitions
        to `CLOSED`, the auto-resume check runs: if no finding remains on the model
        with status `OPEN`, `OVERDUE`, or `ESCALATED` and severity `HIGH` or
        `CRITICAL`, the model returns to `APPROVED_FOR_USE` and every `PAUSED` metric
        returns to `ACTIVE`."

        Closing the escalated CRITICAL finding (retest evidence completed at
        2026-08-24, after the finding's 2026-08-02 created_at) resumes the model and
        returns each metric's identity and status to ACTIVE; the per-model count of
        metrics in {ACTIVE, PAUSED} is conserved at 2 across the round trip.

        Design: Difficulty/compensating_invariant/suspend_resume_conserves_metric_activation
        """
        scenario = create_suspended_tier1_model(severity="CRITICAL",
                                                finding_time="2026-08-02T00:00:00Z",
                                                sweep_to="2026-08-24T00:00:00Z",
                                                metric_names=("psi", "auc"))
        model_id = scenario["model"]["id"]
        psi_id = scenario["metrics"]["psi"]["id"]
        auc_id = scenario["metrics"]["auc"]["id"]
        _complete_retest_engagement(model_id)
        validate_success(api.close_finding(model_id, scenario["finding"]["id"], OFFICER))

        assert get_model(model_id)["status"] == "APPROVED_FOR_USE", "auto-resume"
        for name, mid in (("psi", psi_id), ("auc", auc_id)):
            metric = validate_success(api.get_metric(mid, OWNER_A))
            assert metric["status"] == "ACTIVE", f"metric {name} identity and status restored"
        metrics, _ = validate_paginated(api.list_metrics(model_id, OWNER_A))
        live = [m for m in metrics if m["status"] in ("ACTIVE", "PAUSED")]
        assert len(live) == 2, "conserved across the suspend/resume round trip"


class TestRetirement:
    def test_retire_with_registered_replacement_rejected(self, api):
        """PRD §3.8: "then the referential gate requires the replacement itself to be
        `APPROVED_FOR_USE`, else `ERR_REPLACEMENT_MODEL_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/retire_requires_replacement_model_approved
        """
        ctx_a = create_approved_model(name="Retire A", declared_complexity="LOW",
                                      usage_scope="SINGLE_DESK", exposure_amount=100,
                                      assessed_complexity="LOW")
        b = create_model(name="Unready B", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                         exposure_amount=100)
        assert b["status"] == "REGISTERED"
        err = validate_error(
            api.retire_model(ctx_a["model"]["id"], {"replacement_model_id": b["id"]}, OFFICER),
            ApiErrorId.ERR_REPLACEMENT_MODEL_NOT_APPROVED,
        )
        assert err["error_id"] == "ERR_REPLACEMENT_MODEL_NOT_APPROVED"
        after = get_model(ctx_a["model"]["id"])
        assert after["status"] == "APPROVED_FOR_USE"
        assert after.get("replaced_by_model_id") is None

    def test_retire_with_suspended_replacement_rejected(self, api):
        """PRD §3.8: "then the referential gate requires the replacement itself to be
        `APPROVED_FOR_USE`, else `ERR_REPLACEMENT_MODEL_NOT_APPROVED`".

        A SUSPENDED replacement — approved earlier, then suspended by an escalated
        CRITICAL finding — also fails the gate: only APPROVED_FOR_USE satisfies it.

        Design: Difficulty/cross_entity_state_dependency/retire_requires_replacement_model_approved
        """
        ctx_a = create_approved_model(name="Retire A", declared_complexity="LOW",
                                      usage_scope="SINGLE_DESK", exposure_amount=100,
                                      assessed_complexity="LOW")
        suspended_b = create_suspended_tier1_model(severity="CRITICAL",
                                                   finding_time="2026-08-01T00:00:00Z",
                                                   sweep_to="2026-08-23T00:00:00Z",
                                                   metric_names=("psi",))
        b = suspended_b["model"]
        assert b["status"] == "SUSPENDED"
        err = validate_error(
            api.retire_model(ctx_a["model"]["id"], {"replacement_model_id": b["id"]}, OFFICER),
            ApiErrorId.ERR_REPLACEMENT_MODEL_NOT_APPROVED,
        )
        assert err["error_id"] == "ERR_REPLACEMENT_MODEL_NOT_APPROVED"

    def test_retire_terminal_lockdown_blocks_further_transitions(self, api):
        """PRD §3.8: "Retirement is a deliberate `ModelRiskOfficer` action that moves a
        model from `APPROVED_FOR_USE` or `SUSPENDED` to the terminal `RETIRED`."
        PRD §3.8: "then the state gate requires the retired model to be
        `APPROVED_FOR_USE` or `SUSPENDED`, else `ERR_MODEL_NOT_RETIRABLE`".

        Design: Corner/state_machines/retire_terminal_lockdown_blocks_further_transitions
        """
        retired, replacement = create_retired_pair()
        third_ctx = create_approved_model(name="TL M3", declared_complexity="LOW",
                                          usage_scope="SINGLE_DESK", exposure_amount=100,
                                          assessed_complexity="LOW")
        err = validate_error(
            api.retire_model(retired["id"], {"replacement_model_id": third_ctx["model"]["id"]}, OFFICER),
            ApiErrorId.ERR_MODEL_NOT_RETIRABLE,
        )
        assert err["error_id"] == "ERR_MODEL_NOT_RETIRABLE"
        after = get_model(retired["id"])
        assert after["status"] == "RETIRED"
        assert after["replaced_by_model_id"] == replacement["id"], "unchanged by the failed retire"

    def test_retire_self_replacement_rejected(self, api):
        """PRD §3.8: "and finally the constraint gate forbids naming the retired model
        as its own replacement, else `ERR_SELF_REPLACEMENT`."

        Design: Corner/validations/retire_self_replacement_rejected
        """
        ctx = create_approved_model(name="SelfRep M", declared_complexity="LOW",
                                    usage_scope="SINGLE_DESK", exposure_amount=100,
                                    assessed_complexity="LOW")
        err = validate_error(
            api.retire_model(ctx["model"]["id"], {"replacement_model_id": ctx["model"]["id"]}, OFFICER),
            ApiErrorId.ERR_SELF_REPLACEMENT,
        )
        assert err["error_id"] == "ERR_SELF_REPLACEMENT"
        assert get_model(ctx["model"]["id"])["status"] == "APPROVED_FOR_USE"

    def test_retire_with_unknown_replacement_returns_not_found(self, api):
        """PRD §3.8: "first the body-referenced identifier must resolve to an existing
        model, else `ERR_NOT_FOUND` at the existence stage".

        Design: Corner/validations/retire_with_unknown_replacement_returns_not_found
        """
        ctx = create_approved_model(name="GhostRep M", declared_complexity="LOW",
                                    usage_scope="SINGLE_DESK", exposure_amount=100,
                                    assessed_complexity="LOW")
        err = validate_error(
            api.retire_model(ctx["model"]["id"], {"replacement_model_id": NON_EXISTENT_UUID}, OFFICER),
            ApiErrorId.ERR_NOT_FOUND,
        )
        assert err["error_id"] == "ERR_NOT_FOUND"

    def test_child_creation_on_retired_model_returns_already_retired(self, api):
        """PRD §3.6: "A `ModelValidator` or `ModelRiskOfficer` raises one on any
        non-retired model by supplying a `severity` (`LOW`, `MEDIUM`, `HIGH`, or
        `CRITICAL`) and a short `title`."
        PRD §3.2: "Submission is impossible on a retired model
        (`ERR_MODEL_ALREADY_RETIRED`)".

        Finding creation on a RETIRED model fails with ERR_MODEL_ALREADY_RETIRED.

        Design: Corner/state_machines/child_creation_on_retired_model_returns_already_retired
        """
        retired, _replacement = create_retired_pair()
        err = validate_error(
            api.create_finding(retired["id"], {"severity": "LOW", "title": "post-retire finding"},
                               OFFICER),
            ApiErrorId.ERR_MODEL_ALREADY_RETIRED,
        )
        assert err["error_id"] == "ERR_MODEL_ALREADY_RETIRED"

    def test_retirement_transfers_findings_and_decommissions_metrics(self, api):
        """PRD §3.8: "Every metric of the retired model in `ACTIVE` or `PAUSED` status
        is decommissioned. Every finding of the retired model in `OPEN`, `OVERDUE`, or
        `ESCALATED` status is transferred to the replacement: its `model_id` is
        repointed, and its `remediation_due_at` is recomputed from its own `created_at`
        under the deadline formula of §3.6 — base days by severity, tier multiplication
        rounded half-up, the monitoring deduction when applicable, and the
        seven-to-three-hundred-sixty-five-day clamp — but evaluated against the
        replacement model's tier at transfer time, before the transferred findings are
        counted into the replacement's penalty. Finally, the retired model's
        `open_findings_count` drops to zero, while the replacement's
        `open_findings_count` is recomputed and its `risk_score` and `risk_tier` are
        recomputed as the transferred findings join its penalty".

        M1 (TIER_3) with one ACTIVE metric and one OPEN MEDIUM finding due 2026-11-29
        (round(60*2.0) = 120 days) retires into M2 (TIER_1, 85 after assessed HIGH):
        the finding moves to M2 with deadline recomputed at TIER_1 (60 days ->
        2026-09-30), M1's count zeroes, M2 scores 85 + 2 = 87.

        Design: Corner/cross_cutting_complexity_layers/retirement_transfers_findings_and_decommissions_metrics
        """
        ctx1 = create_approved_model(name="Trans M1", declared_complexity="LOW",
                                     usage_scope="SINGLE_DESK", exposure_amount=100,
                                     assessed_complexity="LOW")
        m1 = ctx1["model"]
        metric = add_metric(m1["id"], "psi", "ABOVE_IS_BREACH", 0.25,
                            owner_headers=ctx1["owner_headers"])
        finding = create_finding(m1["id"], severity="MEDIUM", title="transfer me")
        assert_instant_equal(finding["remediation_due_at"], "2026-11-29T00:00:00Z",
                             "original deadline at pinned TIER_3")

        ctx2 = create_approved_model(name="Trans M2", declared_complexity="HIGH",
                                     usage_scope="SINGLE_DESK", exposure_amount=100,
                                     assessed_complexity="HIGH")
        m2 = ctx2["model"]
        assert m2["risk_tier"] == "TIER_1" and m2["risk_score"] == 85

        retired = validate_success(
            api.retire_model(m1["id"], {"replacement_model_id": m2["id"]}, OFFICER)
        )
        assert retired["status"] == "RETIRED"
        assert retired["replaced_by_model_id"] == m2["id"]
        assert retired["open_findings_count"] == 0

        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["status"] == "DECOMMISSIONED"

        findings, _ = validate_paginated(api.list_findings(m2["id"], OFFICER))
        transferred = [f for f in findings if f["id"] == finding["id"]]
        assert len(transferred) == 1, "the finding was transferred to the replacement"
        assert transferred[0]["model_id"] == m2["id"]
        assert_instant_equal(transferred[0]["remediation_due_at"], "2026-09-30T00:00:00Z",
                             "recomputed at replacement TIER_1: created 2026-08-01 + 60 days")

        m2_after = get_model(m2["id"])
        assert m2_after["open_findings_count"] == 1
        assert m2_after["risk_score"] == 87, f"expected 85 + 2 = 87, got {m2_after['risk_score']}"

    def test_retired_model_excluded_from_report_input_set(self, api):
        """PRD §3.9: "The snapshot's input set is every model whose `created_at` falls
        on or before the report's `period_end` and whose status is `REGISTERED`,
        `APPROVED_FOR_USE`, or `SUSPENDED`; `RETIRED` models are excluded."
        PRD §3.9: "Under `EQUAL_WEIGHTED` it is the plain arithmetic mean of the input
        set's `risk_score` values."

        After retiring M1 into M2, a fresh report counts only M2 (35 after assessed
        LOW) -> total_models 1, inventory_risk_index 35.00.

        Design: Corner/entities/retired_model_excluded_from_report_input_set
        """
        retired, replacement = create_retired_pair()
        assert replacement["risk_score"] == 35  # VALIDATOR_ASSESSED LOW: 25*1 + 0 + 10
        report = create_draft_report(report_type="BOARD_QUARTERLY",
                                     period_start="2026-07-01T00:00:00Z",
                                     period_end="2026-09-30T00:00:00Z",
                                     aggregation_method="EQUAL_WEIGHTED")
        assert report["total_models"] == 1, "RETIRED M1 excluded from the input set"
        assert float(report["inventory_risk_index"]) == 35.00
