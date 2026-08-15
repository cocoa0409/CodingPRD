"""Needs assessments, acuity variants, verification cascades, and OCC-guarded
plan creation (PRD §2.7, §3.3, §3.4)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    create_assessment_payload, create_plan_payload,
    register_client, create_staff_member, open_case,
    create_draft_assessment, submit_assessment, verify_assessment,
    create_verified_assessment, transition_case, transition_plan,
    create_plan_for_case, drive_case_to_planning, staff_headers, get_case,
)

ADMIN = TEST_USERS["center_admin_headers"]


class TestAssessmentInputValidation:
    def test_assessment_score_out_of_range(self):
        """PRD §3.3: "supplying `case_id` and five severity scores —
        `housing_score`, `employment_score`, `education_score`, `language_score`,
        and `health_score` — each an integer from 0 to 4."
        PRD §2.8: "7. **Structural well-formedness** — required fields present,
        enum membership, score ranges, note length, end-after-start ordering,
        funding shares summing to one hundred, an acyclic household graph, one
        draft assessment per case, no duplicate live enrollments, and
        non-overlapping report periods; the generic failure is
        `ERR_INVALID_REQUEST`".

        Design: Corner/entities/assessment_score_out_of_range
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        resp = api_client.create_assessment(
            create_assessment_payload(case["id"], housing_score=5), staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_second_draft_assessment_on_same_case(self):
        """PRD §3.3: "A case may hold at most one assessment in `DRAFT` at a time;
        a second draft attempt fails with `ERR_DRAFT_ASSESSMENT_EXISTS`."

        Design: Corner/validations/second_draft_assessment_on_same_case
        """
        mgr = create_staff_member()
        client = register_client()
        case = open_case(client, mgr)
        create_draft_assessment(case, mgr, score=1)
        resp = api_client.create_assessment(
            create_assessment_payload(case["id"], score=2), staff_headers(mgr))
        validate_error(resp, ApiErrorId.ERR_DRAFT_ASSESSMENT_EXISTS)


class TestSegregationOfDuties:
    def test_assessor_cannot_verify_own_assessment(self):
        """PRD §3.3: "the verifier must not be the creator — an `X-User-ID` equal
        to the assessment's `created_by_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/assessor_cannot_verify_own_assessment
        """
        mgr1 = create_staff_member(full_name="Mgr One")
        mgr2 = create_staff_member(full_name="Mgr Two")
        client = register_client()
        case = open_case(client, mgr1)
        asmt = create_draft_assessment(case, mgr1, score=2)
        submit_assessment(asmt, mgr1)

        resp = api_client.verify_assessment(asmt["id"], staff_headers(mgr1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        verified = validate_success(
            api_client.verify_assessment(asmt["id"], staff_headers(mgr2)))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_id"] == mgr2["id"]
        assert verified["created_by_id"] == mgr1["id"]


class TestAcuityDualVariant:
    def _setup_case_with_submitted_assessment(self):
        mgr1 = create_staff_member(full_name="Mgr One")
        mgr2 = create_staff_member(full_name="Mgr Two")
        client = register_client(full_name="Ana Client", household_size=2)
        case = open_case(client, mgr1)
        asmt = create_draft_assessment(
            case, mgr1, housing_score=3, employment_score=2, education_score=2,
            language_score=2, health_score=1)
        submit_assessment(asmt, mgr1)
        return mgr1, mgr2, client, case, asmt

    def test_rapid_variant_computed_at_submit(self):
        """PRD §3.3: "Each domain score is divided by four and multiplied by its
        weight — 0.30 for housing, 0.25 for employment, 0.15 for education, 0.20
        for language, 0.10 for health — and the five weighted contributions are
        summed into a base index between zero and one. The **rapid** variant, used
        at submission and whenever a not-yet-verified assessment is the latest,
        multiplies the base by one hundred and rounds half-up to one decimal
        place; it applies no multiplier and no bonuses."
        PRD §3.2: "the client's own `acuity_rapid` and `acuity_verified` begin
        null, populated later by assessments."

        Design: Difficulty/dual_variant_calc/acuity_rapid_vs_comprehensive_divergence
        """
        mgr1, _mgr2, _client, case, _asmt = self._setup_case_with_submitted_assessment()
        case_now = get_case(case["id"], mgr1)
        # base = 0.30*(3/4) + 0.25*(2/4) + 0.15*(2/4) + 0.20*(2/4) + 0.10*(1/4)
        #      = 0.55 -> rapid 55.0 (no multiplier, no bonuses).
        assert case_now["acuity_rapid"] == pytest.approx(55.0, abs=1e-6)
        assert case_now["acuity_verified"] is None, \
            "acuity_verified stays null until the first verification"

    def test_comprehensive_variant_diverges_at_verify(self):
        """PRD §3.3: "The **comprehensive** variant, used only on verified
        assessments, first multiplies the base by 1.25 and caps that product at
        one, then multiplies by one hundred and rounds half-up to one decimal
        place; it then adds ten points when the client's `household_size` is at
        least 5, and five more points when the client's `arrival_date` is set and
        lies no more than 90 days before the current logical clock."

        Design: Difficulty/dual_variant_calc/acuity_rapid_vs_comprehensive_divergence
        """
        mgr1, mgr2, _client, case, asmt = self._setup_case_with_submitted_assessment()
        verified = validate_success(
            api_client.verify_assessment(asmt["id"], staff_headers(mgr2)))
        assert verified["status"] == "VERIFIED"
        case_now = get_case(case["id"], mgr1)
        # 0.55 * 1.25 = 0.6875 -> 68.75 -> round_half_up 1dp = 68.8; household 2
        # (< 5) and arrival_date null add no bonus.
        assert case_now["acuity_verified"] == pytest.approx(68.8, abs=1e-6)
        assert case_now["acuity_rapid"] == pytest.approx(55.0, abs=1e-6)
        assert case_now["acuity_verified"] != case_now["acuity_rapid"], \
            "identical scores must diverge across the two variants"


class TestVerificationCascade:
    def _setup_active_case_with_second_assessment(self):
        """Case ACTIVE via assessment A1 (all 2s) with plan P ACTIVE based on A1;
        a second assessment A2 (all 4s) is SUBMITTED, awaiting verification."""
        mgr1 = create_staff_member(full_name="Mgr One")
        mgr2 = create_staff_member(full_name="Mgr Two")
        client = register_client(full_name="Ivan Client", household_size=2)
        case = open_case(client, mgr1)
        a1 = create_verified_assessment(case, mgr1, mgr2, score=2)
        transition_case(case["id"], "ASSESSED", mgr1)
        transition_case(case["id"], "PLANNING", mgr1)
        plan = create_plan_for_case(case["id"], mgr1, title="Plan P", budgeted_hours=12)
        plan = transition_plan(plan["id"], "ACTIVE", mgr1)
        assert plan["basis_assessment_id"] == a1["id"], "Setup: basis must pin A1"
        transition_case(case["id"], "ACTIVE", mgr1)
        a2 = create_draft_assessment(case, mgr1, score=4)
        submit_assessment(a2, mgr1)
        return mgr1, mgr2, client, case, a1, a2, plan

    def test_verify_supersedes_previous_verified_assessment(self):
        """PRD §3.3: "Verification stamps `verified_by_id` with the verifier's
        `X-User-ID`, then cascades: the case's previously `VERIFIED` assessment,
        if one exists, becomes `SUPERSEDED`".

        Design: Difficulty/transitive_cascade/assessment_verify_supersede_plan_revision_cascade
        """
        mgr1, mgr2, _client, _case, a1, a2, _plan = \
            self._setup_active_case_with_second_assessment()
        verified = validate_success(
            api_client.verify_assessment(a2["id"], staff_headers(mgr2)))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_id"] == mgr2["id"]
        old = validate_success(api_client.get_assessment(a1["id"], staff_headers(mgr1)))
        assert old["status"] == "SUPERSEDED", \
            "the previously VERIFIED assessment is superseded by the new verification"

    def test_supersession_forces_plan_back_to_draft_and_recomputes_acuity(self):
        """PRD §3.3: "every case plan of the case that is `ACTIVE` or `SUSPENDED`
        and whose `basis_assessment_id` names the just-superseded assessment is
        pushed back to `DRAFT` with its `plan_revision` incremented by 1; and both
        acuity indices are recomputed from the newly verified assessment — the
        comprehensive variant feeding `acuity_verified` and the rapid variant
        refreshing `acuity_rapid`."
        PRD §3.3: "The **comprehensive** variant, used only on verified
        assessments, first multiplies the base by 1.25 and caps that product at
        one, then multiplies by one hundred and rounds half-up to one decimal
        place".

        Design: Difficulty/transitive_cascade/assessment_verify_supersede_plan_revision_cascade
        """
        mgr1, mgr2, _client, case, _a1, a2, plan = \
            self._setup_active_case_with_second_assessment()
        validate_success(api_client.verify_assessment(a2["id"], staff_headers(mgr2)))
        plan_now = validate_success(api_client.get_plan(plan["id"], staff_headers(mgr1)))
        assert plan_now["status"] == "DRAFT", "basis supersession forces the plan to DRAFT"
        assert plan_now["plan_revision"] == 2, "the auto-revise increments plan_revision by 1"
        case_now = get_case(case["id"], mgr1)
        # All-4 scores: base 1.0 * 1.25 = 1.25 capped at 1.0 -> 100.0, no bonuses.
        assert case_now["acuity_verified"] == pytest.approx(100.0, abs=1e-6)


class TestPlanCreationOCC:
    def test_plan_create_occ_stale_version_conflict(self):
        """PRD §2.7: "That request must carry `expected_case_version`, a
        non-optional field holding the `version` of the parent case as the client
        last observed it. If the case's current `version` no longer equals
        `expected_case_version` — because another writer has advanced the case
        since the client read it — the creation is rejected with
        `ERR_STALE_CASE_VERSION` (HTTP 412), forcing the client to re-read the
        case before superseding a plan it never saw."
        PRD §3.4: "Creation supersedes the case's current plan — whether that plan
        sits in `DRAFT`, `ACTIVE`, or `SUSPENDED`, it becomes `SUPERSEDED` — and
        increments the case's `version` by 1."

        Design: Corner/cross_cutting_layers/plan_create_occ_stale_version_conflict
        """
        mgr1 = create_staff_member(full_name="Mgr One")
        mgr2 = create_staff_member(full_name="Mgr Two")
        client = register_client()
        case = open_case(client, mgr1)
        create_verified_assessment(case, mgr1, mgr2, score=1)
        transition_case(case["id"], "ASSESSED", mgr1)
        case_planning = transition_case(case["id"], "PLANNING", mgr1)
        observed_version = case_planning["version"]

        plan_a = validate_success(api_client.create_plan(
            case["id"], create_plan_payload(
                title="Plan A", budgeted_hours=5,
                expected_case_version=observed_version),
            staff_headers(mgr1)), expected_status=201)

        # Replaying the same observed version must now be stale.
        resp = api_client.create_plan(case["id"], create_plan_payload(
            title="Plan B", budgeted_hours=6,
            expected_case_version=observed_version), staff_headers(mgr1))
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

        case_now = get_case(case["id"], mgr1)
        assert case_now["version"] == observed_version + 1, \
            "the successful create advanced the case version by exactly 1"

        plan_b = validate_success(api_client.create_plan(
            case["id"], create_plan_payload(
                title="Plan B", budgeted_hours=6,
                expected_case_version=case_now["version"]),
            staff_headers(mgr1)), expected_status=201)
        assert plan_b["status"] == "DRAFT"
        plan_a_now = validate_success(api_client.get_plan(plan_a["id"], staff_headers(mgr1)))
        assert plan_a_now["status"] == "SUPERSEDED", \
            "the fresh-version create supersedes the previous plan"
