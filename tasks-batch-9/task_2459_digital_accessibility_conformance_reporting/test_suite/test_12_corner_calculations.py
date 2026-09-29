"""Calculation breadth: which rows feed a formula, a single-profile weight in
isolation, half-up rounding on a value that sits on a half cent, and the
staleness bucket constants of disclosure debt."""

import pytest

from test_helpers import (
    LIAISON,
    TESTER,
    complete_run,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_standard,
    draft_questionnaire,
    expected_disclosure_debt,
    expected_intake_risk_score,
    known_issue_payload,
    log_issue,
    open_report,
    read_component,
    read_product,
    read_questionnaire,
    read_run,
    schedule_run,
    set_clock,
    validate_success,
)

APPLICABLE_CRITERIA = 40

SR_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
KB_WINDOW = ("2026-08-04T09:00:00Z", "2026-08-04T12:00:00Z")

# A single manual run covering all 40 applicable criteria scores 1.00 on its own
# profile, so it contributes that profile's weight and nothing else: 45.00 for
# SCREEN_READER, 20.00 for MAGNIFICATION.
SCREEN_READER_ONLY_COVERAGE_PCT = 45.00
MAGNIFICATION_ONLY_COVERAGE_PCT = 20.00

# MINOR is 5 points, two protected categories give a breadth factor of 1.15, and
# a user_reach_pct of 8 gives a reach factor of 0.54: 5 x 1.15 x 0.54 = 3.105.
LOW_REACH_PCT = 8
EXACT_INTAKE_BASE = 3.105
HALF_UP_INTAKE_SCORE = 3.11

# One MINOR INCLUDED issue that is not yet overdue is a base debt of 1, which is
# the STANDARD tier; 35 days from the reference instant is one whole 30-day
# bucket at half a point per bucket.
BASE_DEBT = 1
DAYS_SINCE_REFERENCE = 35
STALE_CLOCK = "2026-09-05T00:00:00Z"


def build_component_with_two_benches():
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
    sr_bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    kb_bench = create_environment(
        name="Keyboard Bench 1",
        at_profile="KEYBOARD",
        at_product_name="Keyboard only",
        reconfiguration_buffer_minutes=30,
    )
    return {
        "standard": standard,
        "product": product,
        "component": component,
        "sr_bench": sr_bench,
        "kb_bench": kb_bench,
    }


def build_low_reach_component_on_a_two_category_criterion():
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
        name="Admin Console",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="SAMPLED",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=LOW_REACH_PCT,
    )
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
    }


def build_draft_questionnaire_thirty_five_days_old():
    ctx = build_low_reach_component_on_a_two_category_criterion()
    issue = log_issue(
        ctx["product"]["id"],
        ctx["component"]["id"],
        ctx["criterion"]["id"],
        severity="MINOR",
        effort_points=1,
        target_remediation_date="2026-12-01",
        publish_intent="INCLUDED",
        summary="Decorative icons expose redundant alternative text",
    )
    report = open_report(
        ctx["product"]["id"], ctx["standard"]["id"], report_title="ACR Insight Portal 7.0"
    )
    questionnaire = draft_questionnaire(
        ctx["product"]["id"],
        report["id"],
        customer_name="Northwind Health",
        questionnaire_kind="VPAT_ACR",
        answers_summary="Answers cite the ACR for release 7.0",
    )
    set_clock(STALE_CLOCK)
    return {**ctx, "issue": issue, "report": report, "questionnaire": questionnaire}


