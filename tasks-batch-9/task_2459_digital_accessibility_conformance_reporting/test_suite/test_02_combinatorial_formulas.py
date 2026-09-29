"""Formulas whose answer depends on several inputs interacting: the weighted
coverage score with its conditional automated-only cap, the remediation budget
waterfall that rounds each ask before spending, and the questionnaire disclosure
debt whose tier is keyed on a partial figure."""

import pytest

from test_helpers import (
    LEAD,
    allocate_budget_payload,
    commit_issue,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    draft_questionnaire,
    expected_coverage_pct,
    expected_budget_ask_cents,
    expected_debt_base,
    expected_debt_tier,
    expected_disclosure_debt,
    log_issue,
    open_report,
    read_component,
    read_known_issue,
    read_questionnaire,
    read_release_train,
    round_half_up_cents,
    schedule_and_complete_run,
    set_clock,
    submit_questionnaire,
    triage_issue,
    validate_success,
)

# One screen-reader bench is booked three times in a row; the windows are spaced
# more than the bench's 30-minute reconfiguration buffer apart so that no
# booking conflicts with its predecessor.
FIRST_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
SECOND_WINDOW = ("2026-08-03T13:00:00Z", "2026-08-03T15:00:00Z")
THIRD_WINDOW = ("2026-08-03T16:00:00Z", "2026-08-03T18:00:00Z")


def build_component_with_two_automated_screen_reader_runs():
    """A component whose only evidence is two completed AUTOMATED screen-reader runs.

    Both runs exercise all 40 applicable criteria, so the screen-reader profile's
    raw score saturates and the profile is priced entirely by the automated-only
    cap.
    """
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
    bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    first = schedule_and_complete_run(
        component["id"],
        bench["id"],
        method="AUTOMATED",
        at_profile="SCREEN_READER",
        criteria_exercised=40,
        disability_categories_validated=["VISION"],
        scheduled_start=FIRST_WINDOW[0],
        scheduled_end=FIRST_WINDOW[1],
        defects_found=3,
    )
    second = schedule_and_complete_run(
        component["id"],
        bench["id"],
        method="AUTOMATED",
        at_profile="SCREEN_READER",
        criteria_exercised=40,
        disability_categories_validated=["VISION"],
        scheduled_start=SECOND_WINDOW[0],
        scheduled_end=SECOND_WINDOW[1],
        defects_found=1,
    )
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "bench": bench,
        "automated_runs": [first, second],
    }


def build_three_one_point_issues_committed_to_one_train():
    """Three single-point issues of descending risk committed to one train.

    The train's budget of 60327 cents is exactly three times the per-issue ask
    rounded to whole cents, so the waterfall exhausts the budget to the cent only
    when each ask is rounded before it is spent.
    """
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
        name="2026.09",
        window_start="2026-09-01",
        window_end="2026-09-30",
        effort_capacity_points=10,
        remediation_budget_cents=60327,
    )
    issues = []
    for severity, summary in (
        ("BLOCKER", "Checkout cannot be completed with a screen reader at all"),
        ("SERIOUS", "Library thumbnails expose no accessible name to assistive tech"),
        ("MODERATE", "Focus outline is hard to see on the secondary navigation"),
    ):
        issue = log_issue(
            product["id"],
            component["id"],
            criterion["id"],
            severity=severity,
            effort_points=1,
            target_remediation_date="2026-09-15",
            publish_intent="INCLUDED",
            summary=summary,
        )
        triage_issue(issue["id"])
        commit_issue(issue["id"], train["id"])
        issues.append(issue)
    return {"product": product, "component": component, "train": train, "issues": issues}


def build_submitted_questionnaire_with_overdue_blocker_and_minor():
    """A submitted questionnaire on a product carrying one overdue BLOCKER and one MINOR.

    The clock is moved 65 days past the response's creation before the issues are
    logged, so the debt is rebuilt with a two-bucket staleness penalty on top of
    a base debt of 11 points.
    """
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
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    questionnaire = draft_questionnaire(product["id"], report["id"])
    submit_questionnaire(questionnaire["id"])

    set_clock("2026-10-05T00:00:00Z")
    blocker = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="BLOCKER",
        effort_points=8,
        target_remediation_date="2026-09-01",
        publish_intent="INCLUDED",
        summary="Screen reader users cannot complete the checkout journey",
    )
    minor = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="MINOR",
        effort_points=1,
        target_remediation_date="2026-11-15",
        publish_intent="INCLUDED",
        summary="Decorative divider images carry a redundant alt text",
    )
    return {
        "product": product,
        "component": component,
        "report": report,
        "questionnaire": questionnaire,
        "blocker": blocker,
        "minor": minor,
    }


