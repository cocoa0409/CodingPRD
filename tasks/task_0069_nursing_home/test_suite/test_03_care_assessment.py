"""Care Assessment workflow: drafting, scoring, approval cycle,
segregation of duties, and the cascade to Elder.current_care_level
plus active CarePlan.

Anchored in PRD §3.2 and §3.3.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_assessment,
    create_active_care_plan,
    create_approved_assessment,
    create_assessment_payload,
    create_elder,
    draft_assessment,
    expected_classification,
    expected_composite_score,
    list_audit_logs, find_audit_logs,
    get_elder,
    setup_admitted_elder_v2,
    setup_admitted_elder_with_active_plan,
    submit_assessment,
    ADMIN, NURSE, NURSE_ALT, SUPERVISOR, SUPERVISOR_ALT,
    make_nurse_headers, make_supervisor_headers,
    validate_error, validate_success,
)


# ===========================================================================
# Composite scoring (PRD §3.2)
# ===========================================================================
class TestCompositeScoring:

    def test_composite_uses_weighted_inversions_formula(self):
        """PRD §3.2: "The composite score is a weighted sum of three
        transformed components: the ADL deficit, defined as 100 minus
        `adl_score` and weighted by 0.5; the cognitive deficit, defined
        as 30 minus `cognitive_score` and weighted by 1.0; and the raw
        `medical_condition_score`, weighted by 1.0. The three weighted
        terms are summed and the result is rounded half up to two decimal
        places to obtain `composite_score`."

        Claim: adl=80, cog=10, med=20 → composite == 50.00 → L3.
        # difficulty: dual_variant_calc/care_level_classification_weighted_score
        # difficulty: combinatorial_formula/care_level_three_input_nonlinear_thresholds
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 80, 10, 20)
        submitted = submit_assessment(a["id"])
        assert submitted["composite_score"] == pytest.approx(50.00, abs=0.001), \
            f"PRD §3.2: composite must be 50.00, got {submitted['composite_score']}"
        assert submitted["classification"] == "L3"

    @pytest.mark.parametrize(
        "adl,cog,med,expected_class",
        [
            # PRD §3.2 inclusive lower bounds:
            #   >= 80 INTENSIVE; >= 60 L4; >= 40 L3; >= 20 L2; else L1
            (100, 30, 0,  "L1"),   # composite = 0   → L1
            (80,  20, 0,  "L2"),   # (100-80)*0.5 + (30-20)*1 + 0 = 10+10 = 20 → L2 (inclusive lower bound)
            (60,  10, 20, "L4"),   # difficulty boundary instance
            (60,  11, 20, "L3"),   # 0.5*(40) + 19 + 20 = 20+19+20 = 59 → L3
            (20,  5,  40, "INTENSIVE"),  # composite 105 → INTENSIVE
        ],
    )
    def test_classification_thresholds_inclusive(self, adl, cog, med,
                                                 expected_class):
        """PRD §3.2: "a composite of at least 80 yields `INTENSIVE`;
        otherwise at least 60 yields `L4`; otherwise at least 40 yields
        `L3`; otherwise at least 20 yields `L2`; otherwise `L1`."

        Claim: classification thresholds use inclusive lower bounds.
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], adl, cog, med)
        submitted = submit_assessment(a["id"])
        # Compute expected composite from PRD formula
        expected_comp = expected_composite_score(adl, cog, med)
        assert submitted["composite_score"] == pytest.approx(
            expected_comp, abs=0.001,
        ), f"composite mismatch — expected {expected_comp}"
        assert submitted["classification"] == expected_class, \
            f"classification mismatch — expected {expected_class}, got " \
            f"{submitted['classification']} (composite={submitted['composite_score']})"


# ===========================================================================
# Composite score precision (PRD §2.6 / §3.2)
# ===========================================================================
class TestCompositePrecision:

    def test_composite_held_to_two_decimal_places(self):
        """PRD §2.6: "The composite assessment score from
        `care_level_classification` is held to two decimal places, also
        rounded half up."

        Claim: composite is numeric with at most 2 decimal places.
        """
        elder = create_elder()
        # adl=83 → (17)*0.5 = 8.5 — fractional, needs 2dp
        a = draft_assessment(elder["id"], 83, 10, 20)
        submitted = submit_assessment(a["id"])
        # 8.5 + 20 + 20 = 48.5 → rounded half up to 2dp = 48.50
        assert submitted["composite_score"] == pytest.approx(48.50, abs=0.001)


# ===========================================================================
# Composite boundary at 60 (PRD §3.2 — difficulty instance)
# ===========================================================================
class TestCompositeBoundaryAt60:

    def test_composite_60_is_L4_inclusive(self):
        """PRD §3.2: "otherwise at least 60 yields `L4`."

        Claim: adl=60, cog=10, med=20 → composite 60 (inclusive) → L4.
        # difficulty: combinatorial_formula/care_level_three_input_nonlinear_thresholds
        # difficulty: boundary_precision_check/composite_score_threshold_inclusive_lower_bound
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 60, 10, 20)
        submitted = submit_assessment(a["id"])
        assert submitted["composite_score"] == pytest.approx(60.00, abs=0.001)
        assert submitted["classification"] == "L4"

    def test_composite_59_is_L3_below_boundary(self):
        """PRD §3.2: "otherwise at least 40 yields `L3`."

        Claim: adl=60, cog=11, med=20 → composite 59 → L3.
        # difficulty: boundary_precision_check/composite_score_threshold_inclusive_lower_bound
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 60, 11, 20)
        submitted = submit_assessment(a["id"])
        assert submitted["composite_score"] == pytest.approx(59.00, abs=0.001)
        assert submitted["classification"] == "L3"


# ===========================================================================
# Segregation of duties (PRD §3.2, §2.7 #6)
# ===========================================================================
class TestAssessmentSegregationOfDuties:

    def test_approve_with_same_id_as_assessor_rejected(self):
        """PRD §3.2: "Approval is a `Supervisor` action and is governed by
        segregation of duties: the supervisor's `X-User-ID` must not equal
        the assessment's `assessor_id`. The same constraint applies to
        rejection and to return-for-revision; in all three operations a
        same-identity attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Claim: drafter with id "X" submits; approve by id "X" → SoD.
        """
        elder = create_elder()
        nurse_x = make_nurse_headers("staff-x")
        sup_x = make_supervisor_headers("staff-x")
        a = draft_assessment(elder["id"], 80, 10, 20,
                             nurse_headers=nurse_x)
        submit_assessment(a["id"], nurse_headers=nurse_x)
        resp = api_client.approve_care_assessment(a["id"], sup_x)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_reject_with_same_id_as_assessor_rejected(self):
        """PRD §3.2: "The same constraint applies to rejection and to
        return-for-revision; in all three operations a same-identity
        attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Claim: reject by same id → ERR_SEGREGATION_OF_DUTIES.
        """
        elder = create_elder()
        nurse_x = make_nurse_headers("staff-x")
        sup_x = make_supervisor_headers("staff-x")
        a = draft_assessment(elder["id"], 80, 10, 20, nurse_headers=nurse_x)
        submit_assessment(a["id"], nurse_headers=nurse_x)
        resp = api_client.reject_care_assessment(a["id"], sup_x)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_return_for_revision_with_same_id_rejected(self):
        """PRD §3.2: "The same constraint applies to rejection and to
        return-for-revision; in all three operations a same-identity
        attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Claim: return-for-revision by same id → ERR_SEGREGATION_OF_DUTIES.
        """
        elder = create_elder()
        nurse_x = make_nurse_headers("staff-x")
        sup_x = make_supervisor_headers("staff-x")
        a = draft_assessment(elder["id"], 80, 10, 20, nurse_headers=nurse_x)
        submit_assessment(a["id"], nurse_headers=nurse_x)
        resp = api_client.return_care_assessment(a["id"], sup_x)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# Approval side effects (PRD §3.2)
# ===========================================================================
class TestApprovalSideEffects:

    def test_approval_updates_elder_current_care_level(self):
        """PRD §3.2: "On approval, the assessment moves from
        `PENDING_APPROVAL` to `APPROVED`, `approver_id` is recorded,
        `effective_from` is set to the current server time,
        `due_for_reassessment_at` is set to `effective_from` plus 90 days,
        and the elder's `current_care_level` is updated to the approved
        `classification`."

        Claim: after approve, GET /elders/{id}.current_care_level equals
        the new classification.
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 80, 10, 20)  # L3
        submit_assessment(a["id"])
        approved = approve_assessment(a["id"])
        assert approved["status"] == "APPROVED"
        assert approved["classification"] == "L3"
        refreshed = get_elder(elder["id"])
        assert refreshed["current_care_level"] == "L3"

    def test_approval_cascades_active_plan_to_under_review(self):
        """PRD §3.2 / §2.9: "If the elder has an `ACTIVE` `CarePlan` whose
        `care_level_snapshot` differs from the newly approved
        classification, that care plan is automatically advanced from
        `ACTIVE` to `UNDER_REVIEW` in the same transaction — the bridge
        between the assessment cycle and the plan-review cycle."

        Claim: approving an assessment with classification != snapshot
        moves the elder's ACTIVE plan to UNDER_REVIEW.
        # difficulty: transitive_cascade/assessment_approval_cascades_to_plan_review_and_audit
        """
        bundle = setup_admitted_elder_with_active_plan(80, 10, 20)
        plan_id = bundle["plan"]["id"]
        # New assessment with INTENSIVE (composite 105)
        new_a = draft_assessment(bundle["elder"]["id"], 20, 5, 40,
                                 nurse_headers=NURSE_ALT)
        submit_assessment(new_a["id"], nurse_headers=NURSE_ALT)
        approved = approve_assessment(new_a["id"])
        assert approved["classification"] == "INTENSIVE"
        # Plan must have cascaded.
        from test_helpers import api_client as _api
        plan_resp = _api.get_care_plan(plan_id, SUPERVISOR)
        plan = validate_success(plan_resp)
        assert plan["status"] == "UNDER_REVIEW", \
            "PRD §3.2 cascade — ACTIVE plan must move to UNDER_REVIEW"
        # Audit row recorded.
        rows = list_audit_logs(entity_type="CarePlan", entity_id=plan_id)
        flagged = find_audit_logs(rows, entity_type="CarePlan",
                                  entity_id=plan_id, action="REVIEW_FLAGGED")
        assert flagged, "PRD §2.8 — audit row with REVIEW_FLAGGED expected"