class TestCoverageInputSetFiltering:
    """Only COMPLETED runs feed coverage; a booking on the calendar feeds nothing."""

    def test_a_scheduled_keyboard_run_contributes_nothing_to_coverage(self, api):
        """PRD §3.4: "For each of the three profiles `SCREEN_READER`, `KEYBOARD` and
        `MAGNIFICATION`, take the automated evidence for that profile as the sum of
        `criteria_exercised` over the component's `COMPLETED` runs whose `method` is
        `AUTOMATED` and whose `at_profile` is that profile, and the manual evidence
        as the same sum restricted to `MANUAL` runs."
        PRD §3.4: "On success the run moves `SCHEDULED → COMPLETED`, its
        `completed_at` is stamped from the logical clock, and the cascade begins: the
        component's `evidence_units_total` rises by exactly this run's
        `criteria_exercised` (that field is always the sum of `criteria_exercised`
        over the component's `COMPLETED` runs), the component's `coverage_pct` is
        recomputed, and the component's `validated_disability_categories` is rebuilt
        as the union of `disability_categories_validated` over the component's
        `COMPLETED` runs whose `method` is `MANUAL` — automated runs contribute
        nothing at all to validated categories, however many criteria they exercise."

        Design: Corner/calculations/corner_coverage_counts_completed_runs_only
        """
        ctx = build_component_with_two_benches()
        sr_run = schedule_run(
            ctx["component"]["id"],
            ctx["sr_bench"]["id"],
            method="MANUAL",
            at_profile="SCREEN_READER",
            scheduled_start=SR_WINDOW[0],
            scheduled_end=SR_WINDOW[1],
            criteria_exercised=APPLICABLE_CRITERIA,
            disability_categories_validated=["VISION", "COGNITIVE"],
        )
        kb_run = schedule_run(
            ctx["component"]["id"],
            ctx["kb_bench"]["id"],
            method="MANUAL",
            at_profile="KEYBOARD",
            scheduled_start=KB_WINDOW[0],
            scheduled_end=KB_WINDOW[1],
            criteria_exercised=APPLICABLE_CRITERIA,
            disability_categories_validated=["MOTOR"],
        )

        complete_run(sr_run["id"], defects_found=2)

        assert read_run(kb_run["id"])["status"] == "SCHEDULED", (
            "the keyboard booking is still only booked"
        )
        component = read_component(ctx["component"]["id"])
        assert component["coverage_pct"] == pytest.approx(
            SCREEN_READER_ONLY_COVERAGE_PCT, abs=0.01
        ), (
            "counting the scheduled keyboard run would give 80.00 instead, got "
            f"{component['coverage_pct']}"
        )
        assert component["evidence_units_total"] == APPLICABLE_CRITERIA, (
            "only the completed run's 40 criteria are summed, got "
            f"{component['evidence_units_total']}"
        )
        assert sorted(component["validated_disability_categories"]) == [
            "COGNITIVE",
            "VISION",
        ], (
            "MOTOR belongs to the still-scheduled run and is absent, got "
            f"{component['validated_disability_categories']}"
        )


class TestProfileWeightsInIsolation:
    """One profile fully covered, the other two untouched."""

    def test_a_magnification_only_sweep_scores_exactly_its_own_weight(self, api):
        """PRD §3.4: "The three profile scores are combined with fixed weights — 45
        percent of the score for `SCREEN_READER`, 35 percent for `KEYBOARD` and 20
        percent for `MAGNIFICATION` — and the weighted sum is multiplied by 100 to
        yield a percentage."
        PRD §3.4: "The attestation floor is 45.00 percent."
        PRD §3.4: "A component whose recomputed `coverage_pct` is at least 45.00
        qualifies as `COMPLETE`; a component whose recomputed `coverage_pct` falls
        below 45.00 does not."
        PRD §3.1: "`components_complete_count` is the number of those in-scope
        components whose assessment dimension has reached `COMPLETE`."

        Design: Corner/calculations/corner_magnification_only_manual_evidence_weight
        """
        ctx = build_component_with_two_benches()
        mg_bench = create_environment(
            name="ZoomText Bench 1",
            at_profile="MAGNIFICATION",
            at_product_name="ZoomText 2026",
            reconfiguration_buffer_minutes=30,
        )
        mg_run = schedule_run(
            ctx["component"]["id"],
            mg_bench["id"],
            method="MANUAL",
            at_profile="MAGNIFICATION",
            scheduled_start=SR_WINDOW[0],
            scheduled_end=SR_WINDOW[1],
            criteria_exercised=APPLICABLE_CRITERIA,
            disability_categories_validated=["VISION"],
        )

        complete_run(mg_run["id"], defects_found=1)

        component = read_component(ctx["component"]["id"])
        assert component["coverage_pct"] == pytest.approx(
            MAGNIFICATION_ONLY_COVERAGE_PCT, abs=0.01
        ), (
            "a full magnification score carries 20 percent of the weighted sum, got "
            f"{component['coverage_pct']}"
        )
        assert component["assessment_state"] == "IN_TESTING", (
            "20.00 is below the 45.00 floor, so the component has not completed, got "
            f"{component['assessment_state']}"
        )
        assert read_product(ctx["product"]["id"])["components_complete_count"] == 0


