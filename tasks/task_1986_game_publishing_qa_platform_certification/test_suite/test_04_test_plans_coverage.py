"""Test plan lifecycle: entry editing window, review gate, approval coverage
gate, and the uniqueness rules on plans and entries."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_plan_entry,
    create_assignment,
    create_plan,
    create_plan_entry_payload,
    create_test_plan_payload,
    create_title,
    create_vendor,
    get_plan,
    transition_plan,
    validate_error,
    validate_success,
)

QA_HEADERS = TEST_USERS["qa_lead_headers"]


class TestPlanReviewGate:
    def test_plan_cannot_skip_review_step(self, api):
        """PRD §3.2: "The plan lifecycle is a review loop with system-driven
        lock transitions. A `QALead` sends `DRAFT` → `IN_REVIEW`, which
        requires at least one entry (`ERR_NO_PLAN_ENTRIES`). Approval moves
        `IN_REVIEW` → `APPROVED`"
        PRD §2.8: "**State legality.** The target entity is in a legal
        from-state for the requested transition — otherwise
        `ERR_INVALID_STATE` (or `ERR_PACKAGE_NOT_ASSEMBLING` for package
        submission)."

        Design: Corner/state_machines/plan_cannot_skip_review_step
        """
        title = create_title(title_code="SM-PLN", cert_budget_total_cents=1000)
        vendor = create_vendor(name="VendorSM")
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=10)
        create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                          reserved_hours=10)
        resp = api.transition_test_plan(
            plan["id"], {"to_status": "APPROVED"},
            QA_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_plan(plan["id"])["status"] == "DRAFT"

    def test_plan_review_requires_at_least_one_entry(self, api):
        """PRD §3.2: "A `QALead` sends `DRAFT` → `IN_REVIEW`, which requires
        at least one entry (`ERR_NO_PLAN_ENTRIES`)."

        Design: Corner/state_machines/plan_review_requires_entries
        """
        title = create_title(title_code="SM-PLN2", cert_budget_total_cents=1000)
        plan = create_plan(title["id"], "PS5")
        resp = api.transition_test_plan(
            plan["id"], {"to_status": "IN_REVIEW"}, QA_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_NO_PLAN_ENTRIES)
        add_plan_entry(plan["id"], feature_area="AUDIO_MIX",
                       required_coverage_hours=4, is_cert_blocker=False)
        plan = transition_plan(plan["id"], "IN_REVIEW")
        assert plan["status"] == "IN_REVIEW"

    def test_plan_entries_frozen_after_review_start(self, api):
        """PRD §3.2: "While the plan is `DRAFT`, the `QALead` appends
        feature-matrix rows to its `entries` collection one at a time;
        appending to a plan in any other state is rejected with
        `ERR_PLAN_NOT_DRAFT`."

        Design: Corner/state_machines/plan_entries_locked_after_review_start
        """
        title = create_title(title_code="SM2-PND", cert_budget_total_cents=1000)
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=4)
        transition_plan(plan["id"], "IN_REVIEW")
        resp = api.add_plan_entry(
            plan["id"],
            create_plan_entry_payload(
                feature_area="NETWORK", platform_layer="SERVICE",
                is_cert_blocker=False, required_coverage_hours=2,
            ),
            QA_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)
        assert len(get_plan(plan["id"])["entries"]) == 1


class TestPlanApprovalCoverage:
    def test_approve_requires_every_cert_blocker_entry_covered(self, api):
        """PRD §3.2: "Approval moves `IN_REVIEW` → `APPROVED` and is granted
        only when every cert-blocker entry is `COVERED` — otherwise
        `ERR_REQUIRED_COVERAGE_MISSING`."
        PRD §3.2: "On the plan itself, `required_entries_total` counts the
        entries flagged as cert blockers and `covered_required_count` counts
        how many of those are currently `COVERED`."

        Design: Corner/state_machines/plan_approve_requires_full_coverage
        """
        title = create_title(title_code="SM2-COV", cert_budget_total_cents=1000)
        vendor = create_vendor(name="VendorCov")
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=10)
        add_plan_entry(plan["id"], feature_area="NETWORK",
                       platform_layer="SERVICE", required_coverage_hours=6)
        create_assignment(vendor["id"], plan["id"], feature_area="COMBAT",
                          reserved_hours=10)
        create_assignment(vendor["id"], plan["id"], feature_area="NETWORK",
                          reserved_hours=2)
        transition_plan(plan["id"], "IN_REVIEW")
        resp = api.transition_test_plan(
            plan["id"], {"to_status": "APPROVED"}, QA_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_REQUIRED_COVERAGE_MISSING)
        create_assignment(vendor["id"], plan["id"], feature_area="NETWORK",
                          reserved_hours=4)
        plan = transition_plan(plan["id"], "APPROVED")
        assert plan["status"] == "APPROVED"
        assert plan["covered_required_count"] == 2
        assert plan["required_entries_total"] == 2


class TestPlanUniqueness:
    def test_one_live_plan_per_title_and_platform(self, api):
        """PRD §3.2: "Creating a plan names the `title_id` and the
        `platform_code`; at most one non-archived plan may exist for a given
        title and platform, and a conflicting create is rejected with
        `ERR_DUPLICATE_TEST_PLAN`."

        Design: Corner/entities/duplicate_test_plan_per_platform_rejected
        """
        title = create_title(title_code="ENT-DUP4", platform_codes=["PS5", "PC"],
                             cert_budget_total_cents=1000)
        qa = QA_HEADERS
        validate_success(
            api.create_test_plan(
                create_test_plan_payload(title["id"], "PS5"), qa
            ),
            expected_status=201,
        )
        resp = api.create_test_plan(
            create_test_plan_payload(title["id"], "PS5"), qa
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TEST_PLAN)
        validate_success(
            api.create_test_plan(
                create_test_plan_payload(title["id"], "PC"), qa
            ),
            expected_status=201,
        )

    def test_duplicate_feature_area_rejected_within_plan(self, api):
        """PRD §3.2: "Each entry carries a `feature_area` — unique within the
        plan, with duplicates rejected as `ERR_DUPLICATE_FEATURE_AREA`"

        Design: Corner/entities/plan_duplicate_feature_area_rejected
        """
        title = create_title(title_code="ENT-DUP1", cert_budget_total_cents=1000)
        plan = create_plan(title["id"], "PS5")
        add_plan_entry(plan["id"], feature_area="COMBAT",
                       required_coverage_hours=4)
        resp = api.add_plan_entry(
            plan["id"],
            create_plan_entry_payload(
                feature_area="COMBAT", platform_layer="SERVICE",
                is_cert_blocker=False, required_coverage_hours=2,
            ),
            QA_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FEATURE_AREA)
        add_plan_entry(plan["id"], feature_area="NETWORK",
                       platform_layer="SERVICE", is_cert_blocker=False,
                       required_coverage_hours=2)
        assert len(get_plan(plan["id"])["entries"]) == 2