# ===========================================================================
# Revision cycle (PRD §3.2)
# ===========================================================================
class TestRevisionCycle:

    def test_return_for_revision_returns_to_draft(self):
        """PRD §3.2: "Return-for-revision is the cyclic transition that
        loops the assessment back to `DRAFT` so the original drafting
        Nurse can amend the sub-scores and resubmit."

        Claim: PENDING_APPROVAL → return-for-revision → DRAFT.
        # difficulty: non_linear_state_machine/care_assessment_revision_cycle
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 80, 10, 20)
        submit_assessment(a["id"])
        from test_helpers import api_client as _api
        resp = _api.return_care_assessment(a["id"], SUPERVISOR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DRAFT"

    def test_full_revision_cycle_keeps_same_assessment_id_until_approved(self):
        """PRD §3.2: "Return-for-revision is the cyclic transition that
        loops the assessment back to `DRAFT` so the original drafting
        Nurse can amend the sub-scores and resubmit."

        Claim: a full DRAFT→PENDING_APPROVAL→DRAFT→PENDING_APPROVAL→
        APPROVED cycle is honoured against the same assessment id.
        # difficulty: non_linear_state_machine/care_assessment_revision_cycle
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 80, 10, 20)
        a_id = a["id"]
        submit_assessment(a_id)
        from test_helpers import api_client as _api
        validate_success(
            _api.return_care_assessment(a_id, SUPERVISOR),
            expected_status=200,
        )
        # Resubmit + approve via SUPERVISOR_ALT to keep SoD clean.
        submit_assessment(a_id)
        approved = approve_assessment(a_id, supervisor_headers=SUPERVISOR_ALT)
        assert approved["id"] == a_id, \
            "revision must not mint a new assessment id"
        assert approved["status"] == "APPROVED"


