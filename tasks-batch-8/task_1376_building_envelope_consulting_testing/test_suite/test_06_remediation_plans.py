"""Remediation plans: dual cost variants, supersede compensation, OCC, cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_engagement,
    create_anomaly,
    create_assembly,
    create_completed_survey,
    create_plan,
    get_engagement,
    issue_plan,
    setup_issued_plan,
    setup_verified_anomaly,
    validate_error,
    validate_paginated,
    validate_success,
    verify_anomaly,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]


class TestRemediationEstimateVsActualCost:

    def _setup_plan_high_medium_four_sections(self):
        """HIGH + MEDIUM verified anomalies; plan with 4 spec sections."""
        eng = create_active_engagement(name="E1")
        asm = create_assembly(eng["id"], tag="W1",
                              required_airtightness_lps_m2=1.5)
        srv = create_completed_survey(eng["id"], asm["id"])
        an1 = create_anomaly(eng["id"], anomaly_type="WATER_INGRESS",
                             severity="HIGH", description="leak at slab edge",
                             survey_id=srv["id"])
        an2 = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                             severity="MEDIUM", description="wet insulation",
                             survey_id=srv["id"])
        verify_anomaly(eng["id"], an1["id"])
        verify_anomaly(eng["id"], an2["id"])
        plan = create_plan(eng["id"], [an1["id"], an2["id"]],
                           ["07 01 00", "07 02 00", "08 01 00", "08 02 00"])
        return eng, plan

    def test_issue_computes_estimate_with_contingency(self):
        """PRD §3.7: "each listed anomaly contributes a base cost keyed to its
        severity — 500000 cents for `LOW`, 1500000 cents for `MEDIUM`, 4000000
        cents for `HIGH`, and 9000000 cents for `CRITICAL` — the bases are
        summed into a subtotal, and a contingency multiplier of twenty percent
        is applied to that subtotal with the product rounded half-up to whole
        cents. The estimate variant carries no mobilization charge."
        PRD §3.7: "The computed estimate is added to the engagement's
        `recognized_fees_cents` as provisional recognition..."

        Design: Difficulty/dual_variant_calc/remediation_estimate_vs_actual_cost
        """
        eng, plan = self._setup_plan_high_medium_four_sections()
        plan = issue_plan(eng["id"], plan["id"])
        # subtotal = 4000000 + 1500000 = 5500000; estimate = 5500000 * 1.20.
        assert plan["estimated_cost_cents"] == 6600000
        assert plan["plan_status"] == "ISSUED"
        assert get_engagement(eng["id"])["recognized_fees_cents"] == 6600000

    def test_completion_computes_actual_and_negative_reconciliation(self):
        """PRD §3.7: "Completion computes the **actual variant** of the
        remediation cost into `actual_cost_cents`: the same severity-keyed
        subtotal over the listed anomalies, with no contingency, plus a
        mobilization charge of 125000 cents for each specification section
        named in `spec_sections`. The engagement's recognized fees then absorb
        only the reconciliation delta — the actual cost minus the previously
        recognized estimate is added to `recognized_fees_cents`, a delta that
        may legitimately be negative when the work came in under estimate."

        Design: Difficulty/dual_variant_calc/remediation_estimate_vs_actual_cost
        """
        eng, plan = self._setup_plan_high_medium_four_sections()
        plan = issue_plan(eng["id"], plan["id"])
        assert plan["estimated_cost_cents"] == 6600000
        resp = api_client.complete_remediation_plan(eng["id"], plan["id"], P)
        data = validate_success(resp, 200)
        # actual = 5500000 + 4 * 125000 = 6000000 != estimate 6600000.
        assert data["actual_cost_cents"] == 6000000
        assert data["actual_cost_cents"] != data["estimated_cost_cents"]
        assert data["plan_status"] == "COMPLETED"
        # recognized: 6600000 + (6000000 - 6600000) = 6000000.
        assert get_engagement(eng["id"])["recognized_fees_cents"] == 6000000


class TestPlanCompletionCascade:

    def _setup_plan_with_open_anomaly(self):
        """Plan ISSUED over a MEDIUM anomaly; a second (LOW) anomaly left OPEN
        so the engagement sits at RESTRICTED before completion."""
        eng, asm, srv, an2 = setup_verified_anomaly(
            severity="MEDIUM", name="E7", anomaly_type="MOISTURE_TRAP")
        plan = create_plan(eng["id"], [an2["id"]], ["07 01 00"])
        plan = issue_plan(eng["id"], plan["id"])
        assert plan["estimated_cost_cents"] == 1800000
        an1 = create_anomaly(eng["id"], anomaly_type="THERMAL_BRIDGE",
                             severity="LOW", description="left open",
                             survey_id=srv["id"])
        before = get_engagement(eng["id"])
        assert before["posture"] == "RESTRICTED"
        assert before["risk_score"] == 95
        return eng, an1, an2, plan, before

    def test_completion_cascades_anomaly_risk_and_posture(self):
        """PRD §3.7: "In the same transaction, every anomaly named in
        `anomaly_ids` cascades from `VERIFIED` to `REMEDIATED`, each one
        returning 10 points to the `risk_score` (clamped at 100) and each
        triggering its own posture re-derivation, followed by a final posture
        derivation for the plan completion itself."
        PRD §2.5: "Otherwise, if the `risk_score` is below 70, or if any
        anomaly of the engagement is in `OPEN` status, the posture is
        `RESTRICTED`."
        PRD §2.5: "A `RESTRICTED` posture blocks only those two operations;
        every other workflow proceeds normally."

        Design: Difficulty/transitive_cascade/plan_completion_remediates_anomaly_recovers_risk_thaws_posture
        """
        eng, an1, an2, plan, before = self._setup_plan_with_open_anomaly()
        resp = api_client.complete_remediation_plan(eng["id"], plan["id"], P)
        data = validate_success(resp, 200)
        assert data["plan_status"] == "COMPLETED"
        assert data["actual_cost_cents"] == 1625000

        an2_after = validate_success(
            api_client.get_anomaly(eng["id"], an2["id"], C), 200)
        assert an2_after["status"] == "REMEDIATED"

        eng_after = get_engagement(eng["id"])
        assert eng_after["risk_score"] == 100
        # The still-OPEN LOW anomaly keeps the posture at RESTRICTED.
        assert eng_after["posture"] == "RESTRICTED"
        # recognized = 1800000 + (1625000 - 1800000).
        assert eng_after["recognized_fees_cents"] == 1625000

    def test_completion_remediates_each_covered_anomaly_with_clamped_recovery(self):
        """PRD §3.7: "In the same transaction, every anomaly named in
        `anomaly_ids` cascades from `VERIFIED` to `REMEDIATED`, each one
        returning 10 points to the `risk_score` (clamped at 100)..."
        PRD §2.6: "the bound is applied after every single delta — the clamping
        happens per event, which matters when several anomalies are remediated
        in one cascade, because each recovery is clamped individually before
        the next is applied."

        Design: Difficulty/transitive_cascade/plan_completion_remediates_anomaly_recovers_risk_thaws_posture
        """
        eng = create_active_engagement(name="E7B")
        asm = create_assembly(eng["id"], tag="W7B")
        srv = create_completed_survey(eng["id"], asm["id"])
        an_m = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                              severity="MEDIUM", description="m",
                              survey_id=srv["id"])
        an_l = create_anomaly(eng["id"], anomaly_type="THERMAL_BRIDGE",
                              severity="LOW", description="l",
                              survey_id=srv["id"])
        verify_anomaly(eng["id"], an_m["id"])
        verify_anomaly(eng["id"], an_l["id"])
        plan = create_plan(eng["id"], [an_m["id"], an_l["id"]], ["07 01 00"])
        plan = issue_plan(eng["id"], plan["id"])
        # estimate = round_half_up((1500000 + 500000) * 1.20) = 2400000.
        assert plan["estimated_cost_cents"] == 2400000

        resp = api_client.complete_remediation_plan(eng["id"], plan["id"], P)
        data = validate_success(resp, 200)
        # actual = 2000000 + 1 * 125000 = 2125000.
        assert data["actual_cost_cents"] == 2125000
        for an in (an_m, an_l):
            after = validate_success(
                api_client.get_anomaly(eng["id"], an["id"], C), 200)
            assert after["status"] == "REMEDIATED"
        eng_after = get_engagement(eng["id"])
        # 100 - 5 - 2 = 93; +10 -> clamped 100; +10 -> 100.
        assert eng_after["risk_score"] == 100
        assert eng_after["posture"] == "OPEN"
        assert eng_after["recognized_fees_cents"] == 2125000


class TestSupersedeRestoresRecognizedFees:

    def _setup_issued_plan_p1(self):
        eng, asm, srv, an = setup_verified_anomaly(
            severity="MEDIUM", name="E17", anomaly_type="MOISTURE_TRAP")
        p1 = create_plan(eng["id"], [an["id"]], ["07 01 00"])
        p1 = issue_plan(eng["id"], p1["id"])
        return eng, an, p1

    def test_supersede_reverses_provisional_recognition(self):
        """PRD §3.7: "A valid supersession flips the referenced plan from
        `ISSUED` to `SUPERSEDED` automatically as part of the create, reverses
        that plan's provisional recognition by subtracting its
        `estimated_cost_cents` from the engagement's `recognized_fees_cents`,
        re-derives the engagement posture, and — like every successful plan
        creation — increments the engagement's `version` by 1."

        Design: Difficulty/compensating_invariant/supersede_restores_recognized_fees
        """
        eng, an, p1 = self._setup_issued_plan_p1()
        assert p1["estimated_cost_cents"] == 1800000
        after_issue = get_engagement(eng["id"])
        assert after_issue["recognized_fees_cents"] == 1800000

        p2 = create_plan(eng["id"], [an["id"]], ["07 01 00", "07 02 00"],
                         supersedes_plan_id=p1["id"])
        assert p2["plan_status"] == "DRAFT"
        p1_after = validate_success(
            api_client.get_remediation_plan(eng["id"], p1["id"], C), 200)
        assert p1_after["plan_status"] == "SUPERSEDED"
        after_supersede = get_engagement(eng["id"])
        assert after_supersede["recognized_fees_cents"] == 0
        assert after_supersede["version"] == after_issue["version"] + 1

    def test_superseding_plan_traceable_via_flat_list_filter(self):
        """PRD §3.7: "The flat remediation-plan list accepts a
        `supersedes_plan_id` filter, which is how a reviewer traces which
        drafts were written to replace a given issued plan."
        PRD §3.7: "A valid supersession flips the referenced plan from `ISSUED`
        to `SUPERSEDED` automatically as part of the create..."

        Design: Difficulty/compensating_invariant/supersede_restores_recognized_fees
        """
        eng, an, p1 = self._setup_issued_plan_p1()
        p2 = create_plan(eng["id"], [an["id"]], ["07 01 00", "07 02 00"],
                         supersedes_plan_id=p1["id"])
        plans, meta = validate_paginated(
            api_client.list_remediation_plans_flat(
                C, params={"supersedes_plan_id": p1["id"]}))
        assert len(plans) == 1
        assert plans[0]["id"] == p2["id"]
        p1_after = validate_success(
            api_client.get_remediation_plan(eng["id"], p1["id"], C), 200)
        assert p1_after["plan_status"] == "SUPERSEDED"


class TestPlanGates:

    def test_fee_cap_exceeded_on_plan_issue(self):
        """PRD §2.7: "The provisional variant is guarded by a fiscal gate: any
        transition that would provisionally recognize fees is rejected with
        `ERR_FEE_CAP_EXCEEDED` (HTTP 402) when applying the event would push
        `fee_headroom_cents` below zero."
        PRD §2.7: "`fee_headroom_cents` is exactly the engagement's
        `fee_cap_cents` minus its `recognized_fees_cents`."

        Design: Corner/validations/fee_cap_exceeded_on_plan_issue
        """
        eng, asm, srv, an = setup_verified_anomaly(
            severity="MEDIUM", name="EFC", fee_cap_cents=1_000_000,
            anomaly_type="MOISTURE_TRAP")
        # Plan creation is not a fee event and succeeds under a small cap.
        plan = create_plan(eng["id"], [an["id"]], ["07 01 00"])
        # Estimate would be 1800000 > headroom 1000000.
        eng_now = get_engagement(eng["id"])
        resp = api_client.issue_remediation_plan(
            eng["id"], plan["id"],
            {"expected_engagement_version": eng_now["version"]}, C)
        validate_error(resp, ApiErrorId.ERR_FEE_CAP_EXCEEDED)
        after = validate_success(
            api_client.get_remediation_plan(eng["id"], plan["id"], C), 200)
        assert after["plan_status"] == "DRAFT"
        assert get_engagement(eng["id"])["recognized_fees_cents"] == 0

    def test_supersedes_target_must_be_issued(self):
        """PRD §3.7: "When the payload carries `supersedes_plan_id`, that
        reference must point to a remediation plan of the same engagement whose
        `plan_status` is currently `ISSUED`; anything else is rejected with
        `ERR_SUPERSEDES_NOT_ISSUED` (HTTP 409)."

        Design: Corner/validations/supersedes_target_must_be_issued
        """
        eng, asm, srv, an = setup_verified_anomaly(
            severity="MEDIUM", name="ESU", anomaly_type="MOISTURE_TRAP")
        p1 = create_plan(eng["id"], [an["id"]], ["07 01 00"])
        assert p1["plan_status"] == "DRAFT"
        eng_now = get_engagement(eng["id"])
        resp = api_client.create_remediation_plan(
            eng["id"],
            {"anomaly_ids": [an["id"]], "spec_sections": ["07 01 00"],
             "supersedes_plan_id": p1["id"],
             "expected_engagement_version": eng_now["version"]},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_SUPERSEDES_NOT_ISSUED)

    def test_occ_stale_version_on_plan_create(self):
        """PRD §2.9: "Exactly two write operations are guarded by optimistic
        concurrency control against the parent Engagement's `version`: creating
        a remediation plan (`POST /engagements/{id}/remediation-plans`) and
        issuing a remediation plan
        (`POST /engagements/{id}/remediation-plans/{planId}/issue`). ... If the
        supplied value does not equal the engagement's current `version` —
        meaning another write has advanced the engagement since the client last
        read it — the request is rejected with
        `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), and no change is applied."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_plan_create
        """
        eng, asm, srv, an = setup_verified_anomaly(
            severity="MEDIUM", name="EOC", anomaly_type="MOISTURE_TRAP")
        stale_version = get_engagement(eng["id"])["version"]
        # First create advances the engagement version.
        create_plan(eng["id"], [an["id"]], ["07 01 00"])
        resp = api_client.create_remediation_plan(
            eng["id"],
            {"anomaly_ids": [an["id"]], "spec_sections": ["07 03 00"],
             "expected_engagement_version": stale_version},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION)
        # Retrying with the fresh version succeeds.
        fresh_version = get_engagement(eng["id"])["version"]
        resp = api_client.create_remediation_plan(
            eng["id"],
            {"anomaly_ids": [an["id"]], "spec_sections": ["07 03 00"],
             "expected_engagement_version": fresh_version},
            C,
        )
        data = validate_success(resp, 201)
        assert data["plan_status"] == "DRAFT"

    def test_immediate_consistency_of_cascade_in_same_read(self):
        """PRD §3.7: "In the same transaction, every anomaly named in
        `anomaly_ids` cascades from `VERIFIED` to `REMEDIATED`, each one
        returning 10 points to the `risk_score` (clamped at 100) and each
        triggering its own posture re-derivation, followed by a final posture
        derivation for the plan completion itself."

        Design: Corner/consistency_model/immediate_consistency_of_cascade_in_same_read
        """
        eng, asm, srv, an, plan = setup_issued_plan(
            severity="MEDIUM", name="EIC", anomaly_type="MOISTURE_TRAP")
        resp = api_client.complete_remediation_plan(eng["id"], plan["id"], P)
        validate_success(resp, 200)
        # The immediately following reads observe every cascade effect.
        an_after = validate_success(
            api_client.get_anomaly(eng["id"], an["id"], C), 200)
        assert an_after["status"] == "REMEDIATED"
        eng_after = get_engagement(eng["id"])
        assert eng_after["recognized_fees_cents"] == 1625000
        assert eng_after["posture"] == "OPEN"
        assert eng_after["risk_score"] == 100