class TestCoverageWeightedScoringAutomatedCapBranch:
    """The conditional per-profile cap inside the weighted coverage score."""

    def test_automated_only_profile_is_held_at_the_lower_cap(self, api):
        """PRD §3.4: "Automated evidence earns four tenths of a criterion of
        credit per criterion exercised, while manual evidence earns full credit,
        so the profile's raw score is the sum of four tenths of the automated
        evidence plus the whole of the manual evidence, divided by the
        denominator, and then capped at 1."
        PRD §3.4: "A second cap then applies conditionally: a profile with no
        manual evidence at all may not score above 0.60, whereas a profile with
        any manual evidence is capped only at 1.00."
        PRD §3.4: "The three profile scores are combined with fixed weights — 45
        percent of the score for `SCREEN_READER`, 35 percent for `KEYBOARD` and
        20 percent for `MAGNIFICATION` — and the weighted sum is multiplied by
        100 to yield a percentage."
        PRD §3.4: "A component whose recomputed `coverage_pct` is at least 45.00
        qualifies as `COMPLETE`; a component whose recomputed `coverage_pct`
        falls below 45.00 does not."

        Design: Difficulty/combinatorial_formula/coverage_weighted_scoring_automated_cap_branch
        """
        ctx = build_component_with_two_automated_screen_reader_runs()

        component = read_component(ctx["component"]["id"])

        expected = expected_coverage_pct(
            40,
            [
                {"method": "AUTOMATED", "at_profile": "SCREEN_READER", "criteria_exercised": 40},
                {"method": "AUTOMATED", "at_profile": "SCREEN_READER", "criteria_exercised": 40},
            ],
        )
        assert expected == pytest.approx(27.00, abs=0.01)
        assert component["coverage_pct"] == pytest.approx(expected, abs=0.01), (
            "80 automated criteria over a denominator of 40 saturate the raw score, so the "
            "0.60 automated-only cap times the 0.45 screen-reader weight gives 27.00, got "
            f"{component['coverage_pct']}"
        )
        assert component["assessment_state"] == "IN_TESTING", (
            "27.00 is below the 45.00 attestation floor, so the component may not be COMPLETE, "
            f"got {component['assessment_state']}"
        )
        assert component["evidence_units_total"] == 80
        assert component["validated_disability_categories"] == [], (
            "automated runs contribute nothing to validated categories, got "
            f"{component['validated_disability_categories']}"
        )

    def test_one_manual_run_lifts_the_same_profile_to_the_higher_cap(self, api):
        """PRD §3.4: "A second cap then applies conditionally: a profile with no
        manual evidence at all may not score above 0.60, whereas a profile with
        any manual evidence is capped only at 1.00."
        PRD §3.4: "the component's `evidence_units_total` rises by exactly this
        run's `criteria_exercised` (that field is always the sum of
        `criteria_exercised` over the component's `COMPLETED` runs), the
        component's `coverage_pct` is recomputed, and the component's
        `validated_disability_categories` is rebuilt as the union of
        `disability_categories_validated` over the component's `COMPLETED` runs
        whose `method` is `MANUAL` — automated runs contribute nothing at all to
        validated categories, however many criteria they exercise."
        PRD §3.4: "If the recomputed coverage has reached the attestation floor,
        the component advances `IN_TESTING → COMPLETE`."

        Design: Difficulty/combinatorial_formula/coverage_weighted_scoring_automated_cap_branch
        """
        ctx = build_component_with_two_automated_screen_reader_runs()

        schedule_and_complete_run(
            ctx["component"]["id"],
            ctx["bench"]["id"],
            method="MANUAL",
            at_profile="SCREEN_READER",
            criteria_exercised=40,
            disability_categories_validated=["VISION", "COGNITIVE"],
            scheduled_start=THIRD_WINDOW[0],
            scheduled_end=THIRD_WINDOW[1],
            defects_found=3,
        )
        component = read_component(ctx["component"]["id"])

        expected = expected_coverage_pct(
            40,
            [
                {"method": "AUTOMATED", "at_profile": "SCREEN_READER", "criteria_exercised": 40},
                {"method": "AUTOMATED", "at_profile": "SCREEN_READER", "criteria_exercised": 40},
                {"method": "MANUAL", "at_profile": "SCREEN_READER", "criteria_exercised": 40},
            ],
        )
        assert expected == pytest.approx(45.00, abs=0.01)
        assert component["coverage_pct"] == pytest.approx(expected, abs=0.01), (
            "with manual evidence present the profile is capped at 1.00, so the score is the "
            f"0.45 screen-reader weight alone, expected 45.00, got {component['coverage_pct']}"
        )
        assert component["evidence_units_total"] == 120, (
            "40 plus 40 plus 40 exercised criteria are credited exactly once each, got "
            f"{component['evidence_units_total']}"
        )
        assert component["assessment_state"] == "COMPLETE"
        assert sorted(component["validated_disability_categories"]) == ["COGNITIVE", "VISION"], (
            "only the MANUAL run's categories are unioned, got "
            f"{component['validated_disability_categories']}"
        )


