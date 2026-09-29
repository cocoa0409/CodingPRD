"""Two conserved quantities checked on both sides of a compensating operation:
the remediation budget across allocate and deallocate, and testing evidence
across completion and voiding."""

import pytest

from test_helpers import (
    TESTER,
    allocate_budget,
    assert_budget_conservation,
    assert_evidence_conservation,
    complete_run,
    commit_issue,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    deallocate_budget_payload,
    expected_budget_ask_cents,
    expected_coverage_pct,
    log_issue,
    read_component,
    read_known_issue,
    read_product,
    read_release_train,
    read_run,
    schedule_run,
    triage_issue,
    validate_success,
    void_run_payload,
    LEAD,
)

# One effort point asks 18750 cents uplifted by 1.0725, that is 20109.375 cents,
# rounded half-up to 20109 for that issue; three such asks exhaust 60327 exactly.
TRAIN_BUDGET_CENTS = 60327
ASK_PER_POINT_CENTS = 20109

# The screen-reader sweep covers all 40 applicable criteria; the keyboard run
# covers 20 of them, so the two together score 0.45 + 0.35 x 0.5 = 0.625.
APPLICABLE_CRITERIA = 40
KEYBOARD_CRITERIA = 20

SR_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
KB_WINDOW = ("2026-08-04T09:00:00Z", "2026-08-04T11:00:00Z")


def build_base_inventory():
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
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
    }


def build_fully_allocated_train():
    """Three one-point issues committed to a train whose budget they exhaust."""
    ctx = build_base_inventory()
    train = create_release_train(
        name="Train 2026.09",
        window_start="2026-09-01",
        window_end="2026-09-30",
        freeze_days=5,
        effort_capacity_points=10,
        remediation_budget_cents=TRAIN_BUDGET_CENTS,
    )
    issues = {}
    for severity, summary in (
        ("BLOCKER", "Primary navigation is unreachable by keyboard"),
        ("SERIOUS", "Media library thumbnails expose no accessible name"),
        ("MODERATE", "Status messages are not announced politely"),
    ):
        issue = log_issue(
            ctx["product"]["id"],
            ctx["component"]["id"],
            ctx["criterion"]["id"],
            severity=severity,
            effort_points=1,
            target_remediation_date="2026-09-10",
            publish_intent="INCLUDED",
            summary=summary,
        )
        triage_issue(issue["id"], triage_note="Reproduced on Windows and macOS")
        commit_issue(issue["id"], train["id"])
        issues[severity] = issue
    allocated = allocate_budget(train["id"], ctx["product"]["id"])
    return {**ctx, "train": train, "issues": issues, "allocated": allocated}


