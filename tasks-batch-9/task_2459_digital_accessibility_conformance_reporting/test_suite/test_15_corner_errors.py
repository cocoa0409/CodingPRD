"""Error breadth: authentication ahead of everything else, the two publication
gates that survive one another, an empty candidate set at allocation, a level the
parent standard does not reach, a bench that does not provide the declared
profile, a branch action on the wrong route, and evidence from the wrong
component."""

import pytest

from test_helpers import (
    LEAD,
    LIAISON,
    TESTER,
    allocate_budget_payload,
    approve_report,
    commit_issue,
    complaint_triage_payload,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    criterion_payload,
    headers_without_role,
    headers_without_user_id,
    intake_complaint,
    log_issue,
    open_report,
    publication_payload,
    read_complaint,
    read_component,
    read_environment,
    read_known_issue,
    read_product,
    read_release_train,
    read_report,
    record_design_review,
    resolve_issue_payload,
    run_payload,
    schedule_and_complete_run,
    standard_payload,
    submit_report,
    triage_issue,
    validate_error,
    validate_paginated,
    validate_success,
)

APPLICABLE_CRITERIA = 40
RUN_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")

# One manual SCREEN_READER run over all 40 applicable criteria carries the whole
# 45 percent screen-reader weight and nothing else.
FULL_SWEEP_COVERAGE_PCT = 45.00

TRAIN_BUDGET_CENTS = 60327
ISSUE_EFFORT_POINTS = 2


def build_publication_candidate(criterion_level, disability_categories, design_review):
    """A product taken all the way to an APPROVED report.

    `criterion_level` decides whether the standard's single criterion is in the
    product's target scope, and `design_review` decides whether the component has
    been signed off, so each publication gate can be reached in isolation.
    """
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.2.2",
        title="Captions Prerecorded",
        level=criterion_level,
        disability_categories=disability_categories,
        applies_to_surfaces=["WEB"],
    )
    product = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    component = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    if design_review:
        record_design_review(
            component["id"],
            review_decision="PASS",
            review_note="Acceptance criteria include the AT matrix",
        )
        schedule_and_complete_run(
            component["id"],
            create_environment(
                name="NVDA Bench 1",
                at_profile="SCREEN_READER",
                reconfiguration_buffer_minutes=30,
            )["id"],
            method="MANUAL",
            at_profile="SCREEN_READER",
            scheduled_start=RUN_WINDOW[0],
            scheduled_end=RUN_WINDOW[1],
            criteria_exercised=APPLICABLE_CRITERIA,
            disability_categories_validated=["VISION"],
            defects_found=1,
        )
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    submit_report(report["id"], product["id"], submission_note="Ready for reviewer sign-off")
    approved = approve_report(report["id"], approval_note="Approved for publication")
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "report": approved,
    }


def build_product_with_one_open_issue():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="A",
        disability_categories=["VISION"],
        applies_to_surfaces=["WEB"],
    )
    product = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    component = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    issue = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="SERIOUS",
        effort_points=ISSUE_EFFORT_POINTS,
        target_remediation_date="2026-09-25",
        publish_intent="INCLUDED",
        summary="Media library thumbnails expose no accessible name",
    )
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "issue": issue,
    }