class TestBudgetWaterfallRoundsPerIssue:
    """Each ask is rounded to whole cents before the waterfall spends anything."""

    def test_three_rounded_asks_exhaust_the_budget_to_the_cent(self, api):
        """PRD §3.9: "Each candidate's ask is its `effort_points` multiplied by
        the standard remediation rate of 187 dollars 50 cents per effort point —
        that is, 18750 cents per point — multiplied by the programme overhead
        factor of 1.0725, which is a 7.25 percent uplift; that product is rounded
        half-up to whole cents **for that issue** before anything is spent."
        PRD §3.9: "The issue is then granted the smaller of the remaining balance
        and its rounded ask, and that grant becomes its `funded_cents`."
        PRD §3.9: "Its `funding_state` becomes `FULLY_FUNDED` when the grant
        equals the rounded ask and is greater than zero, `PARTIALLY_FUNDED` when
        the grant is greater than zero but short of the ask, and `UNFUNDED` when
        the grant is zero."
        PRD §3.9: "Rounding each ask before spending, rather than summing raw
        asks and rounding once, is normative: the two orders produce different
        splits for the issue that sits on the exhaustion boundary, and only the
        per-issue order is correct."

        Design: Difficulty/combinatorial_formula/budget_waterfall_rounds_per_issue_before_allocating
        """
        ctx = build_three_one_point_issues_committed_to_one_train()

        allocated = validate_success(
            api.allocate_budget(
                ctx["train"]["id"], allocate_budget_payload(ctx["product"]["id"]), LEAD
            )
        )

        ask = expected_budget_ask_cents(1)
        assert ask == 20109, "18750 times 1.0725 is 20109.375, which rounds half-up to 20109"
        assert round_half_up_cents(3 * 18750 * 1.0725) != 3 * ask, (
            "summing the raw asks and rounding the total would spend 60328 cents rather than "
            "60327, which is what makes this scenario discriminating"
        )
        for issue in ctx["issues"]:
            funded = read_known_issue(issue["id"])
            assert funded["funded_cents"] == ask, (
                f"each single-point issue is granted its rounded ask of {ask} cents, got "
                f"{funded['funded_cents']}"
            )
            assert funded["funding_state"] == "FULLY_FUNDED", (
                "a grant equal to the rounded ask is FULLY_FUNDED, got "
                f"{funded['funding_state']}"
            )
        assert allocated["unallocated_cents"] == 0, (
            "three rounded asks of 20109 consume the whole 60327-cent budget, got "
            f"{allocated['unallocated_cents']}"
        )
        assert allocated["allocation_state"] == "ALLOCATED"

    def test_committed_effort_and_budget_conservation_survive_the_waterfall(self, api):
        """PRD §3.9: "Thereafter `committed_effort_points` always equals the sum
        of `effort_points` over the train's issues in states `COMMITTED` and
        `PUBLISHED_COMMITTED`, and `unallocated_cents` always equals
        `remediation_budget_cents` minus the sum of `funded_cents` over the
        train's issues."
        PRD §3.9: "Candidates are then ordered into a strict total order: by
        `risk_score` descending, then by `target_remediation_date` ascending,
        then by `created_at` ascending."

        Design: Difficulty/combinatorial_formula/budget_waterfall_rounds_per_issue_before_allocating
        """
        ctx = build_three_one_point_issues_committed_to_one_train()

        validate_success(
            api.allocate_budget(
                ctx["train"]["id"], allocate_budget_payload(ctx["product"]["id"]), LEAD
            )
        )
        train = read_release_train(ctx["train"]["id"])
        funded = [read_known_issue(issue["id"]) for issue in ctx["issues"]]

        assert train["committed_effort_points"] == 3, (
            "three single-point issues sit in COMMITTED, got "
            f"{train['committed_effort_points']}"
        )
        assert train["unallocated_cents"] == train["remediation_budget_cents"] - sum(
            issue["funded_cents"] for issue in funded
        ), "the remainder plus the granted total must equal the train's whole budget"
        scores = [issue["risk_score"] for issue in funded]
        assert scores == sorted(scores, reverse=True), (
            "the BLOCKER, SERIOUS and MODERATE issues were logged in descending risk order, so "
            f"the waterfall served them in list order, got {scores}"
        )