def build_component_with_two_completed_manual_runs():
    """A screen-reader sweep and a keyboard run, both COMPLETED and credited."""
    ctx = build_base_inventory()
    sr_bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    kb_bench = create_environment(
        name="Keyboard Bench 1",
        at_profile="KEYBOARD",
        at_product_name="Keyboard only",
        reconfiguration_buffer_minutes=30,
    )
    sr_run = schedule_run(
        ctx["component"]["id"],
        sr_bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start=SR_WINDOW[0],
        scheduled_end=SR_WINDOW[1],
        criteria_exercised=APPLICABLE_CRITERIA,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    complete_run(sr_run["id"], defects_found=3)
    component_after_first = read_component(ctx["component"]["id"])
    kb_run = schedule_run(
        ctx["component"]["id"],
        kb_bench["id"],
        method="MANUAL",
        at_profile="KEYBOARD",
        scheduled_start=KB_WINDOW[0],
        scheduled_end=KB_WINDOW[1],
        criteria_exercised=KEYBOARD_CRITERIA,
        disability_categories_validated=["MOTOR"],
    )
    complete_run(kb_run["id"], defects_found=5)
    return {
        **ctx,
        "sr_bench": sr_bench,
        "kb_bench": kb_bench,
        "sr_run": sr_run,
        "kb_run": kb_run,
        "component_after_first": component_after_first,
        "component_at_peak": read_component(ctx["component"]["id"]),
    }


class TestRemediationBudgetIsConserved:
    """Money is neither created nor destroyed by the waterfall or its reversal."""

    def test_the_waterfall_spends_the_whole_budget_without_drift(self, api):
        """PRD §3.9: "Each candidate's ask is its `effort_points` multiplied by the
        standard remediation rate of 187 dollars 50 cents per effort point — that
        is, 18750 cents per point — multiplied by the programme overhead factor of
        1.0725, which is a 7.25 percent uplift; that product is rounded half-up to
        whole cents **for that issue** before anything is spent."
        PRD §3.9: "When the waterfall finishes, the train's `unallocated_cents`
        becomes the untouched remainder and its `allocation_state` becomes
        `ALLOCATED`."
        PRD §3.9: "The invariant that the train's `remediation_budget_cents`
        equals its `unallocated_cents` plus the sum of its issues' `funded_cents`
        holds before, during and after both operations."
        PRD §3.9: "Its `funding_state` becomes `FULLY_FUNDED` when the grant
        equals the rounded ask and is greater than zero, `PARTIALLY_FUNDED` when
        the grant is greater than zero but short of the ask, and `UNFUNDED` when
        the grant is zero."

        Design: Difficulty/compensating_invariant/remediation_budget_conservation
        """
        ctx = build_fully_allocated_train()

        assert expected_budget_ask_cents(1) == ASK_PER_POINT_CENTS, (
            "one point asks 20109 cents once its own ask is rounded, got "
            f"{expected_budget_ask_cents(1)}"
        )
        assert ctx["allocated"]["unallocated_cents"] == 0, (
            "three grants of 20109 exhaust the 60327-cent budget exactly, got "
            f"{ctx['allocated']['unallocated_cents']}"
        )
        assert ctx["allocated"]["allocation_state"] == "ALLOCATED"

        funded_total = 0
        for severity, issue in ctx["issues"].items():
            row = read_known_issue(issue["id"])
            assert row["funded_cents"] == ASK_PER_POINT_CENTS, (
                f"the {severity} issue is granted its whole rounded ask, got "
                f"{row['funded_cents']}"
            )
            assert row["funding_state"] == "FULLY_FUNDED"
            funded_total += row["funded_cents"]

        assert funded_total == TRAIN_BUDGET_CENTS, (
            f"the three grants sum to the whole budget, got {funded_total}"
        )
        assert_budget_conservation(read_release_train(ctx["train"]["id"]), funded_total)

    def test_deallocation_returns_every_cent_but_no_capacity(self, api):
        """PRD §3.9: "Every affected issue's `funded_cents` returns to 0 and its
        `funding_state` returns to `UNFUNDED`, the train's `unallocated_cents`
        rises by exactly the reclaimed total, and `allocation_state` returns to
        `UNALLOCATED`."
        PRD §3.9: "The invariant that the train's `remediation_budget_cents`
        equals its `unallocated_cents` plus the sum of its issues' `funded_cents`
        holds before, during and after both operations."
        PRD §3.9: "Thereafter `committed_effort_points` always equals the sum of
        `effort_points` over the train's issues in states `COMMITTED` and
        `PUBLISHED_COMMITTED`, and `unallocated_cents` always equals
        `remediation_budget_cents` minus the sum of `funded_cents` over the
        train's issues."

        Design: Difficulty/compensating_invariant/remediation_budget_conservation
        """
        ctx = build_fully_allocated_train()

        reversed_train = validate_success(
            api.deallocate_budget(
                ctx["train"]["id"],
                deallocate_budget_payload(
                    ctx["product"]["id"], "Train scope pulled back for re-planning"
                ),
                LEAD,
            )
        )

        assert reversed_train["unallocated_cents"] == TRAIN_BUDGET_CENTS, (
            "every granted cent comes back, with no rounding drift left behind, got "
            f"{reversed_train['unallocated_cents']}"
        )
        assert reversed_train["allocation_state"] == "UNALLOCATED"
        for severity, issue in ctx["issues"].items():
            row = read_known_issue(issue["id"])
            assert row["funded_cents"] == 0, (
                f"the {severity} issue keeps nothing, got {row['funded_cents']}"
            )
            assert row["funding_state"] == "UNFUNDED"
        assert_budget_conservation(reversed_train, 0)
        assert reversed_train["committed_effort_points"] == 3, (
            "deallocation returns money, not capacity, got "
            f"{reversed_train['committed_effort_points']}"
        )


class TestEvidenceUnitsAreConserved:
    """Voiding a run returns the component to exactly the evidence it held before."""

    def test_the_second_completed_run_adds_exactly_its_exercised_criteria(self, api):
        """PRD §3.4: "On success the run moves `SCHEDULED → COMPLETED`, its
        `completed_at` is stamped from the logical clock, and the cascade begins:
        the component's `evidence_units_total` rises by exactly this run's
        `criteria_exercised` (that field is always the sum of `criteria_exercised`
        over the component's `COMPLETED` runs), the component's `coverage_pct` is
        recomputed, and the component's `validated_disability_categories` is
        rebuilt as the union of `disability_categories_validated` over the
        component's `COMPLETED` runs whose `method` is `MANUAL` — automated runs
        contribute nothing at all to validated categories, however many criteria
        they exercise."
        PRD §3.4: "The three profile scores are combined with fixed weights — 45
        percent of the score for `SCREEN_READER`, 35 percent for `KEYBOARD` and 20
        percent for `MAGNIFICATION` — and the weighted sum is multiplied by 100 to
        yield a percentage."

        Design: Difficulty/compensating_invariant/evidence_units_conservation
        """
        ctx = build_component_with_two_completed_manual_runs()

        assert_evidence_conservation(ctx["component_after_first"], APPLICABLE_CRITERIA)
        assert ctx["component_after_first"]["coverage_pct"] == pytest.approx(45.00, abs=0.01), (
            "the screen-reader sweep alone scores 45.00, got "
            f"{ctx['component_after_first']['coverage_pct']}"
        )

        peak_expected = expected_coverage_pct(
            APPLICABLE_CRITERIA,
            [
                {
                    "method": "MANUAL",
                    "at_profile": "SCREEN_READER",
                    "criteria_exercised": APPLICABLE_CRITERIA,
                },
                {
                    "method": "MANUAL",
                    "at_profile": "KEYBOARD",
                    "criteria_exercised": KEYBOARD_CRITERIA,
                },
            ],
        )
        assert peak_expected == pytest.approx(62.50, abs=0.01)
        assert_evidence_conservation(
            ctx["component_at_peak"], APPLICABLE_CRITERIA + KEYBOARD_CRITERIA
        )
        assert ctx["component_at_peak"]["coverage_pct"] == pytest.approx(peak_expected, abs=0.01), (
            "0.45 plus 0.35 times one half is 0.625, got "
            f"{ctx['component_at_peak']['coverage_pct']}"
        )
        assert sorted(ctx["component_at_peak"]["validated_disability_categories"]) == [
            "COGNITIVE",
            "MOTOR",
            "VISION",
        ], (
            "the union over both manual runs carries all three categories, got "
            f"{ctx['component_at_peak']['validated_disability_categories']}"
        )

    def test_voiding_the_keyboard_run_restores_the_earlier_totals_exactly(self, api):
        """PRD §3.4: "The component's `evidence_units_total` decreases by exactly
        the `criteria_exercised` that run had contributed — never by an
        approximation and never by a recomputed guess."
        PRD §3.4: "`coverage_pct` is then recomputed from the remaining
        `COMPLETED` runs, and `validated_disability_categories` is rebuilt as the
        union over the component's remaining `COMPLETED` `MANUAL` runs, so voiding
        the only manual run for a profile can both drop the category union and
        reintroduce that profile's automated-only cap."
        PRD §3.4: "If the recomputed `coverage_pct` has fallen below 45.00, the
        component reverts `COMPLETE → IN_TESTING`, and that reversion in turn
        flips every `ATTESTED` criterion assessment on that component to
        `NEEDS_REVALIDATION`."

        Design: Difficulty/compensating_invariant/evidence_units_conservation
        """
        ctx = build_component_with_two_completed_manual_runs()

        voided = validate_success(
            api.void_run(
                ctx["kb_run"]["id"],
                void_run_payload("Keyboard bench had a stuck modifier key throughout the session"),
                TESTER,
            )
        )

        assert voided["status"] == "VOID"
        component = read_component(ctx["component"]["id"])
        assert_evidence_conservation(component, APPLICABLE_CRITERIA)
        assert component["evidence_units_total"] == (
            ctx["component_at_peak"]["evidence_units_total"] - KEYBOARD_CRITERIA
        ), (
            "exactly the keyboard run's 20 units are withdrawn, got "
            f"{component['evidence_units_total']}"
        )
        assert component["coverage_pct"] == pytest.approx(45.00, abs=0.01), (
            "the surviving screen-reader sweep scores 45.00 again, got "
            f"{component['coverage_pct']}"
        )
        assert component["assessment_state"] == "COMPLETE", (
            "45.00 still meets the attestation floor, so no reversion fires, got "
            f"{component['assessment_state']}"
        )
        assert sorted(component["validated_disability_categories"]) == ["COGNITIVE", "VISION"], (
            "the union is rebuilt from the surviving manual run, so MOTOR is gone, got "
            f"{component['validated_disability_categories']}"
        )
        assert read_run(ctx["sr_run"]["id"])["status"] == "COMPLETED", (
            "voiding one run leaves the other untouched"
        )
        assert read_product(ctx["product"]["id"])["components_complete_count"] == 1