def build_issue_committed_with_evidence_on_a_sibling_component():
    ctx = build_product_with_one_open_issue()
    sibling = create_component(
        ctx["product"]["id"],
        name="Report Viewer",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=30,
    )
    bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    sibling_run = schedule_and_complete_run(
        sibling["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start=RUN_WINDOW[0],
        scheduled_end=RUN_WINDOW[1],
        criteria_exercised=APPLICABLE_CRITERIA,
        disability_categories_validated=["VISION"],
        defects_found=0,
    )
    train = create_release_train(
        name="Train 2026.09",
        window_start="2026-09-05",
        window_end="2026-09-27",
        freeze_days=2,
        effort_capacity_points=10,
        remediation_budget_cents=100000,
    )
    triage_issue(ctx["issue"]["id"], triage_note="Confirmed on NVDA and JAWS")
    commit_issue(ctx["issue"]["id"], train["id"])
    return {**ctx, "sibling": sibling, "sibling_run": sibling_run, "train": train}


class TestAuthenticationPrecedesEverything:
    """A missing identity header is answered before any body is looked at."""

    def test_a_create_missing_an_identity_header_is_unauthenticated(self, api):
        """PRD §2.1: "Every request to every endpoint must carry two headers:
        `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's
        role. If either header is absent, or if `X-User-Role` is not exactly one of
        the five role names below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."
        PRD §2.7: "1. Authentication headers present and the role recognised —
        `ERR_UNAUTHENTICATED` (401)."
        PRD §3.1: "Because a standard code identifies a published document,
        registering a second standard with an already-registered `code` is rejected
        with `ERR_DUPLICATE_STANDARD_CODE`."

        Design: Corner/errors/corner_request_without_role_header_returns_unauthenticated
        """
        payload = standard_payload(
            code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
        )

        validate_error(
            api.create_standard(payload, headers_without_role()),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api.create_standard(payload, headers_without_user_id("AccessibilityLead")),
            "ERR_UNAUTHENTICATED",
            401,
        )

        # Nothing was written: the code is still free, so registering it now succeeds
        # instead of colliding with a row left behind by a refused request.
        accepted = validate_success(api.create_standard(payload, LEAD), 201)
        assert accepted["code"] == "WCAG_2_2", (
            f"the first accepted registration takes the code, got {accepted['code']}"
        )
        assert accepted["criteria_count"] == 0


class TestPublicationCoverageGate:
    """Manual validation must cover every category the in-scope criteria protect."""

    def test_publishing_without_a_validated_category_is_refused(self, api):
        """PRD §3.7: "Every in-scope component's `validated_disability_categories`
        must contain every disability category appearing anywhere in the
        `disability_categories` of the in-scope criteria — a superset relationship,
        checked component by component — or the request is
        `ERR_DISABILITY_COVERAGE_GAP`; in practice this means a product whose
        in-scope criteria protect vision, hearing, motor and cognitive users cannot
        be certified until every in-scope component has manual
        assistive-technology validation for all four."
        PRD §2.7: "18. Disability-category validation coverage at publication —
        `ERR_DISABILITY_COVERAGE_GAP` (422)."
        PRD §3.7: "Publication then does a great deal at once, and every one of
        these effects is part of the contract. The report moves `APPROVED →
        PUBLISHED`, its `published_at` is stamped from the logical clock, and
        `conformance_index_certified` and `criterion_support_snapshot` are frozen
        from the certified rollup of §3.6."

        Design: Corner/errors/corner_publish_with_unvalidated_category_returns_coverage_gap
        """
        ctx = build_publication_candidate(
            criterion_level="A",
            disability_categories=["VISION", "HEARING"],
            design_review=True,
        )

        assert ctx["report"]["state"] == "APPROVED"

        validate_error(
            api.publish_report(ctx["report"]["id"], publication_payload(), LEAD),
            "ERR_DISABILITY_COVERAGE_GAP",
            422,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "APPROVED", (
            f"the refused publication moves no report state, got {report['state']}"
        )
        assert report["published_at"] is None, (
            f"nothing was stamped from the clock, got {report['published_at']}"
        )
        component = read_component(ctx["component"]["id"])
        assert component["coverage_pct"] == pytest.approx(FULL_SWEEP_COVERAGE_PCT, abs=0.01), (
            "coverage is a quantity of evidence, and it is unaffected by the missing "
            f"category, got {component['coverage_pct']}"
        )
        assert component["validated_disability_categories"] == ["VISION"], (
            "HEARING was never validated by a manual run, got "
            f"{component['validated_disability_categories']}"
        )


class TestPublicationDesignReviewGate:
    """With no criterion in scope the coverage gate is vacuous and sign-off is next."""

    def test_publishing_an_unreviewed_component_is_refused(self, api):
        """PRD §3.7: "Every in-scope component's `design_review_state` must be
        `REVIEWED_PASS`, or the request is `ERR_DESIGN_REVIEW_INCOMPLETE`."
        PRD §2.7: "20. Design-review sign-off of every in-scope component at
        publication — `ERR_DESIGN_REVIEW_INCOMPLETE` (422)."
        PRD §3.7: "It requires the report to be `APPROVED` — otherwise
        `ERR_REPORT_NOT_APPROVED` — and then five substantive conditions, evaluated
        in the order set out in §2.7."

        Design: Corner/errors/corner_publish_without_design_review_returns_incomplete
        """
        ctx = build_publication_candidate(
            criterion_level="AAA", disability_categories=["VISION"], design_review=False
        )

        assert read_component(ctx["component"]["id"])["design_review_state"] == "NOT_REVIEWED", (
            "the component was never taken through design review"
        )

        validate_error(
            api.publish_report(ctx["report"]["id"], publication_payload(), LEAD),
            "ERR_DESIGN_REVIEW_INCOMPLETE",
            422,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "APPROVED", (
            f"the report stays where approval left it, got {report['state']}"
        )
        assert report["published_at"] is None
        assert read_product(ctx["product"]["id"])["publication_posture"] == "OPEN", (
            "a refused publication is not a posture event"
        )


class TestAllocationCandidateSet:
    """An empty candidate set is refused, not funded with zero."""

    def test_allocating_against_a_train_holding_no_commitment_is_refused(self, api):
        """PRD §3.9: "The train must not have allocated already — a second attempt
        is `ERR_TRAIN_BUDGET_ALREADY_ALLOCATED` — the product must not be `FROZEN`,
        and there must be at least one candidate issue or the request is
        `ERR_NO_FUNDABLE_ISSUES`."
        PRD §3.9: "The candidate set is precisely the known issues whose
        `release_train_id` is this train, whose `product_id` is the requested
        product, and whose state is `COMMITTED` or `PUBLISHED_COMMITTED`; issues in
        `OPEN`, `TRIAGED`, `DEFERRED` or `RESOLVED` are excluded even if they still
        carry a `release_train_id`."
        PRD §2.7: "39. At least one fundable issue at allocation —
        `ERR_NO_FUNDABLE_ISSUES` (422)."

        Design: Corner/errors/corner_allocate_budget_with_no_committed_issues_rejected
        """
        ctx = build_product_with_one_open_issue()
        train = create_release_train(
            name="Train 2026.09",
            window_start="2026-09-05",
            window_end="2026-09-27",
            freeze_days=2,
            effort_capacity_points=10,
            remediation_budget_cents=TRAIN_BUDGET_CENTS,
        )

        assert ctx["issue"]["state"] == "OPEN", (
            f"the issue was never triaged or committed, got {ctx['issue']['state']}"
        )

        validate_error(
            api.allocate_budget(
                train["id"], allocate_budget_payload(ctx["product"]["id"]), LEAD
            ),
            "ERR_NO_FUNDABLE_ISSUES",
            422,
        )

        stored_train = read_release_train(train["id"])
        assert stored_train["allocation_state"] == "UNALLOCATED", (
            "a refused allocation does not consume the train's one allocation, got "
            f"{stored_train['allocation_state']}"
        )
        assert stored_train["unallocated_cents"] == TRAIN_BUDGET_CENTS
        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["funded_cents"] == 0, (
            f"an OPEN issue is not a candidate, got {issue['funded_cents']}"
        )
        assert issue["funding_state"] == "UNFUNDED"


class TestLevelCompatibilityWithTheParentStandard:
    """An enum-valid level the standard does not reach is a 422, not a bad body."""

    def test_a_criterion_stricter_than_the_standard_is_refused(self, api):
        """PRD §3.1: "A `criterion_number` that already exists on that same standard
        is rejected with `ERR_DUPLICATE_CRITERION_NUMBER`, and a criterion whose
        `level` is stricter than the standard's `max_target_level` — for instance
        `AAA` on a standard that stops at `AA` — is rejected with
        `ERR_LEVEL_OR_SURFACE_UNSUPPORTED`."
        PRD §2.7: "37. Conformance level and surface compatibility with the standard
        — `ERR_LEVEL_OR_SURFACE_UNSUPPORTED` (422)."
        PRD §3.1: "Criteria may be read individually or listed for a standard, and
        that listing accepts an optional `level` filter alongside `limit` and
        `offset`."

        Design: Corner/errors/corner_criterion_above_standard_max_level_rejected
        """
        standard = create_standard(
            code="EN_301_549",
            title="EN 301 549 harmonised",
            surface_scope="WEB",
            max_target_level="AA",
        )

        validate_error(
            api.create_criterion(
                standard["id"],
                criterion_payload(
                    criterion_number="1.4.6",
                    title="Contrast Enhanced",
                    level="AAA",
                    disability_categories=["VISION"],
                    applies_to_surfaces=["WEB"],
                ),
                LEAD,
            ),
            "ERR_LEVEL_OR_SURFACE_UNSUPPORTED",
            422,
        )

        _rows, meta = validate_paginated(api.list_criteria(standard["id"], LEAD))
        assert meta["total_count"] == 0, (
            f"the refused attachment wrote no criterion, got {meta['total_count']}"
        )
        assert validate_success(api.get_standard(standard["id"], LEAD))["criteria_count"] == 0


class TestBenchProfileCompatibility:
    """A bench provides exactly one profile, and a run must declare that one."""

    def test_a_keyboard_run_on_a_screen_reader_bench_is_refused(self, api):
        """PRD §3.3: "The declared `at_profile` must equal the profile the chosen
        bench provides, since a magnification bench cannot exercise a screen reader;
        a mismatch is `ERR_ENVIRONMENT_PROFILE_MISMATCH`."
        PRD §2.6: "A reference that resolves but points into the wrong aggregate is
        a 422-class failure described in §2.7 and in the workflow subsections: a
        criterion belonging to another standard is
        `ERR_CRITERION_STANDARD_MISMATCH`, a report opened against a standard other
        than the product's own is `ERR_REPORT_STANDARD_MISMATCH`, a run declaring an
        assistive-technology profile the bench does not provide is
        `ERR_ENVIRONMENT_PROFILE_MISMATCH`, and a component, report or issue drawn
        from a different product is `ERR_CROSS_PRODUCT_REFERENCE`."
        PRD §3.3: "A bench also reports a derived `scheduled_run_count`, being the
        number of runs on it whose `status` is either `SCHEDULED` or `COMPLETED`."

        Design: Corner/errors/corner_run_profile_not_matching_bench_rejected
        """
        standard = create_standard(
            code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
        )
        product = create_product(
            standard["id"],
            name="Insight Portal",
            version_label="7.0",
            target_level="AA",
            surface_type="WEB",
        )
        component = create_component(
            product["id"],
            name="Web UI",
            component_type="WEB_UI",
            in_scope=True,
            assessment_scope="FULL",
            applicable_criteria_count=APPLICABLE_CRITERIA,
            user_reach_pct=60,
        )
        bench = create_environment(
            name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
        )

        validate_error(
            api.create_run(
                run_payload(
                    component["id"],
                    bench["id"],
                    method="MANUAL",
                    at_profile="KEYBOARD",
                    scheduled_start=RUN_WINDOW[0],
                    scheduled_end=RUN_WINDOW[1],
                    criteria_exercised=20,
                    disability_categories_validated=["MOTOR"],
                ),
                TESTER,
            ),
            "ERR_ENVIRONMENT_PROFILE_MISMATCH",
            422,
        )

        assert read_environment(bench["id"])["scheduled_run_count"] == 0, (
            "the bench's calendar is untouched by a refused booking"
        )
        assert read_component(component["id"])["assessment_state"] == "PLANNED", (
            "no first run took hold, so the testing dimension never started"
        )


class TestBranchActionsAreRouteBound:
    """The complaint is in the right state and still on the wrong branch."""

    def test_fulfilling_an_accommodation_on_a_remediation_complaint_is_refused(self, api):
        """PRD §3.11: "It likewise requires the complaint to be `TRIAGED`, and
        requires its `route` to be `ACCOMMODATION` — attempting it on a
        remediation-routed complaint is `ERR_COMPLAINT_ROUTE_MISMATCH`."
        PRD §2.7: "31. The complaint's route matches the requested branch action and
        closure outcome — `ERR_COMPLAINT_ROUTE_MISMATCH` (409)."
        PRD §3.11: "On success the complaint moves `TRIAGED → ACCOMMODATED`,
        `accommodation_fulfilled_at` is stamped from the logical clock, and the
        product's `accommodations_fulfilled_count` is rebuilt."

        Design: Corner/errors/corner_fulfill_accommodation_on_remediation_route_rejected
        """
        standard = create_standard(
            code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
        )
        product = create_product(
            standard["id"],
            name="Insight Portal",
            version_label="7.0",
            target_level="AA",
            surface_type="WEB",
        )
        component = create_component(
            product["id"],
            name="Web UI",
            component_type="WEB_UI",
            in_scope=True,
            assessment_scope="FULL",
            applicable_criteria_count=APPLICABLE_CRITERIA,
            user_reach_pct=60,
        )
        complaint = intake_complaint(
            product["id"],
            component_id=component["id"],
            channel="EMAIL",
            description="Images in the report viewer have no alternative text",
            disability_category="VISION",
        )
        triaged = validate_success(
            api.triage_complaint(
                complaint["id"], complaint_triage_payload(route="REMEDIATION"), LEAD
            )
        )

        assert triaged["route"] == "REMEDIATION"

        validate_error(
            api.fulfill_accommodation(complaint["id"], {}, LIAISON),
            "ERR_COMPLAINT_ROUTE_MISMATCH",
            409,
        )

        stored = read_complaint(complaint["id"])
        assert stored["state"] == "TRIAGED", (
            "the state was never the problem, and it does not move, got "
            f"{stored['state']}"
        )
        assert stored["accommodation_fulfilled_at"] is None, (
            f"nothing was stamped, got {stored['accommodation_fulfilled_at']}"
        )
        assert read_product(product["id"])["accommodations_fulfilled_count"] == 0


class TestResolutionEvidenceOwnership:
    """A green run next door proves nothing about this defect."""

    def test_resolving_with_a_run_on_another_component_is_refused(self, api):
        """PRD §3.9: "The cited run must have `status` `COMPLETED` and must belong to
        the same component as the issue, or the request is
        `ERR_RESOLUTION_EVIDENCE_INVALID` — a passing run on a neighbouring
        component proves nothing about this defect."
        PRD §2.7: "34. Resolution evidence is a completed run on the issue's own
        component — `ERR_RESOLUTION_EVIDENCE_INVALID` (422)."
        PRD §3.9: "On success the `resolution_note` and `resolution_run_id` are
        recorded, a resolution instant is stamped from the logical clock, and the
        compensating financial effects run: the train's `committed_effort_points`
        drops by the issue's `effort_points`, the train's `unallocated_cents` rises
        by the issue's `funded_cents`, and the issue's `funded_cents` returns to 0
        with `funding_state` returning to `UNFUNDED`."

        Design: Corner/errors/corner_resolve_with_run_on_other_component_rejected
        """
        ctx = build_issue_committed_with_evidence_on_a_sibling_component()

        assert ctx["sibling_run"]["status"] == "COMPLETED", (
            "the cited run is genuinely completed, so only its ownership is wrong"
        )

        validate_error(
            api.resolve_issue(
                ctx["issue"]["id"],
                resolve_issue_payload(
                    ctx["sibling_run"]["id"],
                    resolution_note="Alternative text added to every thumbnail",
                ),
                TESTER,
            ),
            "ERR_RESOLUTION_EVIDENCE_INVALID",
            422,
        )

        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["state"] == "COMMITTED", (
            f"the refused resolution transitions nothing, got {issue['state']}"
        )
        assert issue["resolution_run_id"] is None
        assert (
            read_release_train(ctx["train"]["id"])["committed_effort_points"]
            == ISSUE_EFFORT_POINTS
        ), "the compensating release of effort points did not run"
