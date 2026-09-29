"""Three boundaries probed from both sides: the coverage floor at attestation, the
in-scope inventory at publication, and a train's effort capacity at commit."""

import pytest

from test_helpers import (
    LEAD,
    REVIEWER,
    attestation_payload,
    author_assessment,
    approve_report,
    commit_issue,
    commit_issue_payload,
    complete_run,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    design_review_payload,
    expected_coverage_pct,
    log_issue,
    open_report,
    publication_payload,
    read_assessment,
    read_component,
    read_known_issue,
    read_product,
    read_release_train,
    read_report,
    schedule_run,
    submit_report,
    triage_issue,
    validate_error,
    validate_success,
)

CHANNEL = "CUSTOMER_TRUST_PORTAL"

# Component A is exercised over its whole scope, component B one criterion short.
FULL_SWEEP = 40
ONE_SHORT = 39


def build_two_components_either_side_of_the_coverage_floor():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="A",
        disability_categories=["VISION", "COGNITIVE"],
        applies_to_surfaces=["WEB"],
    )
    product = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    component_a = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=40,
        user_reach_pct=60,
    )
    component_b = create_component(
        product["id"],
        name="Mobile App",
        component_type="MOBILE_APP",
        in_scope=True,
        assessment_scope="SAMPLED",
        applicable_criteria_count=40,
        user_reach_pct=40,
    )
    bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    run_a = schedule_run(
        component_a["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T12:00:00Z",
        criteria_exercised=FULL_SWEEP,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    complete_run(run_a["id"], defects_found=3)
    run_b = schedule_run(
        component_b["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start="2026-08-03T13:00:00Z",
        scheduled_end="2026-08-03T15:00:00Z",
        criteria_exercised=ONE_SHORT,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    complete_run(run_b["id"], defects_found=2)
    assessment_a = author_assessment(component_a["id"], criterion["id"], support_level="SUPPORTS")
    assessment_b = author_assessment(component_b["id"], criterion["id"], support_level="SUPPORTS")
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component_a": read_component(component_a["id"]),
        "component_b": read_component(component_b["id"]),
        "assessment_a": assessment_a,
        "assessment_b": assessment_b,
    }


def build_approved_report_with_an_entirely_excluded_inventory():
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
    for name, reach in (("Internal Admin Console", 5), ("Batch Import CLI", 2)):
        create_component(
            product["id"],
            name=name,
            component_type="DESKTOP_APP",
            in_scope=False,
            assessment_scope="EXCLUDED",
            applicable_criteria_count=40,
            user_reach_pct=reach,
        )
    product = read_product(product["id"])
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    submit_report(report["id"], product["id"])
    approve_report(report["id"])
    return {"standard": standard, "product": product, "report": report}


def build_train_with_capacity_eight_and_two_triaged_issues():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="A",
        disability_categories=["VISION", "COGNITIVE"],
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
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=40,
        user_reach_pct=60,
    )
    train = create_release_train(
        name="Train 2026.09",
        window_start="2026-09-01",
        window_end="2026-09-30",
        freeze_days=5,
        effort_capacity_points=8,
        remediation_budget_cents=0,
    )
    big = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="BLOCKER",
        effort_points=8,
        target_remediation_date="2026-09-10",
        publish_intent="INCLUDED",
        summary="Primary navigation is unreachable by keyboard",
    )
    small = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="MINOR",
        effort_points=1,
        target_remediation_date="2026-09-10",
        publish_intent="INCLUDED",
        summary="Decorative icons expose redundant alternative text",
    )
    triage_issue(big["id"], triage_note="Reproduced on Windows and macOS")
    triage_issue(small["id"], triage_note="Cosmetic, low reach")
    return {"product": product, "component": component, "train": train, "big": big, "small": small}


