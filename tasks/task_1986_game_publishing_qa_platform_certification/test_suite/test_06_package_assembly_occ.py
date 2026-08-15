"""Submission package assembly: build/plan gates, platform referential
checks, supersession of an ASSEMBLING sibling, OCC on the title version,
immediate consistency, and the findings filing window."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_title,
    assert_submission_package,
    create_approved_plan,
    create_candidate_build,
    create_finding_payload,
    create_submission_package,
    create_submission_package_payload,
    create_title,
    create_vendor,
    get_checklist,
    get_checklist_id_for_package,
    get_package,
    get_plan,
    get_title,
    transition_build,
    create_build,
    validate_error,
    validate_success,
)

CL_HEADERS = TEST_USERS["certification_lead_headers"]
PR_HEADERS = TEST_USERS["platform_reviewer_headers"]


def _assembly_prereqs(title_code, title_platforms=("PS5",), plan_platform="PS5",
                      build_platform="PS5"):
    """Title IN_DEVELOPMENT + ACTIVE vendor + APPROVED plan (one covered
    cert-blocker entry) + CANDIDATE build — the assembly preconditions of
    PRD §3.5 without the readiness tracks."""
    title = create_title(title_code=title_code,
                         platform_codes=list(title_platforms),
                         cert_budget_total_cents=500000)
    advance_title(title["id"], "IN_DEVELOPMENT")
    vendor = create_vendor()
    plan = create_approved_plan(title["id"], vendor["id"], plan_platform)
    build = create_candidate_build(title["id"], build_platform)
    return title, vendor, plan, build


class TestPackageAssemblyGates:
    def test_package_create_requires_candidate_build_rejection_leg(self, api):
        """PRD §3.5: "the build belongs to the title
        (`ERR_BUILD_TITLE_MISMATCH`), targets the same platform
        (`ERR_BUILD_PLATFORM_MISMATCH`), and is currently `CANDIDATE`
        (`ERR_BUILD_NOT_CANDIDATE`)"

        Design: Difficulty/cross_entity_state_dependency/package_create_requires_candidate_build
        """
        title = create_title(title_code="XDEP-BLD", cert_budget_total_cents=500000)
        advance_title(title["id"], "IN_DEVELOPMENT")
        vendor = create_vendor()
        plan = create_approved_plan(title["id"], vendor["id"], "PS5")
        build = create_build(title["id"], "PS5")
        transition_build(build["id"], "IN_TEST")
        transition_build(build["id"], "TEST_PASSED")
        resp = api.create_submission_package(
            title["id"],
            create_submission_package_payload(
                "PS5", build["id"], plan["id"], get_title(title["id"])["version"]
            ),
            CL_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_BUILD_NOT_CANDIDATE)

    def test_package_create_succeeds_after_build_promotion(self, api):
        """PRD §3.5: "The referenced test plan moves `APPROVED` → `LOCKED`
        (or remains `LOCKED`)."
        PRD §3.5: "the build belongs to the title
        (`ERR_BUILD_TITLE_MISMATCH`), targets the same platform
        (`ERR_BUILD_PLATFORM_MISMATCH`), and is currently `CANDIDATE`
        (`ERR_BUILD_NOT_CANDIDATE`)"

        Design: Difficulty/cross_entity_state_dependency/package_create_requires_candidate_build
        """
        title = create_title(title_code="XDEP-BLD", cert_budget_total_cents=500000)
        advance_title(title["id"], "IN_DEVELOPMENT")
        vendor = create_vendor()
        plan = create_approved_plan(title["id"], vendor["id"], "PS5")
        build = create_build(title["id"], "PS5")
        transition_build(build["id"], "IN_TEST")
        transition_build(build["id"], "TEST_PASSED")
        transition_build(build["id"], "CANDIDATE")
        package = create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        assert package["status"] == "ASSEMBLING"
        assert package["round"] == 1
        assert get_plan(plan["id"])["status"] == "LOCKED"

    def test_package_create_with_other_platform_build_rejected(self, api):
        """PRD §3.5: "the build belongs to the title
        (`ERR_BUILD_TITLE_MISMATCH`), targets the same platform
        (`ERR_BUILD_PLATFORM_MISMATCH`), and is currently `CANDIDATE`
        (`ERR_BUILD_NOT_CANDIDATE`)"

        Design: Corner/validations/package_create_platform_mismatch_rejected
        """
        title, _vendor, plan, build = _assembly_prereqs(
            "VAL-PLT", title_platforms=("PS5", "PC"), plan_platform="PS5",
            build_platform="PC",
        )
        resp = api.create_submission_package(
            title["id"],
            create_submission_package_payload(
                "PS5", build["id"], plan["id"], get_title(title["id"])["version"]
            ),
            CL_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_BUILD_PLATFORM_MISMATCH)
        # No package landed, so the plan was never locked.
        assert get_plan(plan["id"])["status"] == "APPROVED"


class TestPackageSupersession:
    def test_second_package_supersedes_assembling_sibling(self, api):
        """PRD §3.5: "Any prior `ASSEMBLING` package for the same title and
        platform is moved to `SUPERSEDED`"
        PRD §3.5: "The referenced test plan moves `APPROVED` → `LOCKED` (or
        remains `LOCKED`). The title's `version` increments by one"

        Design: Corner/endpoints/package_create_supersedes_assembling_sibling
        """
        title, _vendor, plan, build = _assembly_prereqs("EP-SUP")
        pkg1 = create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        version_before_second = get_title(title["id"])["version"]
        create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        assert get_package(pkg1["id"])["status"] == "SUPERSEDED"
        assert get_plan(plan["id"])["status"] == "LOCKED"
        assert (
            get_title(title["id"])["version"] == version_before_second + 1
        )

    def test_package_create_response_reflects_side_effects_immediately(self, api):
        """PRD §3.5: "The new package starts `ASSEMBLING` with its `round`
        computed as one plus the count of prior non-superseded packages for
        the same title and platform. A compliance checklist is seeded
        automatically from the platform's requirements catalog (§3.6) and its
        identifier is recorded on the package as `checklist_id`"
        PRD §3.6: "The optimistic reading, `readiness_optimistic_pct`,
        additionally counts `UNVERIFIED` items whose `auto_verifiable` flag is
        true as if they had passed — the planning reading used during
        assembly."
        PRD §2.5: "**`version` (integer):** A system-managed integer that
        starts at 1 on creation and increments with every modification to the
        resource, including mutations driven by system cascades."

        Design: Corner/consistency_model/package_create_response_reflects_side_effects_immediately
        """
        title, _vendor, plan, build = _assembly_prereqs("CM-IMM")
        package = create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        assert_submission_package(package)
        assert package["status"] == "ASSEMBLING"
        assert package["round"] == 1
        assert package["version"] == 1
        assert isinstance(package["checklist_id"], str) and package["checklist_id"]
        # Freshly seeded PS5 catalog: one auto-verifiable item of four.
        assert package["readiness_optimistic_pct"] == 25.00
        assert package["readiness_strict_pct"] == 0.00
        assert get_plan(plan["id"])["status"] == "LOCKED"
        checklist = get_checklist(package["checklist_id"])
        assert checklist["total_items"] == 4
        assert checklist["unverified_count"] == 4


class TestPackageCreateOcc:
    def test_stale_title_version_rejected_on_package_create(self, api):
        """PRD §2.6: "First, assembling a new submission package for a title
        requires the request to carry `expected_title_version`, the caller's
        last-observed `version` of the title. If the title's current `version`
        no longer matches — because another writer advanced it since the
        client last read the title, for example by completing a superseding
        package assembly — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_package_create_stale_title_version
        """
        title, _vendor, plan, build = _assembly_prereqs("LYR-OCC")
        observed = get_title(title["id"])["version"]
        assert observed == 2  # created at 1, one lifecycle transition to 2
        pkg1 = create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        assert get_title(title["id"])["version"] == 3
        resp = api.create_submission_package(
            title["id"],
            create_submission_package_payload(
                "PS5", build["id"], plan["id"], expected_title_version=observed
            ),
            CL_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # The rejected create performed no supersede.
        assert get_package(pkg1["id"])["status"] == "ASSEMBLING"


class TestFindingsFilingWindow:
    def _assembling_package(self, title_code):
        title, _vendor, plan, build = _assembly_prereqs(title_code)
        package = create_submission_package(
            title["id"], "PS5", build["id"], plan["id"]
        )
        return title, package

    def test_finding_on_assembling_package_rejected(self, api):
        """PRD §3.7: "Findings may only be filed while the package is
        `IN_REVIEW` or `REJECTED`; any other state is rejected with
        `ERR_PACKAGE_NOT_REVIEWABLE`."

        Design: Corner/endpoints/findings_rejected_on_assembling_package
        """
        _title, package = self._assembling_package("EP-FND")
        resp = api.create_finding(
            package["id"],
            create_finding_payload(severity="CATEGORY_B",
                                   requirement_code="TRC-PS-04",
                                   description="minor text overflow"),
            PR_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_REVIEWABLE)

    def test_finding_filing_forbidden_for_certification_lead(self, api):
        """PRD §3.7: "During review the `PlatformReviewer` files
        **certification findings** on the package"
        PRD §2.8: "2. **Authorization.** The role is permitted for this
        endpoint and, on transition endpoints, for this specific action —
        otherwise `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/findings_create_forbidden_for_certification_lead
        """
        _title, package = self._assembling_package("RB-FND")
        resp = api.create_finding(
            package["id"],
            create_finding_payload(severity="CATEGORY_B",
                                   requirement_code="TRC-PS-04",
                                   description="text overflow"),
            CL_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
