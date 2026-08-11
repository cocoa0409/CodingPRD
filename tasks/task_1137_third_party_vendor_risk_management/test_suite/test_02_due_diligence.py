"""Due-diligence packages: aggregate score weights, snapshot semantics,
reject/resubmit cycle, review-round cap, SoD and OCC guards, and the
DD_APPROVED gate on contract creation."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_dd_package,
    create_engagement,
    create_vendor,
    get_engagement,
    reset_clock,
    setup_engagement_with_approved_dd,
    submit_dd_package,
    tier_change_vendor,
    validate_error,
    validate_success,
    make_risk_officer_headers,
    make_vrm_headers,
)
from test_helpers.fixtures import VRM, RO


def _get_package(api, package_id):
    return validate_success(api.get_dd_package(package_id, RO), 200)


class TestDDAggregateScoreSemantics:
    def test_dd_score_frozen_after_tier_change(self, api):
        """PRD §3.3: "Score semantics are snapshot-at-submit: a subsequent tier
        change on the vendor does not recompute the score on already-submitted
        packages."
        PRD §3.3: "For `TIER_3_STANDARD` vendors, they are 0.40, 0.35, and
        0.25."

        Design: Difficulty/dual_variant_calc/dd_score_snapshot_vs_live_recompute_on_tier_change
        """
        reset_clock()
        vendor = create_vendor(name="Acme Cloud Corp", category="CLOUD_INFRA")
        engagement = create_engagement(vendor["id"], code="ACME-001", sensitivity="CONFIDENTIAL")
        package = create_dd_package(engagement["id"], fin=80, sec=90, comp=70, reviewer_tag="snap1")
        submitted = submit_dd_package(package["id"])
        # TIER_3 weights: 80*0.40 + 90*0.35 + 70*0.25 = 32.00 + 31.50 + 17.50
        assert submitted["aggregate_dd_score"] == pytest.approx(81.00, abs=1e-9)

        tier_change_vendor(vendor["id"], "TIER_1_CRITICAL", reason="Re-classified as critical infrastructure")

        reread = _get_package(api, package["id"])
        assert reread["aggregate_dd_score"] == pytest.approx(81.00, abs=1e-9), (
            "snapshot-at-submit: tier change must not recompute an already-submitted score"
        )

    def test_new_submission_after_tier_change_uses_new_weights(self, api):
        """PRD §3.3: "Weights depend on the vendor's `criticality_tier` at the
        moment of submission."
        PRD §3.3: "For `TIER_1_CRITICAL` vendors, the financial, security, and
        compliance weights are 0.25, 0.45, and 0.30 respectively."

        Design: Difficulty/dual_variant_calc/dd_score_snapshot_vs_live_recompute_on_tier_change
        """
        reset_clock()
        vendor = create_vendor(name="Acme Cloud Corp 2", category="CLOUD_INFRA")
        engagement = create_engagement(vendor["id"], code="ACME-002", sensitivity="CONFIDENTIAL")
        package = create_dd_package(engagement["id"], fin=80, sec=90, comp=70, reviewer_tag="snap2")
        submit_dd_package(package["id"])
        tier_change_vendor(vendor["id"], "TIER_1_CRITICAL", reason="re-tiered")

        # A second engagement + package on the now-TIER_1 vendor submits under T1 weights.
        engagement2 = create_engagement(vendor["id"], code="ACME-003", sensitivity="CONFIDENTIAL")
        package2 = create_dd_package(engagement2["id"], fin=80, sec=90, comp=70, reviewer_tag="snap3")
        submitted2 = submit_dd_package(package2["id"])
        # TIER_1 weights: 80*0.25 + 90*0.45 + 70*0.30 = 20.00 + 40.50 + 21.00
        assert submitted2["aggregate_dd_score"] == pytest.approx(81.50, abs=1e-9)


class TestDDTierConditionalWeights:
    def test_same_triple_scores_differently_on_tier3_vs_tier1(self, api):
        """PRD §3.3: "For `TIER_1_CRITICAL` vendors, the financial, security,
        and compliance weights are 0.25, 0.45, and 0.30 respectively. For
        `TIER_2_HIGH` vendors, they are 0.30, 0.40, and 0.30. For
        `TIER_3_STANDARD` vendors, they are 0.40, 0.35, and 0.25. For
        `TIER_4_LOW` vendors, they are 0.50, 0.25, and 0.25."

        Design: Difficulty/combinatorial_formula/dd_score_tier_conditional_weight_selection
        """
        reset_clock()
        v_t3 = create_vendor(name="Tier3 Vendor")
        e_t3 = create_engagement(v_t3["id"], code="T3-E1", sensitivity="PUBLIC", spend=100)
        p_t3 = create_dd_package(e_t3["id"], fin=70, sec=80, comp=90, reviewer_tag="t3")
        s_t3 = submit_dd_package(p_t3["id"])

        v_t1 = create_vendor(name="Tier1 Vendor", category="CLOUD_INFRA")
        tier_change_vendor(v_t1["id"], "TIER_1_CRITICAL", reason="critical infra")
        e_t1 = create_engagement(v_t1["id"], code="T1-E1", sensitivity="REGULATED", spend=100)
        p_t1 = create_dd_package(e_t1["id"], fin=70, sec=80, comp=90, reviewer_tag="t1")
        s_t1 = submit_dd_package(p_t1["id"])

        # T3: 70*0.40 + 80*0.35 + 90*0.25 = 78.50 ; T1: 70*0.25 + 80*0.45 + 90*0.30 = 80.50
        assert s_t3["aggregate_dd_score"] == pytest.approx(78.50, abs=1e-9)
        assert s_t1["aggregate_dd_score"] == pytest.approx(80.50, abs=1e-9)
        assert s_t1["aggregate_dd_score"] != s_t3["aggregate_dd_score"]

    def test_same_triple_scores_differently_on_tier2_vs_tier4(self, api):
        """PRD §3.3: "For `TIER_2_HIGH` vendors, they are 0.30, 0.40, and 0.30.
        ... For `TIER_4_LOW` vendors, they are 0.50, 0.25, and 0.25."

        Design: Difficulty/combinatorial_formula/dd_score_tier_conditional_weight_selection
        """
        reset_clock()
        v_t2 = create_vendor(name="Tier2 Vendor")
        tier_change_vendor(v_t2["id"], "TIER_2_HIGH", reason="high")
        e_t2 = create_engagement(v_t2["id"], code="T2-E1", sensitivity="INTERNAL", spend=100)
        p_t2 = create_dd_package(e_t2["id"], fin=70, sec=80, comp=90, reviewer_tag="t2")
        s_t2 = submit_dd_package(p_t2["id"])

        v_t4 = create_vendor(name="Tier4 Vendor")
        tier_change_vendor(v_t4["id"], "TIER_4_LOW", reason="low")
        e_t4 = create_engagement(v_t4["id"], code="T4-E1", sensitivity="PUBLIC", spend=100)
        p_t4 = create_dd_package(e_t4["id"], fin=70, sec=80, comp=90, reviewer_tag="t4")
        s_t4 = submit_dd_package(p_t4["id"])

        # T2: 70*0.30 + 80*0.40 + 90*0.30 = 80.00 ; T4: 70*0.50 + 80*0.25 + 90*0.25 = 77.50
        assert s_t2["aggregate_dd_score"] == pytest.approx(80.00, abs=1e-9)
        assert s_t4["aggregate_dd_score"] == pytest.approx(77.50, abs=1e-9)


class TestDDRejectResubmitCycle:
    def test_reject_then_resubmit_increments_round_and_recomputes(self, api):
        """PRD §3.2: "On resubmit, `review_round` is incremented by 1 and
        `aggregate_dd_score` and `dd_outcome` are recomputed from the (possibly
        edited) scores using the tier weights in force at this new submission
        instant."
        PRD §3.2: "Rejection transitions the package `UNDER_REVIEW → REJECTED`."

        Design: Difficulty/non_linear_state_machine/dd_package_reject_resubmit_cycle
        """
        reset_clock()
        vendor = create_vendor(name="Cycle Vendor")
        engagement = create_engagement(vendor["id"], code="CYC-E1", spend=100)
        package = create_dd_package(engagement["id"], fin=70, sec=70, comp=70, reviewer_tag="cyc")
        submit_dd_package(package["id"])
        validate_success(api.begin_review_dd_package(package["id"], RO), 200)
        rejected = validate_success(api.reject_dd_package(package["id"], RO), 200)
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(
            api.resubmit_dd_package(
                package["id"],
                {"financial_review_score": 90, "security_review_score": 90, "compliance_review_score": 90},
                VRM,
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["review_round"] == 2
        # TIER_3 weights on (90, 90, 90): 90*0.40 + 90*0.35 + 90*0.25 = 90.00
        assert resubmitted["aggregate_dd_score"] == pytest.approx(90.00, abs=1e-9)

    def test_resubmit_without_edits_keeps_scores_and_recomputes(self, api):
        """PRD §3.2: "Resubmission may carry updated values for any of
        `financial_review_score`, `security_review_score`, or
        `compliance_review_score`."
        PRD §3.3: "The outcome `dd_outcome` is then derived from the score: a
        value of at least 75.00 yields `PASS`; a value of at least 60.00 but
        less than 75.00 yields `CONDITIONAL_PASS`; any lower value yields
        `FAIL`."

        Design: Difficulty/non_linear_state_machine/dd_package_reject_resubmit_cycle
        """
        reset_clock()
        vendor = create_vendor(name="Cycle Vendor 2")
        engagement = create_engagement(vendor["id"], code="CYC-E2", spend=100)
        package = create_dd_package(engagement["id"], fin=60, sec=60, comp=60, reviewer_tag="cy2")
        submit_dd_package(package["id"])
        validate_success(api.begin_review_dd_package(package["id"], RO), 200)
        validate_success(api.reject_dd_package(package["id"], RO), 200)

        resubmitted = validate_success(api.resubmit_dd_package(package["id"], {}, VRM), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["review_round"] == 2
        # Unedited scores (60, 60, 60) under TIER_3 weights: 60.00 -> CONDITIONAL_PASS
        assert resubmitted["aggregate_dd_score"] == pytest.approx(60.00, abs=1e-9)
        assert resubmitted["dd_outcome"] == "CONDITIONAL_PASS"


class TestDDPrecisionAndOutcome:
    def test_aggregate_precision_round_half_up(self, api):
        """PRD §3.3: "The raw weighted sum is rounded half-up to two decimal
        places and stored on `aggregate_dd_score`."
        PRD §2.6: "All monetary and percentage values computed by the system
        use 2 decimal places with round-half-up unless a specific calculation
        documents otherwise."

        Design: Corner/calculations/dd_aggregate_precision_round_half_up
        """
        reset_clock()
        vendor = create_vendor(name="PrecV")
        engagement = create_engagement(vendor["id"], code="PV-E1", sensitivity="PUBLIC", spend=100)
        package = create_dd_package(engagement["id"], fin=75, sec=85, comp=95, reviewer_tag="prec")
        submitted = submit_dd_package(package["id"])
        # 75*0.40 + 85*0.35 + 95*0.25 = 30.00 + 29.75 + 23.75 = 83.50 exactly
        assert submitted["aggregate_dd_score"] == pytest.approx(83.50, abs=1e-9)

    def test_dd_outcome_pass_at_exactly_75(self, api):
        """PRD §3.3: "The outcome `dd_outcome` is then derived from the score:
        a value of at least 75.00 yields `PASS`; a value of at least 60.00 but
        less than 75.00 yields `CONDITIONAL_PASS`; any lower value yields
        `FAIL`."

        Design: Corner/calculations/dd_outcome_thresholds_at_pass_boundary
        """
        reset_clock()
        vendor = create_vendor(name="OutV")
        engagement = create_engagement(vendor["id"], code="OUT-E1", sensitivity="PUBLIC", spend=100)
        package = create_dd_package(engagement["id"], fin=75, sec=75, comp=75, reviewer_tag="out")
        submitted = submit_dd_package(package["id"])
        assert submitted["aggregate_dd_score"] == pytest.approx(75.00, abs=1e-9)
        assert submitted["dd_outcome"] == "PASS"


class TestDDStateAndSoD:
    def test_approve_from_draft_rejected_and_no_side_effects(self, api):
        """PRD §3.2: "Approval requires the package to be `UNDER_REVIEW`
        (otherwise `ERR_DD_NOT_UNDER_REVIEW`, HTTP 409)"

        Design: Corner/state_machines/invalid_transition_dd_approve_from_draft
        """
        reset_clock()
        vendor = create_vendor(name="InvT")
        engagement = create_engagement(vendor["id"], code="IT-E1", sensitivity="PUBLIC", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="inv")
        current = get_engagement(engagement["id"])
        res = api.approve_dd_package(
            package["id"], {"expected_engagement_version": current["version"]}, RO
        )
        validate_error(res, ApiErrorId.ERR_DD_NOT_UNDER_REVIEW.value)
        assert _get_package(api, package["id"])["status"] == "DRAFT"

    def test_approve_by_submitter_rejected_sod(self, api):
        """PRD §3.2: "Approval requires the package to be `UNDER_REVIEW`
        (otherwise `ERR_DD_NOT_UNDER_REVIEW`, HTTP 409), requires that
        `X-User-ID` differ from `submitted_by_user_id` (otherwise
        `ERR_SOD_DD_SELF_APPROVE`, HTTP 403)"

        Design: Corner/state_machines/dd_approve_by_submitter_rejected_sod
        """
        reset_clock()
        vendor = create_vendor(name="SoD1")
        engagement = create_engagement(vendor["id"], code="SOD1-E1", sensitivity="PUBLIC", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="sod1")
        submitter = make_vrm_headers("u_vrm_submitter_1")
        submitted = submit_dd_package(package["id"], submitter_headers=submitter)
        assert submitted["submitted_by_user_id"] == "u_vrm_submitter_1"
        validate_success(api.begin_review_dd_package(package["id"], RO), 200)
        current = get_engagement(engagement["id"])

        res = api.approve_dd_package(
            package["id"],
            {"expected_engagement_version": current["version"]},
            make_risk_officer_headers("u_vrm_submitter_1"),
        )
        validate_error(res, ApiErrorId.ERR_SOD_DD_SELF_APPROVE.value)

    def test_state_error_precedes_sod_on_dd_approve(self, api):
        """PRD §3.16: "Authentication (`ERR_UNAUTHENTICATED`) runs before
        authorization (`ERR_UNAUTHORIZED`), which runs before path resolution
        (`ERR_NOT_FOUND`), which runs before state-machine preconditions
        (`ERR_INVALID_STATE` and the more specific state errors), which run
        before segregation-of-duties checks (`ERR_SOD_*`)"
        PRD §3.2: "Approval requires the package to be `UNDER_REVIEW`
        (otherwise `ERR_DD_NOT_UNDER_REVIEW`, HTTP 409), requires that
        `X-User-ID` differ from `submitted_by_user_id` (otherwise
        `ERR_SOD_DD_SELF_APPROVE`, HTTP 403)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_sod_on_dd_approve
        """
        reset_clock()
        vendor = create_vendor(name="Prio1 Vendor")
        engagement = create_engagement(vendor["id"], code="PR1-E1", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="pr1")
        submitted = submit_dd_package(package["id"], submitter_headers=make_vrm_headers("u_pr1_sub"))
        submitter_id = submitted["submitted_by_user_id"]
        current = get_engagement(engagement["id"])

        # Package is SUBMITTED (not UNDER_REVIEW) AND approver == submitter:
        # the state error must surface first.
        res = api.approve_dd_package(
            package["id"],
            {"expected_engagement_version": current["version"]},
            make_risk_officer_headers(submitter_id),
        )
        validate_error(res, ApiErrorId.ERR_DD_NOT_UNDER_REVIEW.value)

    def test_sod_error_fires_once_state_check_passes(self, api):
        """PRD §3.16: "Authentication (`ERR_UNAUTHENTICATED`) runs before
        authorization (`ERR_UNAUTHORIZED`), which runs before path resolution
        (`ERR_NOT_FOUND`), which runs before state-machine preconditions
        (`ERR_INVALID_STATE` and the more specific state errors), which run
        before segregation-of-duties checks (`ERR_SOD_*`)"
        PRD §3.2: "requires that `X-User-ID` differ from
        `submitted_by_user_id` (otherwise `ERR_SOD_DD_SELF_APPROVE`, HTTP 403)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_sod_on_dd_approve
        """
        reset_clock()
        vendor = create_vendor(name="Prio1b Vendor")
        engagement = create_engagement(vendor["id"], code="PR1B-E1", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="pr1b")
        submitted = submit_dd_package(package["id"], submitter_headers=make_vrm_headers("u_pr1b_sub"))
        validate_success(api.begin_review_dd_package(package["id"], RO), 200)
        current = get_engagement(engagement["id"])

        # State check now passes (UNDER_REVIEW); the SoD violation surfaces.
        res = api.approve_dd_package(
            package["id"],
            {"expected_engagement_version": current["version"]},
            make_risk_officer_headers(submitted["submitted_by_user_id"]),
        )
        validate_error(res, ApiErrorId.ERR_SOD_DD_SELF_APPROVE.value)

    def test_dd_resubmit_blocked_after_third_rejection(self, api):
        """PRD §3.2: "A rejected package can be resubmitted by a
        `VendorRelationshipManager` while its `review_round` is still less than
        3; attempts to resubmit at `review_round` equal to 3 are rejected with
        `ERR_DD_REVIEW_ROUND_EXHAUSTED` (HTTP 422)"

        Design: Corner/state_machines/dd_resubmit_exhausted_review_round
        """
        reset_clock()
        vendor = create_vendor(name="Exh")
        engagement = create_engagement(vendor["id"], code="EX-E1", sensitivity="PUBLIC", spend=100)
        package = create_dd_package(engagement["id"], fin=60, sec=60, comp=60, reviewer_tag="exh")
        p_id = package["id"]
        submit_dd_package(p_id)
        for expected_round in (2, 3):
            validate_success(api.begin_review_dd_package(p_id, RO), 200)
            validate_success(api.reject_dd_package(p_id, RO), 200)
            resub = validate_success(api.resubmit_dd_package(p_id, {}, VRM), 200)
            assert resub["review_round"] == expected_round
        validate_success(api.begin_review_dd_package(p_id, RO), 200)
        validate_success(api.reject_dd_package(p_id, RO), 200)

        res = api.resubmit_dd_package(p_id, {}, VRM)
        validate_error(res, ApiErrorId.ERR_DD_REVIEW_ROUND_EXHAUSTED.value)


class TestDDApproveOCC:
    def test_stale_engagement_version_rejected_on_approve(self, api):
        """PRD §3.2: "Approval is also OCC-guarded: the request must carry
        `expected_engagement_version` matching the engagement's current
        `version`, otherwise `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "If the value does not match the parent entity's current
        `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), protecting the client from overwriting changes it has not
        observed."

        Design: Corner/errors/err_stale_version_on_dd_approve
        """
        reset_clock()
        vendor = create_vendor(name="OccV")
        engagement = create_engagement(vendor["id"], code="OCC-E1", sensitivity="PUBLIC", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="occ")
        submit_dd_package(package["id"])
        validate_success(api.begin_review_dd_package(package["id"], RO), 200)
        current = get_engagement(engagement["id"])

        res = api.approve_dd_package(
            package["id"],
            {"expected_engagement_version": current["version"] - 1},
            RO,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


class TestContractDependsOnDDApproved:
    def test_contract_create_blocked_while_dd_in_progress(self, api):
        """PRD §3.4: "Creation requires the engagement to be in `DD_APPROVED`,
        otherwise `ERR_DD_NOT_APPROVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/contract_execute_depends_on_dd_approved
        """
        reset_clock()
        vendor = create_vendor(name="XDep1 Vendor")
        engagement = create_engagement(vendor["id"], code="XD1-E1", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="xd1")
        submit_dd_package(package["id"])  # engagement now DD_IN_PROGRESS, not DD_APPROVED

        res = api.create_contract(
            engagement["id"],
            {
                "contract_reference": "XD1-C1",
                "effective_date": "2026-05-01T00:00:00Z",
                "expiry_date": "2027-05-01T00:00:00Z",
                "has_right_to_audit_clause": False,
                "has_sla_terms": True,
                "has_exit_plan_section": False,
                "sla_uptime_pct": 99.5,
                "breach_cure_window_days": 30,
                "renewal_notice_days": 60,
            },
            VRM,
        )
        validate_error(res, ApiErrorId.ERR_DD_NOT_APPROVED.value)

    def test_contract_create_succeeds_after_dd_approval(self, api):
        """PRD §3.4: "Creation requires the engagement to be in `DD_APPROVED`,
        otherwise `ERR_DD_NOT_APPROVED` (HTTP 409)."
        PRD §3.4: "On creation the contract lands in `DRAFT` and the engagement
        transitions `DD_APPROVED → CONTRACTING`."

        Design: Difficulty/cross_entity_state_dependency/contract_execute_depends_on_dd_approved
        """
        ctx = setup_engagement_with_approved_dd(vendor_name="XDep1b Vendor")
        res = api.create_contract(
            ctx["engagement"]["id"],
            {
                "contract_reference": "XD1B-C1",
                "effective_date": "2026-05-01T00:00:00Z",
                "expiry_date": "2027-05-01T00:00:00Z",
                "has_right_to_audit_clause": False,
                "has_sla_terms": True,
                "has_exit_plan_section": False,
                "sla_uptime_pct": 99.5,
                "breach_cure_window_days": 30,
                "renewal_notice_days": 60,
            },
            VRM,
        )
        contract = validate_success(res, 201)
        assert contract["status"] == "DRAFT"
        engagement = get_engagement(ctx["engagement"]["id"])
        assert engagement["lifecycle_status"] == "CONTRACTING"
