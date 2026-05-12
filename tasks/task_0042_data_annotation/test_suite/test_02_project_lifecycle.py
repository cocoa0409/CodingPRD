"""Project creation, edit, and lifecycle (DRAFT -> OPEN -> CLOSED ->
ARCHIVED). Covers PRD §3.1, §3.9, §2.5 (optimistic concurrency)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_n_golden_samples,
    archive_project,
    assert_annotation_project,
    close_project,
    create_draft_project,
    create_golden_sample_payload,
    create_project_payload,
    open_project,
    patch_project_payload,
    setup_open_project,
    split_packages_for_project,
    TEST_USERS,
    validate_error,
    validate_success,
)


# =========================================================================
# §3.1 -- Project creation: parameter ranges
# =========================================================================
class TestProjectCreate:

    def test_create_in_draft(self, api, project_manager_headers):
        """PRD §3.1: 'The newly created project enters DRAFT status with
        golden_sample_count set to zero.'

        Claim: POST /annotation-projects 201 returns DRAFT with
        golden_sample_count == 0.
        """
        res = api.create_project(
            create_project_payload(), project_manager_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_annotation_project(data)
        assert data["status"] == "DRAFT"
        assert data["golden_sample_count"] == 0

    def test_default_timeout_seconds_when_omitted(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'An optional timeout_seconds controls the per-package
        deadline; when omitted it defaults to 86400 seconds (24 hours).'

        Claim: project created without timeout_seconds has timeout_seconds
        == 86400.
        """
        payload = create_project_payload()
        payload.pop("timeout_seconds", None)
        res = api.create_project(payload, project_manager_headers)
        data = validate_success(res, expected_status=201)
        assert data["timeout_seconds"] == 86400

    @pytest.mark.parametrize("bad_size", [9, 501, 0, -1])
    def test_invalid_package_size_rejected(
        self, api, project_manager_headers, bad_size,
    ):
        """PRD §3.1: 'the package_size of items per TaskPackage (an
        integer between 10 and 500 inclusive)'.

        Claim: package_size outside [10, 500] -> ERR_INVALID_PARAMETER / 400.
        """
        res = api.create_project(
            create_project_payload(package_size=bad_size),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PARAMETER.value)

    @pytest.mark.parametrize("bad_target", [0, 1.01, -0.1])
    def test_invalid_pass_rate_target_rejected(
        self, api, project_manager_headers, bad_target,
    ):
        """PRD §3.1: 'the pass_rate_target (greater than zero and at most 1)
        used for bonus and penalty computation.'

        Claim: pass_rate_target outside (0, 1] -> ERR_INVALID_PARAMETER.
        """
        res = api.create_project(
            create_project_payload(pass_rate_target=bad_target),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PARAMETER.value)

    def test_invalid_timeout_seconds_below_minimum(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'when supplied it must be at least 60 seconds'.

        Claim: timeout_seconds < 60 -> ERR_INVALID_PARAMETER / 400.
        """
        res = api.create_project(
            create_project_payload(timeout_seconds=59),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PARAMETER.value)

    def test_package_size_boundary_inclusive_ten(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'package_size of items per TaskPackage (an integer
        between 10 and 500 inclusive)'.

        Claim: package_size=10 succeeds (lower inclusive boundary).
        """
        res = api.create_project(
            create_project_payload(package_size=10),
            project_manager_headers,
        )
        validate_success(res, expected_status=201)

    def test_package_size_boundary_inclusive_500(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'package_size of items per TaskPackage (an integer
        between 10 and 500 inclusive)'.

        Claim: package_size=500 succeeds (upper inclusive boundary).
        """
        res = api.create_project(
            create_project_payload(package_size=500),
            project_manager_headers,
        )
        validate_success(res, expected_status=201)


# =========================================================================
# §3.1 -- /open preconditions
# =========================================================================
class TestOpenPreconditions:

    def test_open_without_packages_rejected(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'at least one TaskPackage must already exist for the
        project (else ERR_NO_TASK_PACKAGES).'

        Claim: open with five goldens but zero packages ->
        ERR_NO_TASK_PACKAGES / 409.
        """
        proj = create_draft_project(pm_headers=project_manager_headers)
        add_n_golden_samples(proj["id"], 5, pm_headers=project_manager_headers)
        res = api.open_project(proj["id"], project_manager_headers)
        validate_error(res, ApiErrorId.ERR_NO_TASK_PACKAGES.value)

    def test_open_with_insufficient_goldens(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'the count of GoldenSample rows attached to the
        project must be at least 5 (else ERR_GOLDEN_SAMPLES_INSUFFICIENT)'.

        Claim: open with 4 goldens -> ERR_GOLDEN_SAMPLES_INSUFFICIENT.
        """
        proj = create_draft_project(pm_headers=project_manager_headers)
        add_n_golden_samples(proj["id"], 4, pm_headers=project_manager_headers)
        split_packages_for_project(proj["id"], 10, pm_headers=project_manager_headers)
        res = api.open_project(proj["id"], project_manager_headers)
        validate_error(
            res, ApiErrorId.ERR_GOLDEN_SAMPLES_INSUFFICIENT.value,
        )

    def test_open_with_exactly_five_goldens_succeeds(
        self, api, project_manager_headers,
    ):
        """PRD §2.10: 'The minimum number of golden samples required
        before a project can be opened is 5'.

        Claim: open with exactly 5 goldens succeeds (inclusive boundary).
        """
        proj = create_draft_project(pm_headers=project_manager_headers)
        add_n_golden_samples(proj["id"], 5, pm_headers=project_manager_headers)
        split_packages_for_project(proj["id"], 10, pm_headers=project_manager_headers)
        res = api.open_project(proj["id"], project_manager_headers)
        data = validate_success(res)
        assert data["status"] == "OPEN"

    def test_open_initialises_tier_required(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'When the transition commits, every TaskPackage on
        the project has its tier_required initialised -- EASY projects
        mark their packages as requiring JUNIOR, MEDIUM projects as
        requiring SENIOR, and HARD projects as requiring EXPERT.'

        Claim: opening a HARD project sets tier_required = EXPERT on each
        package.
        """
        project, packages = setup_open_project(difficulty="HARD")
        assert all(p["tier_required"] == "EXPERT" for p in packages)


# =========================================================================
# §3.1 -- DRAFT-only edit + version conflict
# =========================================================================
class TestProjectEdit:

    def test_patch_outside_draft_rejected(
        self, api, project_manager_headers,
    ):
        """PRD §3.1: 'Any edit attempt outside DRAFT is rejected with
        ERR_PROJECT_NOT_DRAFT.'

        Claim: PATCH on an OPEN project -> ERR_PROJECT_NOT_DRAFT / 409.
        """
        project, _ = setup_open_project()
        res = api.patch_project(
            project["id"],
            patch_project_payload(version=project["version"], unit_price_cents=200),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_DRAFT.value)

    def test_version_conflict_on_patch(
        self, api, project_manager_headers,
    ):
        """PRD §2.5: 'When a request body supplies a version value, the
        server compares it against the current version of the target
        resource; if the two do not match, the request is rejected with
        ERR_VERSION_CONFLICT and no mutation is applied.'

        Claim: PATCH with stale version -> ERR_VERSION_CONFLICT / 409.
        """
        proj = create_draft_project(pm_headers=project_manager_headers)
        # First successful PATCH bumps version.
        first = api.patch_project(
            proj["id"],
            patch_project_payload(version=proj["version"], unit_price_cents=200),
            project_manager_headers,
        )
        validate_success(first)
        # Second PATCH using the OLD version -> conflict.
        res = api.patch_project(
            proj["id"],
            patch_project_payload(version=proj["version"], unit_price_cents=300),
            project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_version_omitted_skips_check(
        self, api, project_manager_headers,
    ):
        """PRD §2.5: 'When a request body omits version or sends an
        explicit JSON null, the server skips the version check and
        proceeds with the update.'

        Claim: PATCH without version succeeds and bumps version by 1.
        """
        proj = create_draft_project(pm_headers=project_manager_headers)
        v0 = proj["version"]
        res = api.patch_project(
            proj["id"], {"unit_price_cents": 250},
            project_manager_headers,
        )
        data = validate_success(res)
        assert data["version"] == v0 + 1


# =========================================================================
# §3.9 -- Close and archive
# =========================================================================
class TestCloseArchive:

    def test_close_blocked_with_in_progress_package(
        self, api, project_manager_headers,
    ):
        """PRD §3.9: 'A close attempt with any such package outstanding
        is rejected with ERR_PACKAGES_STILL_OPEN.'

        Claim: close while a package is IN_PROGRESS -> ERR_PACKAGES_STILL_OPEN.
        """
        from test_helpers import (
            create_junior_annotator,
            claim_package,
        )
        project, packages = setup_open_project()
        annotator = create_junior_annotator()
        claim_package(packages[0]["id"], annotator["id"])
        res = api.close_project(project["id"], project_manager_headers)
        validate_error(res, ApiErrorId.ERR_PACKAGES_STILL_OPEN.value)

    def test_archive_blocked_with_withheld_salary(
        self, api, project_manager_headers,
    ):
        """PRD §3.9: 'A CLOSED project may be archived only after every
        SalaryLedgerEntry referencing one of its packages is in RELEASED
        settlement state; an archive attempt that finds any entry still
        WITHHELD is rejected with ERR_SALARY_NOT_FINALIZED.'

        Claim: archive while a piece-rate entry is still WITHHELD ->
        ERR_SALARY_NOT_FINALIZED.
        """
        from test_helpers import (
            setup_in_progress_package,
            submit_labels,
            start_inspection,
            finalize_inspection,
            close_project as do_close,
        )
        state = setup_in_progress_package()
        pkg = state["package"]
        annotator = state["annotator"]
        submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
        insp = start_inspection(pkg["id"])
        finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=0)
        do_close(state["project"]["id"])
        res = api.archive_project(
            state["project"]["id"], project_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_SALARY_NOT_FINALIZED.value)