class TestCoverageAtTheAttestationFloor:
    """40 of 40 exercised criteria attest; 39 of 40 do not."""

    def test_a_component_exactly_on_the_floor_can_be_attested(self, api):
        """PRD §3.4: "The attestation floor is 45.00 percent."
        PRD §3.4: "A component whose recomputed `coverage_pct` is at least 45.00
        qualifies as `COMPLETE`; a component whose recomputed `coverage_pct` falls
        below 45.00 does not."
        PRD §3.5: "The owning component's `assessment_state` must be `COMPLETE`,
        or the request is `ERR_COMPONENT_ASSESSMENT_INCOMPLETE` — which is the
        coverage floor of §3.4 reaching into the attestation workflow."

        Design: Difficulty/boundary_precision_check/coverage_exactly_at_min_attest_threshold_versus_one_unit_short
        """
        ctx = build_two_components_either_side_of_the_coverage_floor()

        assert ctx["component_a"]["coverage_pct"] == pytest.approx(45.00, abs=0.01), (
            "40 manual screen-reader units over a scope of 40 land exactly on the floor, got "
            f"{ctx['component_a']['coverage_pct']}"
        )
        assert ctx["component_a"]["assessment_state"] == "COMPLETE"

        attested = validate_success(
            api.attest_assessment(
                ctx["assessment_a"]["id"],
                attestation_payload("Full manual sweep on NVDA 2026.1"),
                REVIEWER,
            )
        )

        assert attested["attestation_state"] == "ATTESTED", (
            "landing exactly on 45.00 is enough to attest, got "
            f"{attested['attestation_state']}"
        )

    def test_one_exercised_criterion_short_is_refused(self, api):
        """PRD §3.4: "Exactly one rounding happens in the whole calculation: the
        per-profile scores are kept at full precision and only the final
        percentage is rounded half-up to two decimal places, which becomes
        `coverage_pct`."
        PRD §3.4: "A component whose recomputed `coverage_pct` is at least 45.00
        qualifies as `COMPLETE`; a component whose recomputed `coverage_pct` falls
        below 45.00 does not."
        PRD §2.7: "19. The assessed component's assessment state is `COMPLETE`, at
        attestation — `ERR_COMPONENT_ASSESSMENT_INCOMPLETE` (409)."

        Design: Difficulty/boundary_precision_check/coverage_exactly_at_min_attest_threshold_versus_one_unit_short
        """
        ctx = build_two_components_either_side_of_the_coverage_floor()

        expected = expected_coverage_pct(
            40,
            [{"method": "MANUAL", "at_profile": "SCREEN_READER", "criteria_exercised": ONE_SHORT}],
        )
        assert expected == pytest.approx(43.88, abs=0.01)
        assert ctx["component_b"]["coverage_pct"] == pytest.approx(expected, abs=0.01), (
            "0.45 times 39/40 is 0.43875, which rounds half-up to 43.88, got "
            f"{ctx['component_b']['coverage_pct']}"
        )
        assert ctx["component_b"]["assessment_state"] == "IN_TESTING"

        validate_error(
            api.attest_assessment(
                ctx["assessment_b"]["id"],
                attestation_payload("Attempting the component that is one criterion short"),
                REVIEWER,
            ),
            "ERR_COMPONENT_ASSESSMENT_INCOMPLETE",
            409,
        )

        assessment = read_assessment(ctx["assessment_b"]["id"])
        assert assessment["attestation_state"] == "DRAFT"
        product = read_product(ctx["product"]["id"])
        assert product["components_complete_count"] == 1, (
            "only the component on the floor counts as complete, got "
            f"{product['components_complete_count']}"
        )


