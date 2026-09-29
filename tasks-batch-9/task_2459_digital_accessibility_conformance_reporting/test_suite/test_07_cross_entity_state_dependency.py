"""Three actions whose legality is decided by the state of a *different* entity:
attestation reads the component, questionnaire attestation reads the report, and
complaint closure reads the linked known issue."""

import pytest

from test_helpers import (
    LEAD,
    REVIEWER,
    REVIEWER_USER_ID,
    attest_assessment,
    attestation_payload,
    author_assessment,
    close_complaint_payload,
    commit_issue,
    complete_run,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    draft_questionnaire,
    intake_complaint,
    link_complaint_issue,
    log_issue,
    open_report,
    publication_payload,
    questionnaire_attestation_payload,
    read_assessment,
    read_complaint,
    read_component,
    read_known_issue,
    read_product,
    read_questionnaire,
    read_release_train,
    read_report,
    record_design_review,
    resolve_issue,
    schedule_run,
    submit_questionnaire,
    submit_report,
    triage_complaint,
    triage_issue,
    approve_report,
    validate_error,
    validate_success,
)

# The component declares 40 applicable criteria; one manual screen-reader run over
# all 40 scores 0.45 x 1.00 x 100 = 45.00, exactly the attestation floor.
APPLICABLE_CRITERIA = 40
RUN_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")

# 2026-08-01 plus 90 days is the quarterly refresh deadline stamped at
# questionnaire attestation.
UPDATE_DUE_AT_DATE = "2026-10-30"


