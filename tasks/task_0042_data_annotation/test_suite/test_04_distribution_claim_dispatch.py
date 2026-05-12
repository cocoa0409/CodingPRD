"""Distribution: claiming, dispatching, tier checks, suspension gating,
distribution-mode permission, and concurrent-claim races. Covers PRD §3.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    claim_package,
    create_annotator,
    create_expert_annotator,
    create_junior_annotator,
    create_senior_annotator,
    dispatch_package_payload,
    make_annotator_headers,
    make_project_manager_headers,
    re_evaluate,
    run_race,
    setup_open_project,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# =========================================================================
# §3.3 -- distribution_mode permission
# =========================================================================
class TestDistributionMode:

    def test_grab_rejected_in_dispatch_only_project(self, api):
        """PRD §3.3: 'A claim attempt against a project whose mode is
        DISPATCH is rejected with ERR_GRAB_NOT_ALLOWED.'

        Claim: claim on DISPATCH-only project -> ERR_GRAB_NOT_ALLOWED.
        """
        project, packages = setup_open_project(distribution_mode="DISPATCH")
        annotator = create_junior_annotator()
        res = api.claim_package(
            packages[0]["id"], make_annotator_headers(annotator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_GRAB_NOT_ALLOWED.value)

    def test_dispatch_rejected_in_grab_only_project(
        self, api, project_manager_headers,
    ):
        """PRD §3.3: 'a dispatch attempt against a project whose mode is
        GRAB is rejected with ERR_DISPATCH_NOT_ALLOWED.'

        Claim: dispatch on GRAB-only project -> ERR_DISPATCH_NOT_ALLOWED.
        """
        project, packages = setup_open_project(distribution_mode="GRAB")
        annotator = create_junior_annotator()
        res = api.dispatch_package(
            packages[0]["id"],
            dispatch_package_payload(annotator_id=annotator["id"]),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_DISPATCH_NOT_ALLOWED.value)

    def test_hybrid_allows_both_paths(
        self, api, project_manager_headers,
    ):
        """PRD §3.3: 'A HYBRID project allows both.'

        Claim: HYBRID project accepts both /claim and /dispatch.
        """
        project, packages = setup_open_project(
            distribution_mode="HYBRID", total_item_count=20, package_size=10,
        )
        a1 = create_junior_annotator()
        a2 = create_junior_annotator()
        # Claim on first package by a1.
        r1 = api.claim_package(
            packages[0]["id"], make_annotator_headers(a1["id"]),
        )
        validate_success(r1)
        # Dispatch second package to a2.
        r2 = api.dispatch_package(
            packages[1]["id"],
            dispatch_package_payload(annotator_id=a2["id"]),
            project_manager_headers,
        )
        validate_success(r2)


# =========================================================================
# §3.3 -- Tier sufficiency
# =========================================================================
class TestTierSufficiency:

    def test_junior_cannot_claim_senior_required_package(self, api):
        """PRD §3.2: 'An annotator may take a package only when their
        tier rank is at least the package's required tier rank.'
        PRD §3.2: 'Failures of this comparison are rejected with
        ERR_TIER_INSUFFICIENT.'

        Claim: JUNIOR claiming a SENIOR-required (MEDIUM) package -> 403
        ERR_TIER_INSUFFICIENT.
        """
        project, packages = setup_open_project(difficulty="MEDIUM")
        junior = create_junior_annotator()
        res = api.claim_package(
            packages[0]["id"], make_annotator_headers(junior["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TIER_INSUFFICIENT.value)

    def test_senior_can_claim_junior_required_package(self, api):
        """PRD §3.2: 'a SENIOR may take a package marked JUNIOR or
        SENIOR but not EXPERT'.

        Claim: SENIOR claiming an EASY (JUNIOR-required) package succeeds.
        """
        project, packages = setup_open_project(difficulty="EASY")
        senior = create_senior_annotator()
        res = api.claim_package(
            packages[0]["id"], make_annotator_headers(senior["id"]),
        )
        validate_success(res)

    def test_senior_cannot_claim_expert_required_package(self, api):
        """PRD §3.2: 'a SENIOR may take a package marked JUNIOR or
        SENIOR but not EXPERT'.

        Claim: SENIOR on a HARD (EXPERT-required) package -> 403
        ERR_TIER_INSUFFICIENT.
        """
        project, packages = setup_open_project(difficulty="HARD")
        senior = create_senior_annotator()
        res = api.claim_package(
            packages[0]["id"], make_annotator_headers(senior["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TIER_INSUFFICIENT.value)

    def test_expert_can_claim_any_tier(self, api):
        """PRD §3.2: 'an EXPERT may take any package'.

        Claim: EXPERT successfully claims a HARD package.
        """
        project, packages = setup_open_project(difficulty="HARD")
        expert = create_expert_annotator()
        res = api.claim_package(
            packages[0]["id"], make_annotator_headers(expert["id"]),
        )
        validate_success(res)


# =========================================================================
# §3.3 -- Project must be OPEN
# =========================================================================
class TestProjectStateGate:

    def test_claim_on_draft_project_rejected(
        self, api, project_manager_headers,
    ):
        """PRD §3.3: 'The project must be in OPEN status (else
        ERR_PROJECT_NOT_OPEN).'

        Claim: claim on a DRAFT project -> 409 ERR_PROJECT_NOT_OPEN.
        """
        from test_helpers import (
            create_draft_project,
            split_packages_for_project,
            add_n_golden_samples,
        )
        proj = create_draft_project()
        # Split packages so the package id resolves; project remains DRAFT.
        pkgs = split_packages_for_project(proj["id"], 10)
        annotator = create_junior_annotator()
        res = api.claim_package(
            pkgs[0]["id"], make_annotator_headers(annotator["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_OPEN.value)


# =========================================================================
# §3.3 -- Suspension gating
# =========================================================================
class TestSuspensionGating:

    def test_suspended_annotator_cannot_claim(self, api):
        """PRD §3.3: 'The acting annotator ... must be in ACTIVE status
        (else ERR_ANNOTATOR_SUSPENDED)'.

        Claim: SUSPENDED annotator claiming -> 403 ERR_ANNOTATOR_SUSPENDED.
        """
        from test_helpers import (
            setup_annotator_with_pass_fail_history,
        )
        project, packages = setup_open_project(difficulty="EASY")
        senior = create_senior_annotator()
        seq = (["PASS"] * 14) + (["FAIL"] * 7)
        setup_annotator_with_pass_fail_history(
            annotator=senior, pass_then_fail=seq,
        )
        re_evaluate(senior["id"])
        # Now suspended.
        res = api.claim_package(
            packages[0]["id"], make_annotator_headers(senior["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ANNOTATOR_SUSPENDED.value)


# =========================================================================
# §3.3 -- Single-occupancy: ERR_PACKAGE_ALREADY_TAKEN
# =========================================================================
class TestPackageAlreadyTaken:

    def test_second_claim_after_first_succeeded(self, api):
        """PRD §3.3: 'The package itself must currently have a null
        assigned_annotator_id; if a competing writer has already filled
        it, the request is rejected with ERR_PACKAGE_ALREADY_TAKEN.'

        Claim: serial second claim on same package -> 409
        ERR_PACKAGE_ALREADY_TAKEN.
        """
        project, packages = setup_open_project()
        a1 = create_junior_annotator()
        a2 = create_junior_annotator()
        r1 = api.claim_package(
            packages[0]["id"], make_annotator_headers(a1["id"]),
        )
        validate_success(r1)
        r2 = api.claim_package(
            packages[0]["id"], make_annotator_headers(a2["id"]),
        )
        validate_error(r2, ApiErrorId.ERR_PACKAGE_ALREADY_TAKEN.value)

    def test_concurrent_claims_one_wins_one_loses(self, api):
        """PRD §3.3: 'When two annotators race to claim the same POOL
        package simultaneously, the platform's serialisation guarantee
        is first-writer-wins on assigned_annotator_id: at most one writer
        becomes the assignee, and the loser's request aborts with
        ERR_PACKAGE_ALREADY_TAKEN and HTTP status 409.'

        Claim: two concurrent claims -> exactly one success, one loser.
        """
        project, packages = setup_open_project()
        a1 = create_junior_annotator()
        a2 = create_junior_annotator()
        pkg_id = packages[0]["id"]

        results = run_race(
            lambda: api.claim_package(
                pkg_id, make_annotator_headers(a1["id"]),
            ),
            lambda: api.claim_package(
                pkg_id, make_annotator_headers(a2["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser's error_id is ERR_PACKAGE_ALREADY_TAKEN per PRD.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_PACKAGE_ALREADY_TAKEN.value)


# =========================================================================
# §3.3 -- claim side effects
# =========================================================================
class TestClaimSideEffects:

    def test_claim_sets_assigned_and_deadline(self, api):
        """PRD §3.3: 'When the transition commits, the package's
        assigned_annotator_id is set to the acting (or dispatched)
        annotator's id, claimed_at is set to the current server time,
        and deadline_at is set to claimed_at plus the project's
        timeout_seconds.'

        Claim: post-claim package has matching assigned_annotator_id,
        non-null claimed_at and deadline_at.
        """
        project, packages = setup_open_project(timeout_seconds=300)
        annotator = create_junior_annotator()
        res = api.claim_package(
            packages[0]["id"], make_annotator_headers(annotator["id"]),
        )
        data = validate_success(res)
        assert data["assigned_annotator_id"] == annotator["id"]
        assert data["claimed_at"] is not None
        assert data["deadline_at"] is not None
        assert data["status"] == "IN_PROGRESS"
