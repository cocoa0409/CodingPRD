"""Certification decisions with segregation of duties, finding fix/verify
gates, and the cross-round remediation cycle (PRD §3.5, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_build,
    create_candidate_build,
    create_submission_package,
    decide_package,
    get_build,
    get_checklist_id_for_package,
    get_finding,
    get_package,
    make_platform_reviewer_headers,
    review_package,
    set_clock,
    setup_rejected_package_with_finding,
    setup_submittable_package,
    submit_package,
    transition_build,
    transition_finding,
    verify_checklist_pass_sequence,
    validate_error,
)

PR_HEADERS = TEST_USERS["platform_reviewer_headers"]
MONDAY_09 = "2026-08-03T09:00:00Z"


class TestCertDecisionSegregation:
    def test_decider_must_differ_from_submitter(self, api):
        """PRD §3.5: "Segregation of duties binds the decision — the deciding
        `X-User-ID` must differ from `submitted_by_user_id`, otherwise
        `ERR_SELF_CERT_DECISION` (HTTP 403) — and the decider is recorded as
        `decided_by_user_id`."
        PRD §3.5: "Approval additionally consumes the referenced build
        (`CANDIDATE` → `CONSUMED`) and runs the plan-unlock check."

        Design: Corner/rbac/cert_decision_same_user_rejected
        """
        set_clock(MONDAY_09)
        ctx = setup_submittable_package(title_code="RB-SOD",
                                        cert_budget_total_cents=1_000_000)
        submit_package(ctx["package"]["id"], submitter_user_id="cl-1")
        review_package(ctx["package"]["id"], reviewer_user_id="pr-0")
        # A decider whose X-User-ID equals the submitter's is rejected.
        resp = api.transition_submission_package(
            ctx["package"]["id"], {"to_status": "APPROVED"},
            make_platform_reviewer_headers("cl-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_CERT_DECISION)
        assert get_package(ctx["package"]["id"])["status"] == "IN_REVIEW"
        # A different PlatformReviewer user decides the same package.
        package = decide_package(ctx["package"]["id"], "APPROVED", "pr-9")
        assert package["status"] == "APPROVED"
        assert package["decided_by_user_id"] == "pr-9"
        assert get_build(ctx["build"]["id"])["status"] == "CONSUMED"


class TestFindingFixGates:
    def test_fix_build_must_be_strictly_newer(self, api):
        """PRD §3.7: "the build must belong to the package's title
        (`ERR_BUILD_TITLE_MISMATCH`), target the package's platform
        (`ERR_BUILD_PLATFORM_MISMATCH`), have been created strictly after the
        rejected package's build (`ERR_FINDING_BUILD_NOT_NEWER`, HTTP 422),
        and be `TEST_PASSED` or `CANDIDATE` (`ERR_FIX_BUILD_NOT_QUALIFIED`)."

        Design: Corner/validations/finding_fix_requires_strictly_newer_build
        """
        set_clock(MONDAY_09)
        ctx = setup_rejected_package_with_finding(title_code="VAL-NWB")
        # The rejected package's own build is, trivially, not strictly newer
        # than itself.
        resp = api.transition_finding(
            ctx["finding"]["id"],
            {"to_status": "FIXED_IN_BUILD", "build_id": ctx["build"]["id"]},
            TEST_USERS["certification_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FINDING_BUILD_NOT_NEWER)
        assert get_finding(ctx["finding"]["id"])["status"] == "OPEN"

    def test_fix_build_must_be_test_qualified(self, api):
        """PRD §3.7: "the build must belong to the package's title
        (`ERR_BUILD_TITLE_MISMATCH`), target the package's platform
        (`ERR_BUILD_PLATFORM_MISMATCH`), have been created strictly after the
        rejected package's build (`ERR_FINDING_BUILD_NOT_NEWER`, HTTP 422),
        and be `TEST_PASSED` or `CANDIDATE` (`ERR_FIX_BUILD_NOT_QUALIFIED`)."

        Design: Corner/state_machines/fix_build_must_be_test_qualified
        """
        set_clock(MONDAY_09)
        ctx = setup_rejected_package_with_finding(title_code="SM2-FBQ")
        # A strictly newer build that is still in testing.
        set_clock("2026-08-03T11:00:00Z")
        build2 = create_build(ctx["title"]["id"], "PS5", "1.0.1")
        transition_build(build2["id"], "IN_TEST")
        resp = api.transition_finding(
            ctx["finding"]["id"],
            {"to_status": "FIXED_IN_BUILD", "build_id": build2["id"]},
            TEST_USERS["certification_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FIX_BUILD_NOT_QUALIFIED)
        finding = get_finding(ctx["finding"]["id"])
        assert finding["status"] == "OPEN"
        assert finding["fixed_in_build_id"] is None


class TestFindingVerification:
    def test_failed_verification_reopens_finding(self, api):
        """PRD §3.7: "When `passed` is false, verification failure reopens the
        finding `FIXED_IN_BUILD` → `OPEN`, increments `reopen_count`, and
        clears `fixed_in_build_id`."

        Design: Corner/state_machines/finding_verification_failure_reopens
        """
        set_clock(MONDAY_09)
        ctx = setup_rejected_package_with_finding(title_code="SM-FND")
        set_clock("2026-08-03T11:00:00Z")
        build2 = create_candidate_build(ctx["title"]["id"], "PS5", "1.0.1")
        finding = transition_finding(
            ctx["finding"]["id"], "FIXED_IN_BUILD",
            headers=TEST_USERS["certification_lead_headers"],
            build_id=build2["id"],
        )
        assert finding["status"] == "FIXED_IN_BUILD"
        finding = transition_finding(
            finding["id"], "OPEN", headers=PR_HEADERS, passed=False
        )
        assert finding["status"] == "OPEN"
        assert finding["reopen_count"] == 1
        assert finding["fixed_in_build_id"] is None
        # The owning package stays REJECTED while the finding is open.
        assert get_package(ctx["package"]["id"])["status"] == "REJECTED"


class TestRemediationRoundCycle:
    def _setup_round2_with_fixed_finding(self):
        """Round-2 package assembled on a newer CANDIDATE build; the round-1
        CATEGORY_A finding marked FIXED_IN_BUILD on that build."""
        set_clock(MONDAY_09)
        ctx = setup_rejected_package_with_finding(title_code="CYC-PKG")
        set_clock("2026-08-03T11:00:00Z")
        build2 = create_candidate_build(ctx["title"]["id"], "PS5", "1.0.1")
        pkg2 = create_submission_package(
            ctx["title"]["id"], "PS5", build2["id"], ctx["plan"]["id"]
        )
        transition_finding(
            ctx["finding"]["id"], "FIXED_IN_BUILD",
            headers=TEST_USERS["certification_lead_headers"],
            build_id=build2["id"],
        )
        verify_checklist_pass_sequence(
            get_checklist_id_for_package(pkg2["id"]), "PS5"
        )
        set_clock("2026-08-03T12:00:00Z")
        return ctx, pkg2

    def test_open_category_a_findings_gate_next_round_submit(self, api):
        """PRD §3.5: "No rejected package for the same title and platform may
        still carry a `CATEGORY_A` finding in `OPEN` or `FIXED_IN_BUILD`
        (`ERR_OPEN_CATEGORY_A_FINDINGS`)."
        PRD §3.7: "when `passed` is true the finding moves `FIXED_IN_BUILD` →
        `VERIFIED`, and when that was the owning package's last non-verified
        finding — with at least one finding existing — the system closes the
        package `REJECTED` → `CLOSED`."

        Design: Difficulty/non_linear_state_machine/submission_package_remediation_round_cycle
        """
        ctx, pkg2 = self._setup_round2_with_fixed_finding()
        # FIXED_IN_BUILD is not yet VERIFIED, so the gate still blocks.
        resp = api.transition_submission_package(
            pkg2["id"], {"to_status": "SUBMITTED"},
            TEST_USERS["certification_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_CATEGORY_A_FINDINGS)
        transition_finding(ctx["finding"]["id"], "VERIFIED",
                           headers=PR_HEADERS, passed=True)
        # Verifying the last non-verified finding auto-closes round 1.
        assert get_package(ctx["package"]["id"])["status"] == "CLOSED"

    def test_remediation_round_two_submits_at_half_base_fee(self, api):
        """PRD §3.7: "each new package for the same title and platform
        increments `round`, and the round drives the resubmission fee tier of
        §3.5 — second rounds bill at half the base fee, third and later rounds
        at a quarter."
        PRD §3.5: "No rejected package for the same title and platform may
        still carry a `CATEGORY_A` finding in `OPEN` or `FIXED_IN_BUILD`
        (`ERR_OPEN_CATEGORY_A_FINDINGS`)."

        Design: Difficulty/non_linear_state_machine/submission_package_remediation_round_cycle
        """
        ctx, pkg2 = self._setup_round2_with_fixed_finding()
        assert pkg2["round"] == 2
        resp = api.transition_submission_package(
            pkg2["id"], {"to_status": "SUBMITTED"},
            TEST_USERS["certification_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_CATEGORY_A_FINDINGS)
        transition_finding(ctx["finding"]["id"], "VERIFIED",
                           headers=PR_HEADERS, passed=True)
        pkg2 = submit_package(pkg2["id"])
        assert pkg2["status"] == "SUBMITTED"
        assert pkg2["fee_cents"] == 60000  # 120000 x 0.50, weekday