class TestPublishAtZeroThenOneInScopeComponent:
    """A non-empty but fully excluded inventory still counts as zero in scope."""

    def test_publication_is_refused_while_nothing_is_in_scope(self, api):
        """PRD §3.7: "The product must have at least one in-scope component, since
        an empty inventory cannot be certified, or the request is
        `ERR_NO_IN_SCOPE_COMPONENTS`."
        PRD §3.1: "`components_in_scope_count` is the number of the product's
        components whose in-scope flag is true"

        Design: Difficulty/boundary_precision_check/publish_at_zero_in_scope_components_then_at_one
        """
        ctx = build_approved_report_with_an_entirely_excluded_inventory()

        assert ctx["product"]["components_in_scope_count"] == 0, (
            "two components exist but neither is in scope, got "
            f"{ctx['product']['components_in_scope_count']}"
        )

        validate_error(
            api.publish_report(ctx["report"]["id"], publication_payload(CHANNEL), LEAD),
            "ERR_NO_IN_SCOPE_COMPONENTS",
            422,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "APPROVED", (
            f"the refusal leaves the report approved, got {report['state']}"
        )

    def test_adding_one_reviewed_in_scope_component_lets_publication_through(self, api):
        """PRD §3.7: "Every in-scope component's `design_review_state` must be
        `REVIEWED_PASS`, or the request is `ERR_DESIGN_REVIEW_INCOMPLETE`."
        PRD §3.7: "The report moves `APPROVED → PUBLISHED`, its `published_at` is
        stamped from the logical clock, and `conformance_index_certified` and
        `criterion_support_snapshot` are frozen from the certified rollup of
        §3.6."
        PRD §3.7: "Every known issue of the same product that is in state
        `COMMITTED` with a `publish_intent` of `INCLUDED` moves `COMMITTED →
        PUBLISHED_COMMITTED`, has its `public_target_date` set by copying its
        internal `target_remediation_date`, and has its `published_report_id` set
        to this report; the number of issues moved this way is recorded on the
        report as `published_issue_count`."

        Design: Difficulty/boundary_precision_check/publish_at_zero_in_scope_components_then_at_one
        """
        ctx = build_approved_report_with_an_entirely_excluded_inventory()
        validate_error(
            api.publish_report(ctx["report"]["id"], publication_payload(CHANNEL), LEAD),
            "ERR_NO_IN_SCOPE_COMPONENTS",
            422,
        )

        in_scope = create_component(
            ctx["product"]["id"],
            name="Web UI",
            component_type="WEB_UI",
            in_scope=True,
            assessment_scope="FULL",
            applicable_criteria_count=40,
            user_reach_pct=60,
        )
        validate_success(
            api.design_review(
                in_scope["id"],
                design_review_payload("PASS", "Acceptance criteria include the AT matrix"),
                REVIEWER,
            )
        )
        assert read_product(ctx["product"]["id"])["components_in_scope_count"] == 1

        published = validate_success(
            api.publish_report(ctx["report"]["id"], publication_payload(CHANNEL), LEAD)
        )

        assert published["state"] == "PUBLISHED", (
            f"one in-scope component is the whole difference, got {published['state']}"
        )
        assert published["pinned_assessment_ids"] == [], (
            "nothing was attested, so the pinned list stays empty, got "
            f"{published['pinned_assessment_ids']}"
        )
        assert published["published_issue_count"] == 0


class TestTrainCapacityAtExactEquality:
    """Landing exactly on capacity is admitted; the next point is not."""

    def test_an_issue_that_fills_the_train_exactly_is_committed(self, api):
        """PRD §3.9: "And the train must have room: the train's current
        `committed_effort_points` plus this issue's `effort_points` must not exceed
        its `effort_capacity_points`, or the request is
        `ERR_TRAIN_CAPACITY_EXCEEDED`; landing exactly on capacity is allowed."
        PRD §3.9: "On success the issue moves `TRIAGED → COMMITTED`, its
        `release_train_id` is recorded, the train's `committed_effort_points` rises
        by the issue's `effort_points`, and the product's `publication_posture` is
        rebuilt."

        Design: Difficulty/boundary_precision_check/train_effort_capacity_at_exact_equality_then_one_point_over
        """
        ctx = build_train_with_capacity_eight_and_two_triaged_issues()

        committed = validate_success(
            api.commit_issue(
                ctx["big"]["id"], commit_issue_payload(ctx["train"]["id"]), LEAD
            )
        )

        assert committed["state"] == "COMMITTED"
        assert committed["release_train_id"] == ctx["train"]["id"]
        train = read_release_train(ctx["train"]["id"])
        assert train["committed_effort_points"] == 8, (
            "8 points against a capacity of 8 is admitted at exact equality, got "
            f"{train['committed_effort_points']}"
        )

    def test_one_point_beyond_capacity_is_refused(self, api):
        """PRD §3.9: "And the train must have room: the train's current
        `committed_effort_points` plus this issue's `effort_points` must not exceed
        its `effort_capacity_points`, or the request is
        `ERR_TRAIN_CAPACITY_EXCEEDED`; landing exactly on capacity is allowed."
        PRD §3.9: "Thereafter `committed_effort_points` always equals the sum of
        `effort_points` over the train's issues in states `COMMITTED` and
        `PUBLISHED_COMMITTED`, and `unallocated_cents` always equals
        `remediation_budget_cents` minus the sum of `funded_cents` over the train's
        issues."

        Design: Difficulty/boundary_precision_check/train_effort_capacity_at_exact_equality_then_one_point_over
        """
        ctx = build_train_with_capacity_eight_and_two_triaged_issues()
        commit_issue(ctx["big"]["id"], ctx["train"]["id"])

        validate_error(
            api.commit_issue(
                ctx["small"]["id"], commit_issue_payload(ctx["train"]["id"]), LEAD
            ),
            "ERR_TRAIN_CAPACITY_EXCEEDED",
            409,
        )

        small = read_known_issue(ctx["small"]["id"])
        assert small["state"] == "TRIAGED", (
            f"the refused commit leaves the issue triaged, got {small['state']}"
        )
        assert small["release_train_id"] is None
        train = read_release_train(ctx["train"]["id"])
        assert train["committed_effort_points"] == 8, (
            "the refusal changes nothing on the train, got "
            f"{train['committed_effort_points']}"
        )