class TestRoundingDirection:
    """A score whose exact value ends in a half must go up, not to even."""

    def test_an_intake_risk_score_on_a_half_cent_rounds_half_up(self, api):
        """PRD §3.9: "The severity contributes fixed points: 40 for `BLOCKER`, 25
        for `SERIOUS`, 12 for `MODERATE` and 5 for `MINOR`."
        PRD §3.9: "The breadth factor counts how many distinct disability
        categories the violated criterion protects — a number from 1 to 4, read
        from that criterion's `disability_categories` — and equals 1 plus fifteen
        hundredths for each category beyond the first, so a criterion protecting
        all four categories carries a breadth factor of 1.45."
        PRD §3.9: "The reach factor equals one half plus one half multiplied by the
        affected component's `user_reach_pct` divided by 100, so a component nobody
        touches still carries half weight and a component every user touches
        carries full weight."
        PRD §3.9: "Under the `INTAKE_ESTIMATE` variant — used when the issue is
        first logged and again at triage, before the prioritization board has
        looked at it — the `risk_score` is simply that base term rounded half-up to
        two decimal places, with no aging, no complaint amplification and no
        ceiling."

        Design: Corner/calculations/corner_intake_risk_score_rounds_half_up
        """
        ctx = build_low_reach_component_on_a_two_category_criterion()

        assert expected_intake_risk_score("MINOR", 2, LOW_REACH_PCT) == pytest.approx(
            HALF_UP_INTAKE_SCORE, abs=0.001
        ), "5 x 1.15 x 0.54 is exactly 3.105, which rounds half-up to 3.11"

        created = validate_success(
            api.create_known_issue(
                known_issue_payload(
                    ctx["product"]["id"],
                    ctx["component"]["id"],
                    ctx["criterion"]["id"],
                    severity="MINOR",
                    effort_points=1,
                    target_remediation_date="2026-12-01",
                    publish_intent="INCLUDED",
                    summary="Decorative icons expose redundant alternative text",
                ),
                TESTER,
            ),
            201,
        )

        assert created["risk_score"] == pytest.approx(HALF_UP_INTAKE_SCORE, abs=0.001), (
            f"round-half-even would report 3.10 instead, got {created['risk_score']}"
        )
        assert created["risk_score"] != pytest.approx(EXACT_INTAKE_BASE, abs=0.0001), (
            "the exact base term is rounded to two places before it is stored"
        )
        assert created["risk_variant"] == "INTAKE_ESTIMATE"
        assert created["state"] == "OPEN"


class TestDisclosureDebtConstants:
    """The staleness penalty is bucketed by whole 30-day periods, not by day."""

    def test_submitting_thirty_five_days_on_applies_exactly_one_bucket(self, api):
        """PRD §3.10: "First, the base debt is a sum over the product's known
        issues whose `publish_intent` is `INCLUDED` and whose state is `OPEN`,
        `TRIAGED`, `COMMITTED` or `PUBLISHED_COMMITTED`; issues that are `DEFERRED`
        or `RESOLVED`, and issues marked `EXCLUDED`, contribute nothing
        whatsoever."
        PRD §3.10: "Each contributing issue adds 8 points for `BLOCKER` severity, 5
        for `SERIOUS`, 3 for `MODERATE` and 1 for `MINOR`, plus a further overdue
        surcharge of 2 points when that issue's `target_remediation_date` is earlier
        than the logical clock's date."
        PRD §3.10: "Second, the tier is derived from that base debt **and from
        nothing else**: `STANDARD` when the base debt is 6 or less, `ELEVATED` when
        it is greater than 6 but 12 or less, and `CRITICAL` when it is greater than
        12."
        PRD §3.10: "Third, the staleness penalty is computed against a reference
        instant, which is `last_attested_at` when the response has ever been
        attested and the response's own `created_at` otherwise: count the whole days
        from that reference instant to the logical clock, divide by 30 discarding
        any remainder to obtain a bucket number, cap that bucket at 4, and multiply
        it by the tier's penalty rate — half a point per bucket at `STANDARD`, one
        point per bucket at `ELEVATED`, two points per bucket at `CRITICAL`."
        PRD §3.10: "It moves `review_status` `DRAFT → SUBMITTED`, stamps
        `submitted_at` from the logical clock, and computes `disclosure_debt` and
        `disclosure_tier` for the first time."

        Design: Corner/calculations/corner_disclosure_debt_staleness_bucket_constants
        """
        ctx = build_draft_questionnaire_thirty_five_days_old()

        expected = expected_disclosure_debt(BASE_DEBT, DAYS_SINCE_REFERENCE)
        assert expected == pytest.approx(1.50, abs=0.001), (
            "one whole bucket at half a point on a base debt of 1 gives 1.50"
        )

        submitted = validate_success(
            api.submit_questionnaire(ctx["questionnaire"]["id"], {}, LIAISON)
        )

        assert submitted["review_status"] == "SUBMITTED"
        assert submitted["disclosure_debt"] == pytest.approx(expected, abs=0.01), (
            "a per-day penalty or an un-bucketed debt would not give 1.50, got "
            f"{submitted['disclosure_debt']}"
        )
        assert submitted["disclosure_tier"] == "STANDARD", (
            "the tier keys on the base debt of 1 alone, got "
            f"{submitted['disclosure_tier']}"
        )
        stored = read_questionnaire(ctx["questionnaire"]["id"])
        assert stored["submitted_at"].startswith("2026-09-05T00:00:00"), (
            f"submission is stamped from the moved clock, got {stored['submitted_at']}"
        )
