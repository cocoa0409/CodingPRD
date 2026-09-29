"""Cross-cutting breadth: the two optimistically locked creates, each refused on a
version the client had already outgrown and accepted on the re-read one, and the
in-scope denominator that an excluded component never enters."""

import pytest

from test_helpers import (
    LEAD,
    TESTER,
    TESTER_USER_ID,
    assessment_payload,
    complete_run,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_standard,
    read_component,
    read_product,
    report_payload,
    schedule_run,
    validate_error,
    validate_success,
)

APPLICABLE_CRITERIA = 40
RUN_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")

# One manual SCREEN_READER run over all 40 applicable criteria carries the whole
# 45 percent screen-reader weight, which is exactly the attestation floor.
FULL_SWEEP_COVERAGE_PCT = 45.00

# The excluded component is a batch job nobody drives through a browser.
EXCLUDED_CRITERIA_COUNT = 5
EXCLUDED_REACH_PCT = 1


def build_product_then_add_a_component():
    """A product whose captured version is left one behind by a later component."""
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
    stale_version = product["version"]
    component = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    return {
        "standard": standard,
        "product": product,
        "component": component,
        "stale_version": stale_version,
    }


def build_component_then_complete_a_run():
    """A component whose captured version is left behind by a run completion."""
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
    stale_version = component["version"]
    bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    run = schedule_run(
        component["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start=RUN_WINDOW[0],
        scheduled_end=RUN_WINDOW[1],
        criteria_exercised=APPLICABLE_CRITERIA,
        disability_categories_validated=["VISION"],
    )
    complete_run(run["id"], defects_found=1)
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "stale_version": stale_version,
        "run": run,
    }


class TestReportCreationIsLockedToTheProduct:
    """The guard is on the version, not on the body."""

    def test_a_product_version_read_before_the_component_is_stale(self, api):
        """PRD §2.5: "Opening a conformance report requires a non-optional
        `expected_product_version` field in the request body carrying the client's
        last observed `version` of the target `Product`. If that value does not equal
        the product's current `version`, the create is rejected with
        `ERR_STALE_PRODUCT_VERSION` (HTTP 412)."
        PRD §2.5: "This is not a courtesy check: a report legitimately supersedes the
        product's previously published report at publication time, and a writer
        holding a stale view of the product — of its posture, its provisional index,
        its component counts, or of an already-open report — must re-read the product
        before authoring."
        PRD §3.2: "Its creation immediately rebuilds the owning product's
        `components_in_scope_count`, `assessment_readiness`,
        `conformance_index_provisional` and `publication_posture`, and raises the
        product's `version` by 1."
        PRD §3.7: "A new report starts in `state` `DRAFT` with `pinned_assessment_ids`
        and `pinned_assessment_versions` both empty, an empty
        `criterion_support_snapshot`, no `conformance_index_certified`, a
        `published_issue_count` of 0, a `change_request_count` of 0, no
        `publication_channel`, no `published_at`, no `withdrawal_reason`, no
        `superseded_by_report_id`, and neither a `submitted_by_user_id` nor an
        `approved_by_user_id`."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_product_version_blocks_report_create
        """
        ctx = build_product_then_add_a_component()
        fresh = read_product(ctx["product"]["id"])

        assert fresh["version"] == ctx["stale_version"] + 1, (
            "adding the component advanced the product by exactly one version, got "
            f"{fresh['version']} against {ctx['stale_version']}"
        )
        assert fresh["components_in_scope_count"] == 1

        validate_error(
            api.create_report(
                report_payload(
                    ctx["product"]["id"],
                    ctx["standard"]["id"],
                    ctx["stale_version"],
                    report_title="ACR Insight Portal 7.0",
                ),
                LEAD,
            ),
            "ERR_STALE_PRODUCT_VERSION",
            412,
        )

        accepted = validate_success(
            api.create_report(
                report_payload(
                    ctx["product"]["id"],
                    ctx["standard"]["id"],
                    fresh["version"],
                    report_title="ACR Insight Portal 7.0",
                ),
                LEAD,
            ),
            201,
        )

        assert accepted["state"] == "DRAFT", (
            "the identical body succeeds once the version is current, which is what "
            f"makes the guard version-based, got {accepted['state']}"
        )
        assert accepted["product_id"] == ctx["product"]["id"]