class TestDisclosureDebtTierKeyedOnBaseDebtOnly:
    """The tier is read off the base debt, never off the final debt figure."""

    def test_tier_stays_elevated_although_the_final_debt_exceeds_twelve(self, api):
        """PRD §3.10: "Each contributing issue adds 8 points for `BLOCKER`
        severity, 5 for `SERIOUS`, 3 for `MODERATE` and 1 for `MINOR`, plus a
        further overdue surcharge of 2 points when that issue's
        `target_remediation_date` is earlier than the logical clock's date."
        PRD §3.10: "Second, the tier is derived from that base debt **and from
        nothing else**: `STANDARD` when the base debt is 6 or less, `ELEVATED`
        when it is greater than 6 but 12 or less, and `CRITICAL` when it is
        greater than 12."
        PRD §3.10: "The apparent circularity — a penalty that depends on a tier
        that depends on a debt figure — is resolved by keying the tier on the
        base debt only; recomputing the tier from the final `disclosure_debt`, or
        iterating the two to a fixed point, is forbidden and produces wrong
        answers."

        Design: Difficulty/combinatorial_formula/disclosure_debt_tier_keyed_on_base_debt_only
        """
        ctx = build_submitted_questionnaire_with_overdue_blocker_and_minor()

        questionnaire = read_questionnaire(ctx["questionnaire"]["id"])

        base = expected_debt_base(
            [{"severity": "BLOCKER", "overdue": True}, {"severity": "MINOR", "overdue": False}]
        )
        assert base == 11, "BLOCKER 8 plus the 2-point overdue surcharge plus MINOR 1 is 11"
        assert expected_debt_tier(base) == "ELEVATED"
        assert questionnaire["disclosure_tier"] == "ELEVATED", (
            "a base debt of 11 is greater than 6 and no greater than 12, so the tier is "
            f"ELEVATED even though the final debt is 13.00, got {questionnaire['disclosure_tier']}"
        )
        assert questionnaire["review_status"] == "SUBMITTED", (
            "rebuilding disclosure debt never moves the authoring dimension, got "
            f"{questionnaire['review_status']}"
        )

    def test_staleness_penalty_uses_the_elevated_rate_not_the_critical_one(self, api):
        """PRD §3.10: "Third, the staleness penalty is computed against a
        reference instant, which is `last_attested_at` when the response has ever
        been attested and the response's own `created_at` otherwise: count the
        whole days from that reference instant to the logical clock, divide by 30
        discarding any remainder to obtain a bucket number, cap that bucket at 4,
        and multiply it by the tier's penalty rate — half a point per bucket at
        `STANDARD`, one point per bucket at `ELEVATED`, two points per bucket at
        `CRITICAL`."
        PRD §3.10: "Fourth, `disclosure_debt` is the base debt plus that penalty,
        rounded half-up to two decimal places, and `disclosure_tier` is the tier
        from the second step."

        Design: Difficulty/combinatorial_formula/disclosure_debt_tier_keyed_on_base_debt_only
        """
        ctx = build_submitted_questionnaire_with_overdue_blocker_and_minor()

        questionnaire = read_questionnaire(ctx["questionnaire"]["id"])

        expected = expected_disclosure_debt(11, 65)
        assert expected == pytest.approx(13.00, abs=0.01)
        assert questionnaire["disclosure_debt"] == pytest.approx(expected, abs=0.01), (
            "65 whole days since creation is bucket 2, and at the ELEVATED rate of one point "
            f"per bucket the debt is 11 plus 2, expected 13.00, got "
            f"{questionnaire['disclosure_debt']}"
        )
        assert questionnaire["disclosure_debt"] != pytest.approx(15.00, abs=0.01), (
            "charging the CRITICAL rate of two points per bucket would give 15.00, which is the "
            "wrong answer the pinned evaluation order forbids"
        )