def build_untested_component_with_a_draft_row():
    """A DRAFT assessment on a component that has no runs at all.

    The component is still `PLANNED`, so its own dimension — not anything about
    the assessment row — is what an attestation attempt has to answer to.
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
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    assessment = author_assessment(component["id"], criterion["id"], support_level="SUPPORTS")
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": read_component(component["id"]),
        "bench": bench,
        "assessment": assessment,
    }


def bring_the_component_to_complete(ctx):
    """Book and close the manual sweep that carries the component to COMPLETE."""
    run = schedule_run(
        ctx["component"]["id"],
        ctx["bench"]["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start=RUN_WINDOW[0],
        scheduled_end=RUN_WINDOW[1],
        criteria_exercised=APPLICABLE_CRITERIA,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    complete_run(run["id"], defects_found=3)
    return run


def build_submitted_questionnaire_citing_an_approved_report():
    """A SUBMITTED questionnaire whose cited report is APPROVED but not published."""
    ctx = build_untested_component_with_a_draft_row()
    run = bring_the_component_to_complete(ctx)
    attest_assessment(ctx["assessment"]["id"], attestation_note="Reproduced with NVDA 2026.1")
    record_design_review(
        ctx["component"]["id"], "PASS", "Acceptance criteria include the AT matrix"
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
    submit_report(report["id"], ctx["product"]["id"])
    approve_report(report["id"])
    submitted = submit_questionnaire(questionnaire["id"])
    return {**ctx, "run": run, "report": report, "questionnaire": submitted}


def build_linked_complaint_over_a_committed_issue():
    """A LINKED complaint whose known issue is still COMMITTED, not at rest."""
    ctx = build_untested_component_with_a_draft_row()
    run = bring_the_component_to_complete(ctx)
    train = create_release_train(
        name="Train 2026.08",
        window_start="2026-08-05",
        window_end="2026-08-20",
        freeze_days=2,
        effort_capacity_points=10,
        remediation_budget_cents=0,
    )
    issue = log_issue(
        ctx["product"]["id"],
        ctx["component"]["id"],
        ctx["criterion"]["id"],
        severity="SERIOUS",
        effort_points=2,
        target_remediation_date="2026-08-10",
        publish_intent="INCLUDED",
        summary="Media library thumbnails expose no accessible name",
    )
    triage_issue(issue["id"], triage_note="Reproduced with NVDA")
    commit_issue(issue["id"], train["id"])
    complaint = intake_complaint(
        ctx["product"]["id"],
        component_id=ctx["component"]["id"],
        criterion_id=ctx["criterion"]["id"],
        channel="EMAIL",
        description="Screen reader users cannot identify library images",
        disability_category="VISION",
    )
    triage_complaint(complaint["id"], route="REMEDIATION")
    linked = link_complaint_issue(complaint["id"], issue["id"])
    return {**ctx, "run": run, "train": train, "issue": issue, "complaint": linked}


class TestAttestationDependsOnTheComponentsTestingDimension:
    """The row is faultless; the component it belongs to is what decides."""

    def test_attesting_a_row_on_an_untested_component_is_refused(self, api):
        """PRD §3.5: "The owning component's `assessment_state` must be
        `COMPLETE`, or the request is `ERR_COMPONENT_ASSESSMENT_INCOMPLETE` —
        which is the coverage floor of §3.4 reaching into the attestation
        workflow."
        PRD §3.2: "A new component starts with `assessment_state` at `PLANNED`,
        `design_review_state` at `NOT_REVIEWED`, `coverage_pct` at 0.00,
        `evidence_units_total` at 0, an empty `validated_disability_categories`
        list and no `design_review_note`."
        PRD §3.5: "A newly authored row begins with `attestation_state` at
        `DRAFT`, records the acting `X-User-ID` as its `authored_by_user_id`, and
        carries no `attested_by_user_id`, no `attested_at`, no `attestation_note`
        and no `superseded_by_assessment_id`."

        Design: Difficulty/cross_entity_state_dependency/attest_requires_component_complete
        """
        ctx = build_untested_component_with_a_draft_row()

        assert ctx["component"]["assessment_state"] == "PLANNED", (
            "no run has been booked, so the testing dimension has not started, got "
            f"{ctx['component']['assessment_state']}"
        )
        assert ctx["assessment"]["attestation_state"] == "DRAFT"

        validate_error(
            api.attest_assessment(
                ctx["assessment"]["id"],
                attestation_payload("Signing off before any bench time"),
                REVIEWER,
            ),
            "ERR_COMPONENT_ASSESSMENT_INCOMPLETE",
            409,
        )

        assessment = read_assessment(ctx["assessment"]["id"])
        assert assessment["attestation_state"] == "DRAFT", (
            f"the refused attestation leaves the row drafted, got {assessment['attestation_state']}"
        )
        assert assessment["attested_by_user_id"] is None
        assert assessment["attested_at"] is None

    def test_the_same_row_attests_once_the_component_reaches_complete(self, api):
        """PRD §3.4: "If the recomputed coverage has reached the attestation
        floor, the component advances `IN_TESTING → COMPLETE`."
        PRD §3.5: "A successful attestation moves the row `DRAFT → ATTESTED`,
        stamps `attested_at` from the logical clock, records the reviewer's
        `X-User-ID` as `attested_by_user_id`, stores the `attestation_note`,
        rebuilds the product's `conformance_index_provisional` and
        `assessed_criteria_count`, re-derives `publication_posture`, and raises
        the product's `version` by 1."
        PRD §3.6: "When the denominator is 0 the index is 0.00; otherwise the
        index is 100 multiplied by the numerator, divided by the denominator,
        rounded half-up to two decimal places."

        Design: Difficulty/cross_entity_state_dependency/attest_requires_component_complete
        """
        ctx = build_untested_component_with_a_draft_row()
        validate_error(
            api.attest_assessment(
                ctx["assessment"]["id"],
                attestation_payload("Signing off before any bench time"),
                REVIEWER,
            ),
            "ERR_COMPONENT_ASSESSMENT_INCOMPLETE",
            409,
        )

        bring_the_component_to_complete(ctx)
        component = read_component(ctx["component"]["id"])
        assert component["coverage_pct"] == pytest.approx(45.00, abs=0.01), (
            "a manual screen-reader sweep of all 40 criteria scores 45.00, got "
            f"{component['coverage_pct']}"
        )
        assert component["assessment_state"] == "COMPLETE"

        attested = validate_success(
            api.attest_assessment(
                ctx["assessment"]["id"],
                attestation_payload("Reproduced with NVDA 2026.1"),
                REVIEWER,
            )
        )

        assert attested["attestation_state"] == "ATTESTED", (
            "nothing about the row changed between the two attempts, only the component, got "
            f"{attested['attestation_state']}"
        )
        assert attested["attested_by_user_id"] == REVIEWER_USER_ID
        product = read_product(ctx["product"]["id"])
        assert product["conformance_index_provisional"] == pytest.approx(100.00, abs=0.01), (
            "one SUPPORTS row over the single in-scope criterion is 100.00, got "
            f"{product['conformance_index_provisional']}"
        )


class TestQuestionnaireAttestationDependsOnTheCitedReport:
    """An approved report is not a public one, and only a public one may be cited."""

    def test_attesting_answers_that_cite_an_unpublished_report_is_refused(self, api):
        """PRD §3.10: "Accuracy attestation is the `AccessibilityLead`'s act of
        standing behind the answers, carrying an `accuracy_attestation`
        statement; it is legal only from `SUBMITTED` — otherwise
        `ERR_QUESTIONNAIRE_NOT_SUBMITTED` — and additionally requires that the
        cited report's `state` is `PUBLISHED`, or the request is
        `ERR_REPORT_NOT_PUBLISHED`, and that the product's posture is exactly
        `OPEN` as described in §3.8."
        PRD §3.10: "It moves `review_status` `DRAFT → SUBMITTED`, stamps
        `submitted_at` from the logical clock, and computes `disclosure_debt` and
        `disclosure_tier` for the first time."
        PRD §3.10: "First, the base debt is a sum over the product's known issues
        whose `publish_intent` is `INCLUDED` and whose state is `OPEN`,
        `TRIAGED`, `COMMITTED` or `PUBLISHED_COMMITTED`; issues that are
        `DEFERRED` or `RESOLVED`, and issues marked `EXCLUDED`, contribute
        nothing whatsoever."

        Design: Difficulty/cross_entity_state_dependency/questionnaire_attest_requires_published_report
        """
        ctx = build_submitted_questionnaire_citing_an_approved_report()

        assert ctx["questionnaire"]["review_status"] == "SUBMITTED"
        assert ctx["questionnaire"]["disclosure_debt"] == pytest.approx(0.00, abs=0.01), (
            "no known issue has been logged, so there is nothing to disclose, got "
            f"{ctx['questionnaire']['disclosure_debt']}"
        )
        assert read_product(ctx["product"]["id"])["publication_posture"] == "OPEN", (
            "the strict posture precondition is satisfied, so only the report state can bite"
        )
        assert read_report(ctx["report"]["id"])["state"] == "APPROVED"

        validate_error(
            api.attest_questionnaire(
                ctx["questionnaire"]["id"],
                questionnaire_attestation_payload("Answers are accurate as of today"),
                LEAD,
            ),
            "ERR_REPORT_NOT_PUBLISHED",
            409,
        )

        questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
        assert questionnaire["review_status"] == "SUBMITTED", (
            f"the refused attestation leaves the response submitted, got {questionnaire['review_status']}"
        )
        assert questionnaire["last_attested_at"] is None
        assert questionnaire["update_due_at"] is None

    def test_publishing_the_cited_report_unlocks_the_attestation(self, api):
        """PRD §3.10: "On success `review_status` moves `SUBMITTED → ATTESTED`,
        `last_attested_at` is stamped from the logical clock, the accuracy
        dimension is set to `CURRENT`, any `correction_due_at` is cleared, and
        the update cadence restarts: `update_due_at` is set to 90 days after
        `last_attested_at`, which is the quarterly refresh obligation the company
        takes on when it attests."
        PRD §3.7: "The report moves `APPROVED → PUBLISHED`, its `published_at` is
        stamped from the logical clock, and `conformance_index_certified` and
        `criterion_support_snapshot` are frozen from the certified rollup of
        §3.6."

        Design: Difficulty/cross_entity_state_dependency/questionnaire_attest_requires_published_report
        """
        ctx = build_submitted_questionnaire_citing_an_approved_report()
        validate_error(
            api.attest_questionnaire(
                ctx["questionnaire"]["id"],
                questionnaire_attestation_payload("Answers are accurate as of today"),
                LEAD,
            ),
            "ERR_REPORT_NOT_PUBLISHED",
            409,
        )

        published = validate_success(
            api.publish_report(
                ctx["report"]["id"], publication_payload("CUSTOMER_TRUST_PORTAL"), LEAD
            )
        )
        assert published["state"] == "PUBLISHED"

        attested = validate_success(
            api.attest_questionnaire(
                ctx["questionnaire"]["id"],
                questionnaire_attestation_payload("Answers are accurate as of today"),
                LEAD,
            )
        )

        assert attested["review_status"] == "ATTESTED", (
            "the cited report becoming public is the whole difference, got "
            f"{attested['review_status']}"
        )
        assert attested["accuracy_status"] == "CURRENT"
        assert attested["last_attested_at"].startswith("2026-08-01T00:00:00"), (
            f"last_attested_at is stamped from the logical clock, got {attested['last_attested_at']}"
        )
        assert attested["update_due_at"].startswith(f"{UPDATE_DUE_AT_DATE}T00:00:00"), (
            "the quarterly refresh falls 90 days after the attestation instant, got "
            f"{attested['update_due_at']}"
        )
        assert attested["correction_due_at"] is None


class TestComplaintClosureDependsOnTheLinkedIssue:
    """A committed issue is work in progress; closure waits for it to come to rest."""

    def test_closing_over_a_still_committed_issue_is_refused(self, api):
        """PRD §3.11: "Closing from `LINKED` requires that the linked known issue
        has come to rest — its state must be `RESOLVED` or `DEFERRED`, or the
        request is `ERR_LINKED_ISSUE_UNRESOLVED` — and the `closure_outcome` must
        be either `REMEDIATION_SCHEDULED` or `NOT_A_DEFECT`; anything else is
        `ERR_COMPLAINT_ROUTE_MISMATCH`."
        PRD §3.11: "On success the complaint moves `TRIAGED → LINKED`, its
        `linked_issue_id` is recorded, the issue's `linked_complaint_count` rises
        by 1, and the issue's `risk_score` is recomputed under whichever
        `risk_variant` it currently carries — which is how customer pressure
        feeds back into prioritization, since the `BOARD_REVIEW` variant
        amplifies by the complaint count while the `INTAKE_ESTIMATE` variant
        ignores it."
        PRD §3.9: "On success the issue moves `TRIAGED → COMMITTED`, its
        `release_train_id` is recorded, the train's `committed_effort_points`
        rises by the issue's `effort_points`, and the product's
        `publication_posture` is rebuilt."

        Design: Difficulty/cross_entity_state_dependency/complaint_close_requires_issue_terminal
        """
        ctx = build_linked_complaint_over_a_committed_issue()

        assert ctx["complaint"]["state"] == "LINKED"
        assert ctx["complaint"]["linked_issue_id"] == ctx["issue"]["id"]
        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["state"] == "COMMITTED", (
            f"the issue is scheduled but not yet at rest, got {issue['state']}"
        )
        assert issue["linked_complaint_count"] == 1

        validate_error(
            api.close_complaint(
                ctx["complaint"]["id"],
                close_complaint_payload("REMEDIATION_SCHEDULED"),
                LEAD,
            ),
            "ERR_LINKED_ISSUE_UNRESOLVED",
            409,
        )

        complaint = read_complaint(ctx["complaint"]["id"])
        assert complaint["state"] == "LINKED", (
            f"the refused closure leaves the complaint linked, got {complaint['state']}"
        )
        assert complaint["closure_outcome"] is None
        assert complaint["closed_at"] is None

    def test_resolving_the_issue_lets_the_complaint_close(self, api):
        """PRD §3.9: "On success the `resolution_note` and `resolution_run_id` are
        recorded, a resolution instant is stamped from the logical clock, and the
        compensating financial effects run: the train's
        `committed_effort_points` drops by the issue's `effort_points`, the
        train's `unallocated_cents` rises by the issue's `funded_cents`, and the
        issue's `funded_cents` returns to 0 with `funding_state` returning to
        `UNFUNDED`."
        PRD §3.11: "In both cases the `closure_outcome` and a `closed_at` instant
        from the logical clock are recorded; on the accommodation branch no known
        issue is touched, and on the remediation branch the linked issue keeps
        whatever state it had reached."

        Design: Difficulty/cross_entity_state_dependency/complaint_close_requires_issue_terminal
        """
        ctx = build_linked_complaint_over_a_committed_issue()
        validate_error(
            api.close_complaint(
                ctx["complaint"]["id"],
                close_complaint_payload("REMEDIATION_SCHEDULED"),
                LEAD,
            ),
            "ERR_LINKED_ISSUE_UNRESOLVED",
            409,
        )

        resolved = resolve_issue(ctx["issue"]["id"], ctx["run"]["id"])
        assert resolved["state"] == "RESOLVED", (
            f"the completed run on the same component is valid evidence, got {resolved['state']}"
        )
        train = read_release_train(ctx["train"]["id"])
        assert train["committed_effort_points"] == 0, (
            "resolution returns the issue's 2 effort points to the train, got "
            f"{train['committed_effort_points']}"
        )

        closed = validate_success(
            api.close_complaint(
                ctx["complaint"]["id"],
                close_complaint_payload("REMEDIATION_SCHEDULED"),
                LEAD,
            )
        )

        assert closed["state"] == "CLOSED", (
            "the linked issue coming to rest is the whole difference, got "
            f"{closed['state']}"
        )
        assert closed["closure_outcome"] == "REMEDIATION_SCHEDULED"
        assert closed["linked_issue_id"] == ctx["issue"]["id"], (
            "closure preserves the link it was gated on, got "
            f"{closed['linked_issue_id']}"
        )
        assert read_known_issue(ctx["issue"]["id"])["state"] == "RESOLVED", (
            "closing the complaint leaves the issue exactly where it had come to rest"
        )