class TestAssessmentAuthoringIsLockedToTheComponent:
    """A completed run overtakes the client's view of the component."""

    def test_a_component_version_read_before_the_run_completion_is_stale(self, api):
        """PRD §2.5: "Authoring a criterion assessment requires a non-optional
        `expected_component_version` field carrying the client's last observed
        `version` of the target `ProductComponent`. A mismatch with the component's
        current `version` is rejected with `ERR_STALE_COMPONENT_VERSION` (HTTP 412)."
        PRD §2.5: "Again the reason is supersession: a new assessment for the same
        component-and-criterion pair silently retires the previous one, so a writer
        whose view of the component's coverage, assessment state or evidence has been
        overtaken must re-read before authoring the superseding row."
        PRD §3.5: "A newly authored row begins with `attestation_state` at `DRAFT`,
        records the acting `X-User-ID` as its `authored_by_user_id`, and carries no
        `attested_by_user_id`, no `attested_at`, no `attestation_note` and no
        `superseded_by_assessment_id`."
        PRD §2.7: "7. Optimistic concurrency: `expected_product_version` on report
        creation and `expected_component_version` on assessment authoring —
        `ERR_STALE_PRODUCT_VERSION` or `ERR_STALE_COMPONENT_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_component_version_blocks_assessment_create
        """
        ctx = build_component_then_complete_a_run()
        fresh = read_component(ctx["component"]["id"])

        assert fresh["coverage_pct"] == pytest.approx(FULL_SWEEP_COVERAGE_PCT, abs=0.01), (
            f"the completed sweep wrote 45.00 onto the component, got {fresh['coverage_pct']}"
        )
        assert fresh["version"] > ctx["stale_version"], (
            "the completion advanced the component, got "
            f"{fresh['version']} against {ctx['stale_version']}"
        )

        validate_error(
            api.create_assessment(
                assessment_payload(
                    ctx["component"]["id"],
                    ctx["criterion"]["id"],
                    ctx["stale_version"],
                    support_level="SUPPORTS",
                ),
                TESTER,
            ),
            "ERR_STALE_COMPONENT_VERSION",
            412,
        )

        accepted = validate_success(
            api.create_assessment(
                assessment_payload(
                    ctx["component"]["id"],
                    ctx["criterion"]["id"],
                    fresh["version"],
                    support_level="SUPPORTS",
                ),
                TESTER,
            ),
            201,
        )

        assert accepted["attestation_state"] == "DRAFT", (
            f"the retry authors the row, got {accepted['attestation_state']}"
        )
        assert accepted["authored_by_user_id"] == TESTER_USER_ID, (
            "the acting operator identifier is recorded as provenance, got "
            f"{accepted['authored_by_user_id']}"
        )


class TestInScopeDenominator:
    """An excluded component never enters the readiness denominator."""

    def test_an_excluded_component_does_not_hold_readiness_back(self, api):
        """PRD §3.1: "The two component counters have precise definitions that matter
        downstream: `components_in_scope_count` is the number of the product's
        components whose in-scope flag is true, and `components_complete_count` is
        the number of those in-scope components whose assessment dimension has
        reached `COMPLETE`."
        PRD §3.1: "From them, `assessment_readiness` is `READY` when the product has
        at least one in-scope component and every in-scope component is complete, and
        `NOT_READY` in every other case, including the case of an empty inventory."
        PRD §3.3: "Scheduling the first run for a component is what starts its
        testing dimension: the component moves `PLANNED → IN_TESTING`, provided its
        declared `assessment_scope` is not `EXCLUDED` — a component declared out of
        assessment depth stays at `PLANNED` no matter how many runs are booked
        against it."
        PRD §3.4: "A component whose recomputed `coverage_pct` is at least 45.00
        qualifies as `COMPLETE`; a component whose recomputed `coverage_pct` falls
        below 45.00 does not."

        Design: Corner/cross_cutting_complexity_layers/corner_derived_component_counters_ignore_out_of_scope_rows
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
        in_scope = create_component(
            product["id"],
            name="Web UI",
            component_type="WEB_UI",
            in_scope=True,
            assessment_scope="FULL",
            applicable_criteria_count=APPLICABLE_CRITERIA,
            user_reach_pct=60,
        )

        assert read_product(product["id"])["components_in_scope_count"] == 1

        excluded = create_component(
            product["id"],
            name="Legacy Batch Job",
            component_type="DOCUMENTATION",
            in_scope=False,
            assessment_scope="EXCLUDED",
            applicable_criteria_count=EXCLUDED_CRITERIA_COUNT,
            user_reach_pct=EXCLUDED_REACH_PCT,
        )

        assert read_product(product["id"])["components_in_scope_count"] == 1, (
            "the excluded component is not counted in scope"
        )

        bench = create_environment(
            name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
        )
        run = schedule_run(
            in_scope["id"],
            bench["id"],
            method="MANUAL",
            at_profile="SCREEN_READER",
            scheduled_start=RUN_WINDOW[0],
            scheduled_end=RUN_WINDOW[1],
            criteria_exercised=APPLICABLE_CRITERIA,
            disability_categories_validated=["VISION"],
        )
        complete_run(run["id"], defects_found=0)

        product_after = read_product(product["id"])
        assert product_after["components_in_scope_count"] == 1
        assert product_after["components_complete_count"] == 1, (
            "the one in-scope component reached the floor, got "
            f"{product_after['components_complete_count']}"
        )
        assert product_after["assessment_readiness"] == "READY", (
            "completing the whole in-scope inventory is enough, even with an excluded "
            f"component present, got {product_after['assessment_readiness']}"
        )
        assert read_component(excluded["id"])["assessment_state"] == "PLANNED", (
            "the excluded component was never taken into testing"
        )
        assert read_component(in_scope["id"])["assessment_state"] == "COMPLETE"