# ===========================================================================
# Audit on approve / reject (PRD §3.2 + §2.8)
# ===========================================================================
class TestAssessmentAudit:

    def test_approve_writes_audit_row(self):
        """PRD §3.2: "Approval also writes an `AuditLog` row with
        `entity_type` of `CareAssessment` and `action` of `APPROVE`."

        Claim: an APPROVE audit row exists for the approved assessment.
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 80, 10, 20)
        submit_assessment(a["id"])
        approve_assessment(a["id"])
        rows = list_audit_logs(entity_type="CareAssessment",
                               entity_id=a["id"])
        approves = find_audit_logs(rows, entity_type="CareAssessment",
                                   entity_id=a["id"], action="APPROVE")
        assert approves, "PRD §3.2 — APPROVE audit row required"

    def test_reject_writes_audit_row(self):
        """PRD §3.2: "rejection writes the parallel row with `action` of
        `REJECT`."

        Claim: a REJECT audit row exists for the rejected assessment.
        """
        elder = create_elder()
        a = draft_assessment(elder["id"], 80, 10, 20)
        submit_assessment(a["id"])
        from test_helpers import api_client as _api
        validate_success(
            _api.reject_care_assessment(a["id"], SUPERVISOR),
            expected_status=200,
        )
        rows = list_audit_logs(entity_type="CareAssessment",
                               entity_id=a["id"])
        rejects = find_audit_logs(rows, entity_type="CareAssessment",
                                  entity_id=a["id"], action="REJECT")
        assert rejects, "PRD §3.2 — REJECT audit row required"
