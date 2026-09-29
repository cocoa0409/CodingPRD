"""Three deep cascades, each triggered by a different call: completing a run,
voiding a completed run, and publishing a report."""

import pytest

from test_helpers import (
    LEAD,
    TESTER,
    attest_assessment,
    author_assessment,
    commit_issue,
    complete_run_payload,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    complete_run,
    draft_questionnaire,
    log_issue,
    open_report,
    publication_payload,
    read_assessment,
    read_component,
    read_known_issue,
    read_product,
    read_questionnaire,
    record_design_review,
    schedule_run,
    set_clock,
    submit_report,
    triage_issue,
    approve_report,
    validate_success,
    void_run_payload,
)

# The bench window used by every scenario in this module; the buffer of 30
# minutes is irrelevant because no scenario books the bench twice.
RUN_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")


def build_standard_product_and_component(with_criterion: bool = True):
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = None
    if with_criterion:
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
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "bench": bench,
    }


def build_scheduled_manual_run():
    """A component sitting at IN_TESTING with its only run still SCHEDULED."""
    ctx = build_standard_product_and_component(with_criterion=False)
    run = schedule_run(
        ctx["component"]["id"],
        ctx["bench"]["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start=RUN_WINDOW[0],
        scheduled_end=RUN_WINDOW[1],
        criteria_exercised=40,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    return {**ctx, "run": run, "component_before": read_component(ctx["component"]["id"])}


def build_attested_component_at_the_floor():
    """A COMPLETE component with one ATTESTED SUPPORTS row, so the index is 100.00."""
    ctx = build_standard_product_and_component()
    run = schedule_run(
        ctx["component"]["id"],
        ctx["bench"]["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start=RUN_WINDOW[0],
        scheduled_end=RUN_WINDOW[1],
        criteria_exercised=40,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    complete_run(run["id"], defects_found=3)
    assessment = author_assessment(
        ctx["component"]["id"], ctx["criterion"]["id"], support_level="SUPPORTS"
    )
    attest_assessment(assessment["id"], attestation_note="Reproduced with NVDA 2026.1")
    return {
        **ctx,
        "run": run,
        "assessment": assessment,
        "product_before": read_product(ctx["product"]["id"]),
    }


def build_approved_report_with_overdue_committed_blocker():
    """An APPROVED report whose committed BLOCKER is already past its target date."""
    built = build_attested_component_at_the_floor()
    record_design_review(built["component"]["id"], "PASS", "Acceptance criteria include the AT matrix")
    train = create_release_train(
        name="Train 2026.08",
        window_start="2026-08-05",
        window_end="2026-08-20",
        freeze_days=2,
        effort_capacity_points=10,
        remediation_budget_cents=0,
    )
    issue = log_issue(
        built["product"]["id"],
        built["component"]["id"],
        built["criterion"]["id"],
        severity="BLOCKER",
        effort_points=2,
        target_remediation_date="2026-08-10",
        publish_intent="INCLUDED",
        summary="Primary navigation is unreachable by keyboard",
    )
    triage_issue(issue["id"], triage_note="Reproduced on Windows and macOS")
    commit_issue(issue["id"], train["id"])
    report = open_report(
        built["product"]["id"], built["standard"]["id"], report_title="ACR Insight Portal 7.0"
    )
    questionnaire = draft_questionnaire(
        built["product"]["id"],
        report["id"],
        customer_name="Northwind Health",
        questionnaire_kind="VPAT_ACR",
        answers_summary="Answers cite the ACR for release 7.0",
    )
    submit_report(report["id"], built["product"]["id"])
    approve_report(report["id"])

    set_clock("2026-09-01T00:00:00Z")
    return {
        **built,
        "train": train,
        "issue": issue,
        "report": report,
        "questionnaire": questionnaire,
        "product_at_approval": read_product(built["product"]["id"]),
    }


class TestRunCompletionReadinessChain:
    """Completing one run travels from the run to the product's readiness."""

    def test_completion_credits_evidence_and_carries_the_component_to_complete(self, api):
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
        PRD §3.3: "The run is created with `status` at `SCHEDULED`, with no
        `defects_found`, no `void_reason` and no `completed_at`; nothing is
        credited to coverage until the run is completed."

        Design: Difficulty/transitive_cascade/run_completion_readiness_chain
        """
        ctx = build_scheduled_manual_run()

        assert ctx["component_before"]["assessment_state"] == "IN_TESTING", (
            "scheduling the first run starts the testing dimension, got "
            f"{ctx['component_before']['assessment_state']}"
        )
        assert ctx["component_before"]["coverage_pct"] == pytest.approx(0.00, abs=0.01), (
            "a merely scheduled run credits nothing, got "
            f"{ctx['component_before']['coverage_pct']}"
        )

        completed = validate_success(
            api.complete_run(ctx["run"]["id"], complete_run_payload(3), TESTER)
        )

        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"].startswith("2026-08-01T00:00:00"), (
            f"completed_at is stamped from the logical clock, got {completed['completed_at']}"
        )
        component = read_component(ctx["component"]["id"])
        assert component["evidence_units_total"] == 40, (
            f"the run's 40 exercised criteria are credited, got {component['evidence_units_total']}"
        )
        assert component["coverage_pct"] == pytest.approx(45.00, abs=0.01), (
            f"a manual run over the whole scope scores 45.00, got {component['coverage_pct']}"
        )
        assert component["assessment_state"] == "COMPLETE"

    def test_the_component_reaching_complete_lifts_the_product_counters(self, api):
        """PRD §3.4: "If the recomputed coverage has reached the attestation
        floor, the component advances `IN_TESTING → COMPLETE`."
        PRD §3.4: "The product's `components_complete_count`,
        `assessment_readiness` and `publication_posture` are then rebuilt, and
        both the component's `version` and the product's `version` rise by 1."
        PRD §3.1: "From them, `assessment_readiness` is `READY` when the product
        has at least one in-scope component and every in-scope component is
        complete, and `NOT_READY` in every other case, including the case of an
        empty inventory."

        Design: Difficulty/transitive_cascade/run_completion_readiness_chain
        """
        ctx = build_scheduled_manual_run()
        product_before = read_product(ctx["product"]["id"])
        assert product_before["components_complete_count"] == 0
        assert product_before["assessment_readiness"] == "NOT_READY"

        validate_success(api.complete_run(ctx["run"]["id"], complete_run_payload(3), TESTER))

        product = read_product(ctx["product"]["id"])
        assert product["components_complete_count"] == 1, (
            "the only in-scope component is now complete, got "
            f"{product['components_complete_count']}"
        )
        assert product["assessment_readiness"] == "READY", (
            f"every in-scope component is complete, got {product['assessment_readiness']}"
        )
        assert product["components_in_scope_count"] == 1
        assert product["version"] == product_before["version"] + 1, (
            "completing a run raises the owning product's version by exactly 1, got "
            f"{product['version']} after {product_before['version']}"
        )


class TestRunVoidRevalidationChain:
    """Voiding the only completed run unwinds five hops of derived state."""

    def test_void_withdraws_the_evidence_and_drops_the_component_back(self, api):
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

        Design: Difficulty/transitive_cascade/run_void_revalidation_chain
        """
        ctx = build_attested_component_at_the_floor()
        assert ctx["product_before"]["conformance_index_provisional"] == pytest.approx(
            100.00, abs=0.01
        ), (
            "one ATTESTED SUPPORTS row over one in-scope criterion is 100.00, got "
            f"{ctx['product_before']['conformance_index_provisional']}"
        )

        voided = validate_success(
            api.void_run(
                ctx["run"]["id"],
                void_run_payload("Bench was running an unpatched screen reader build"),
                TESTER,
            )
        )

        assert voided["status"] == "VOID"
        component = read_component(ctx["component"]["id"])
        assert component["evidence_units_total"] == 0, (
            "exactly the 40 credited criteria are withdrawn, got "
            f"{component['evidence_units_total']}"
        )
        assert component["coverage_pct"] == pytest.approx(0.00, abs=0.01)
        assert component["validated_disability_categories"] == [], (
            "the union over the remaining manual runs is empty, got "
            f"{component['validated_disability_categories']}"
        )
        assert component["assessment_state"] == "IN_TESTING", (
            f"0.00 is below the 45.00 floor, got {component['assessment_state']}"
        )

    def test_the_reversion_invalidates_the_attested_row_and_erases_the_index(self, api):
        """PRD §3.5: "Attested evidence can go stale in two ways, and both drive
        the row `ATTESTED → NEEDS_REVALIDATION` without any client action: the
        owning component leaving `COMPLETE`, or the run the row cites as
        `evidence_run_id` being voided."
        PRD §3.5: "In that flip `attested_by_user_id` and `attested_at` are
        deliberately retained for audit, but the row stops qualifying as evidence
        for either conformance-index variant, and the product's
        `conformance_index_provisional` and `publication_posture` are rebuilt."
        PRD §3.8: "Note the guard on the index test: a product whose
        `assessed_criteria_count` is 0 is never `RESTRICTED` on index grounds,
        because a provisional index of 0.00 over an empty denominator says nothing
        about conformance — the index floor of 85.00 only bites once at least one
        criterion has been assessed."

        Design: Difficulty/transitive_cascade/run_void_revalidation_chain
        """
        ctx = build_attested_component_at_the_floor()

        validate_success(
            api.void_run(
                ctx["run"]["id"],
                void_run_payload("Bench was running an unpatched screen reader build"),
                TESTER,
            )
        )

        assessment = read_assessment(ctx["assessment"]["id"])
        assert assessment["attestation_state"] == "NEEDS_REVALIDATION", (
            "the component leaving COMPLETE invalidates its attested row, got "
            f"{assessment['attestation_state']}"
        )
        assert assessment["attested_by_user_id"] is not None, (
            "the attester is retained for audit after the flip"
        )
        product = read_product(ctx["product"]["id"])
        assert product["assessed_criteria_count"] == 0, (
            "a NEEDS_REVALIDATION row qualifies for neither variant, got "
            f"{product['assessed_criteria_count']}"
        )
        assert product["conformance_index_provisional"] == pytest.approx(0.00, abs=0.01)
        assert product["components_complete_count"] == 0
        assert product["publication_posture"] == "OPEN", (
            "with no assessed criterion the index floor cannot restrict the product, got "
            f"{product['publication_posture']}"
        )


class TestPublishFreezesCustomerDisclosuresChain:
    """Publication exposes an already-late blocker and freezes the product."""

    def test_publication_commits_the_included_issue_to_customers(self, api):
        """PRD §3.7: "The report moves `APPROVED → PUBLISHED`, its `published_at`
        is stamped from the logical clock, and `conformance_index_certified` and
        `criterion_support_snapshot` are frozen from the certified rollup of
        §3.6."
        PRD §3.7: "Every known issue of the same product that is in state
        `COMMITTED` with a `publish_intent` of `INCLUDED` moves `COMMITTED →
        PUBLISHED_COMMITTED`, has its `public_target_date` set by copying its
        internal `target_remediation_date`, and has its `published_report_id` set
        to this report; the number of issues moved this way is recorded on the
        report as `published_issue_count`."

        Design: Difficulty/transitive_cascade/publish_freezes_customer_disclosures_chain
        """
        ctx = build_approved_report_with_overdue_committed_blocker()
        assert ctx["product_at_approval"]["publication_posture"] == "OPEN"
        assert ctx["product_at_approval"]["overdue_committed_blocker_count"] == 0, (
            "a merely COMMITTED issue is not yet a public commitment, got "
            f"{ctx['product_at_approval']['overdue_committed_blocker_count']}"
        )

        published = validate_success(
            api.publish_report(
                ctx["report"]["id"], publication_payload("CUSTOMER_TRUST_PORTAL"), LEAD
            )
        )

        assert published["state"] == "PUBLISHED"
        assert published["conformance_index_certified"] == pytest.approx(100.00, abs=0.01), (
            "the single attested SUPPORTS row certifies the only in-scope criterion, got "
            f"{published['conformance_index_certified']}"
        )
        assert published["published_issue_count"] == 1, (
            f"one INCLUDED committed issue is disclosed, got {published['published_issue_count']}"
        )
        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["state"] == "PUBLISHED_COMMITTED"
        assert issue["public_target_date"] == "2026-08-10", (
            "the internal target date is copied to the customer-facing one, got "
            f"{issue['public_target_date']}"
        )
        assert issue["published_report_id"] == ctx["report"]["id"]

    def test_the_overdue_commitment_freezes_the_product_and_its_questionnaire(self, api):
        """PRD §3.7: "The product's `overdue_committed_blocker_count` is then
        rebuilt from the newly published commitments and its `publication_posture`
        re-derived, so a publication that exposes a blocker whose target date has
        already passed flips the very product it just certified to `FROZEN`."
        PRD §3.8: "If `overdue_committed_blocker_count` is at least 1, or
        `correction_required_questionnaire_count` is at least 1, the posture is
        `FROZEN`."
        PRD §3.8: "A transition into `FROZEN`, whether from `OPEN` or from
        `RESTRICTED`, flips every questionnaire response of that product whose
        accuracy dimension is `CURRENT` or `STALE` to `CORRECTION_REQUIRED`,
        setting each one's `correction_due_at` to 10 days after the logical clock
        and clearing its `update_due_at`."

        Design: Difficulty/transitive_cascade/publish_freezes_customer_disclosures_chain
        """
        ctx = build_approved_report_with_overdue_committed_blocker()

        validate_success(
            api.publish_report(
                ctx["report"]["id"], publication_payload("CUSTOMER_TRUST_PORTAL"), LEAD
            )
        )

        product = read_product(ctx["product"]["id"])
        assert product["overdue_committed_blocker_count"] == 1, (
            "the published BLOCKER's target date of 2026-08-10 is behind the clock's "
            f"2026-09-01, got {product['overdue_committed_blocker_count']}"
        )
        assert product["publication_posture"] == "FROZEN"
        questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
        assert questionnaire["accuracy_status"] == "CORRECTION_REQUIRED", (
            "the freeze cascades onto the CURRENT response, got "
            f"{questionnaire['accuracy_status']}"
        )
        assert questionnaire["correction_due_at"].startswith("2026-09-11T00:00:00"), (
            "ten days after the clock's 2026-09-01, got "
            f"{questionnaire['correction_due_at']}"
        )
        assert questionnaire["update_due_at"] is None
        assert product["correction_required_questionnaire_count"] == 1
