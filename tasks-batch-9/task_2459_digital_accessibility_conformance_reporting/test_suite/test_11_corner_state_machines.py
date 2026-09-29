"""State-machine breadth: the state a row is born in, one legal hop on each
forked lifecycle, triggers refused from the wrong state, terminal lock-out,
non-idempotent replay, a transition precondition, and a compensating withdrawal."""

import pytest

from test_helpers import (
    LEAD,
    LIAISON,
    REVIEWER,
    TESTER,
    approval_payload,
    approve_report,
    change_request_payload,
    commit_issue,
    complaint_payload,
    complaint_triage_payload,
    complete_run,
    complete_run_payload,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    draft_questionnaire,
    log_issue,
    make_role_headers,
    open_report,
    publish_report,
    read_complaint,
    read_component,
    read_known_issue,
    read_product,
    read_questionnaire,
    read_report,
    read_run,
    record_design_review,
    run_payload,
    schedule_run,
    submit_report,
    triage_issue,
    validate_error,
    validate_success,
    void_run,
    void_run_payload,
    withdraw_report,
)

APPLICABLE_CRITERIA = 40
RUN_WINDOW = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")

# A single 40-criteria manual screen-reader sweep over 40 applicable criteria
# scores 0.45 x 1.00, that is 45.00 percent.
FULL_SWEEP_COVERAGE_PCT = 45.00

# Withdrawal sets correction_due_at 10 days after the clock, which starts at
# 2026-08-01T00:00:00Z.
CORRECTION_DUE_AT_DATE = "2026-08-11"


def build_component_and_bench():
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
    return {
        "standard": standard,
        "product": product,
        "component": component,
        "bench": bench,
    }


def build_completed_sweep():
    ctx = build_component_and_bench()
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
    completed = complete_run(run["id"], defects_found=3)
    return {**ctx, "run": run, "completed": completed}


def build_draft_report_on_an_empty_inventory():
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
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    return {"standard": standard, "product": product, "report": report}


def build_published_report_with_a_public_commitment():
    """A PUBLISHED report, one PUBLISHED_COMMITTED issue and one citing response.

    The standard's only criterion sits at `AAA` while the product targets `AA`,
    so no criterion is in the target scope and the criterion-level publication
    preconditions are vacuous.
    """
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="AAA",
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
    record_design_review(
        component["id"],
        review_decision="PASS",
        review_note="Acceptance criteria include the AT matrix",
    )
    train = create_release_train(
        name="Train 2026.08",
        window_start="2026-08-05",
        window_end="2026-08-20",
        freeze_days=2,
        effort_capacity_points=10,
        remediation_budget_cents=0,
    )
    issue = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="SERIOUS",
        effort_points=2,
        target_remediation_date="2026-08-15",
        publish_intent="INCLUDED",
        summary="Media library thumbnails expose no accessible name",
    )
    triage_issue(issue["id"], triage_note="Confirmed on NVDA and JAWS")
    commit_issue(issue["id"], train["id"])
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    questionnaire = draft_questionnaire(
        product["id"],
        report["id"],
        customer_name="Northwind Health",
        questionnaire_kind="VPAT_ACR",
        answers_summary="Answers cite the ACR for release 7.0",
    )
    submit_report(report["id"], product["id"], submission_note="Ready for reviewer sign-off")
    approve_report(report["id"], approval_note="Approved with no pinned evidence")
    published = publish_report(report["id"], publication_channel="CUSTOMER_TRUST_PORTAL")
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "train": train,
        "issue": issue,
        "report": report,
        "questionnaire": questionnaire,
        "published": published,
    }


class TestInitialStates:
    """A booking is born SCHEDULED and credits nothing."""

    def test_a_new_assessment_run_is_scheduled_and_credits_nothing(self, api):
        """PRD §3.3: "The run is created with `status` at `SCHEDULED`, with no
        `defects_found`, no `void_reason` and no `completed_at`; nothing is
        credited to coverage until the run is completed."
        PRD §3.2: "A new component starts with `assessment_state` at `PLANNED`,
        `design_review_state` at `NOT_REVIEWED`, `coverage_pct` at 0.00,
        `evidence_units_total` at 0, an empty `validated_disability_categories`
        list and no `design_review_note`."

        Design: Corner/state_machines/corner_assessment_run_initial_state_is_scheduled
        """
        ctx = build_component_and_bench()

        created = validate_success(
            api.create_run(
                run_payload(
                    ctx["component"]["id"],
                    ctx["bench"]["id"],
                    method="MANUAL",
                    at_profile="SCREEN_READER",
                    scheduled_start=RUN_WINDOW[0],
                    scheduled_end=RUN_WINDOW[1],
                    criteria_exercised=APPLICABLE_CRITERIA,
                    disability_categories_validated=["VISION", "COGNITIVE"],
                ),
                TESTER,
            ),
            201,
        )

        assert created["status"] == "SCHEDULED", (
            f"a booking is born scheduled, got {created['status']}"
        )
        assert created["completed_at"] is None, (
            f"nothing has closed the run out, got {created['completed_at']}"
        )
        component = read_component(ctx["component"]["id"])
        assert component["coverage_pct"] == pytest.approx(0.00, abs=0.01), (
            f"scheduling credits no coverage, got {component['coverage_pct']}"
        )
        assert component["evidence_units_total"] == 0


class TestLegalTransitions:
    """The accommodation fork of complaint triage, with fulfilment left undone."""

    def test_triaging_a_complaint_onto_the_accommodation_route_persists_its_fields(self, api):
        """PRD §3.11: "On the `ACCOMMODATION` route two further fields become
        mandatory: the `requested_accommodation` describing what the complainant
        needs, between 10 and 1000 characters, and the `needed_by_date` naming the
        calendar date by which it is needed."
        PRD §3.11: "Successful triage moves the complaint `NEW → TRIAGED`, records
        the `route`, persists the accommodation fields on that branch, and stamps a
        triage instant from the logical clock."
        PRD §3.11: "The `ACCOMMODATION` branch continues with fulfilment, recorded
        by a `CustomerLiaison` with no payload."
        PRD §3.11: "On success the complaint moves `TRIAGED → ACCOMMODATED`,
        `accommodation_fulfilled_at` is stamped from the logical clock, and the
        product's `accommodations_fulfilled_count` is rebuilt."

        Design: Corner/state_machines/corner_complaint_triage_valid_transition
        """
        ctx = build_component_and_bench()
        intake = validate_success(
            api.create_complaint(
                complaint_payload(
                    ctx["product"]["id"],
                    component_id=ctx["component"]["id"],
                    channel="PHONE",
                    description="I need the report exported in large print",
                    disability_category="VISION",
                ),
                LIAISON,
            ),
            201,
        )

        assert intake["state"] == "NEW", (
            f"intake lands in NEW with no route yet, got {intake['state']}"
        )

        triaged = validate_success(
            api.triage_complaint(
                intake["id"],
                complaint_triage_payload(
                    route="ACCOMMODATION",
                    requested_accommodation="Large-print export of the conformance report",
                    needed_by_date="2026-09-01",
                ),
                LEAD,
            )
        )

        assert triaged["state"] == "TRIAGED"
        assert triaged["route"] == "ACCOMMODATION"
        assert triaged["accommodation_fulfilled_at"] is None, (
            "fulfilment is a separate action on this branch, got "
            f"{triaged['accommodation_fulfilled_at']}"
        )
        stored = read_complaint(intake["id"])
        assert stored["requested_accommodation"] == (
            "Large-print export of the conformance report"
        ), f"the accommodation text is persisted, got {stored['requested_accommodation']}"
        assert stored["needed_by_date"] == "2026-09-01"


class TestInvalidTransitions:
    """request-changes has no edge out of DRAFT."""

    def test_requesting_changes_on_a_draft_report_is_refused(self, api):
        """PRD §3.7: "A `ConformanceReviewer` may then return the report or approve
        it, and both actions require the report to be `IN_REVIEW` — otherwise
        `ERR_REPORT_NOT_IN_REVIEW`."
        PRD §3.7: "Returning it carries a `change_request_note`, moves the report
        `IN_REVIEW → CHANGES_REQUESTED`, raises `change_request_count` by 1, and
        clears `pinned_assessment_ids` and `pinned_assessment_versions` back to
        empty lists."
        PRD §3.7: "A new report starts in `state` `DRAFT` with
        `pinned_assessment_ids` and `pinned_assessment_versions` both empty, an
        empty `criterion_support_snapshot`, no `conformance_index_certified`, a
        `published_issue_count` of 0, a `change_request_count` of 0, no
        `publication_channel`, no `published_at`, no `withdrawal_reason`, no
        `superseded_by_report_id`, and neither a `submitted_by_user_id` nor an
        `approved_by_user_id`."

        Design: Corner/state_machines/corner_request_changes_on_draft_report_rejected
        """
        ctx = build_draft_report_on_an_empty_inventory()

        assert ctx["report"]["state"] == "DRAFT"

        validate_error(
            api.request_changes(
                ctx["report"]["id"],
                change_request_payload("Please add remarks for the contrast criterion"),
                REVIEWER,
            ),
            "ERR_REPORT_NOT_IN_REVIEW",
            409,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "DRAFT", (
            f"the refused return transitions nothing, got {report['state']}"
        )
        assert report["change_request_count"] == 0, (
            f"the counter only moves on a legal return, got {report['change_request_count']}"
        )


class TestTerminalStatesAndReplay:
    """VOID admits no second void, and COMPLETED admits no second completion."""

    def test_voiding_an_already_void_run_is_locked_out_without_double_debiting(self, api):
        """PRD §3.4: "A run may be voided from `SCHEDULED` or from `COMPLETED`, but
        never from `VOID` — a repeat attempt is `ERR_RUN_NOT_ACTIONABLE` — and a
        `COMPLETED` run that some known issue cites as its resolution evidence may
        not be voided at all, which is likewise reported as
        `ERR_RUN_NOT_ACTIONABLE`."
        PRD §3.4: "The component's `evidence_units_total` decreases by exactly the
        `criteria_exercised` that run had contributed — never by an approximation
        and never by a recomputed guess."
        PRD §3.4: "The tester supplies a `void_reason`; the run moves to `VOID`,
        which is terminal."

        Design: Corner/state_machines/corner_void_run_twice_is_locked_out
        """
        ctx = build_completed_sweep()
        first_void = void_run(
            ctx["run"]["id"],
            void_reason="Bench was running an unpatched screen reader build",
        )

        assert first_void["status"] == "VOID"
        after_first = read_component(ctx["component"]["id"])
        assert after_first["evidence_units_total"] == 0, (
            "the sweep's 40 units are withdrawn once, got "
            f"{after_first['evidence_units_total']}"
        )

        validate_error(
            api.void_run(
                ctx["run"]["id"],
                void_run_payload("Trying to void the same run again"),
                TESTER,
            ),
            "ERR_RUN_NOT_ACTIONABLE",
            409,
        )

        assert read_run(ctx["run"]["id"])["status"] == "VOID"
        component = read_component(ctx["component"]["id"])
        assert component["evidence_units_total"] == 0, (
            "the refused second void debits nothing further, so the total never goes "
            f"negative, got {component['evidence_units_total']}"
        )
        assert component["coverage_pct"] == pytest.approx(0.00, abs=0.01), (
            f"no completed run is left to credit, got {component['coverage_pct']}"
        )

    def test_completing_an_already_completed_run_is_refused_not_replayed(self, api):
        """PRD §3.4: "Closing out a run records its `defects_found` — a count from 0
        to 500 when supplied — and is only possible while the run's `status` is
        `SCHEDULED`; attempting it on a run that is already `COMPLETED` or `VOID` is
        `ERR_RUN_NOT_ACTIONABLE`."
        PRD §3.4: "On success the run moves `SCHEDULED → COMPLETED`, its
        `completed_at` is stamped from the logical clock, and the cascade begins:
        the component's `evidence_units_total` rises by exactly this run's
        `criteria_exercised` (that field is always the sum of `criteria_exercised`
        over the component's `COMPLETED` runs), the component's `coverage_pct` is
        recomputed, and the component's `validated_disability_categories` is
        rebuilt as the union of `disability_categories_validated` over the
        component's `COMPLETED` runs whose `method` is `MANUAL` — automated runs
        contribute nothing at all to validated categories, however many criteria
        they exercise."

        Design: Corner/state_machines/corner_complete_run_twice_is_not_idempotent
        """
        ctx = build_completed_sweep()

        assert ctx["completed"]["status"] == "COMPLETED"

        validate_error(
            api.complete_run(ctx["run"]["id"], complete_run_payload(defects_found=3), TESTER),
            "ERR_RUN_NOT_ACTIONABLE",
            409,
        )

        component = read_component(ctx["component"]["id"])
        assert component["evidence_units_total"] == APPLICABLE_CRITERIA, (
            "the refused replay credits nothing a second time, got "
            f"{component['evidence_units_total']}"
        )
        assert component["coverage_pct"] == pytest.approx(FULL_SWEEP_COVERAGE_PCT, abs=0.01), (
            f"coverage stays at the single sweep's 45.00, got {component['coverage_pct']}"
        )


class TestTransitionPreconditions:
    """Approval is a two-person act even when both roles sit on one identity."""

    def test_the_submitter_cannot_approve_their_own_report(self, api):
        """PRD §3.7: "Approval carries an `approval_note` and moves the report
        `IN_REVIEW → APPROVED`; the approving reviewer's `X-User-ID` must differ
        from the report's `submitted_by_user_id`, or the request is
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.7: "The owner's `X-User-ID` must equal the report's `product_id`, or
        the request is `ERR_PRODUCT_OWNERSHIP_MISMATCH`."
        PRD §3.7: "On success the acting `X-User-ID` is written to
        `submitted_by_user_id`, overwriting any earlier submitter when the report
        is coming back around the review loop, and a submission instant is stamped
        from the logical clock."

        Design: Corner/state_machines/corner_report_approval_by_submitter_rejected
        """
        ctx = build_draft_report_on_an_empty_inventory()
        submitted = submit_report(
            ctx["report"]["id"], ctx["product"]["id"], submission_note="Ready for reviewer sign-off"
        )

        assert submitted["state"] == "IN_REVIEW"
        assert submitted["submitted_by_user_id"] == ctx["product"]["id"], (
            "the accountable owner acts under the product's own identifier, got "
            f"{submitted['submitted_by_user_id']}"
        )

        validate_error(
            api.approve_report(
                ctx["report"]["id"],
                approval_payload("Approving my own submission"),
                make_role_headers(ctx["product"]["id"], "ConformanceReviewer"),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "IN_REVIEW", (
            f"the refused approval leaves the report in review, got {report['state']}"
        )
        assert report["approved_by_user_id"] is None


class TestSideEffectExecution:
    """Withdrawing a published report runs all three declared compensations."""

    def test_withdrawal_reverses_the_whole_publication_cascade(self, api):
        """PRD §3.7: "Withdrawing a `PUBLISHED` report compensates the entire
        publication cascade: every known issue whose `published_report_id` is this
        report and whose state is `PUBLISHED_COMMITTED` moves `PUBLISHED_COMMITTED
        → COMMITTED` with both `public_target_date` and `published_report_id`
        cleared to nothing; every questionnaire response citing this report as its
        `report_id` whose accuracy dimension is `CURRENT` or `STALE` flips to
        `CORRECTION_REQUIRED` with `correction_due_at` set 10 days after the
        logical clock, because answers citing a report that is no longer public are
        by definition answers that need correcting; and the product's
        `overdue_committed_blocker_count`, `correction_required_questionnaire_count`
        and `publication_posture` are all rebuilt."
        PRD §3.7: "Every known issue of the same product that is in state
        `COMMITTED` with a `publish_intent` of `INCLUDED` moves `COMMITTED →
        PUBLISHED_COMMITTED`, has its `public_target_date` set by copying its
        internal `target_remediation_date`, and has its `published_report_id` set
        to this report; the number of issues moved this way is recorded on the
        report as `published_issue_count`."
        PRD §3.8: "If `overdue_committed_blocker_count` is at least 1, or
        `correction_required_questionnaire_count` is at least 1, the posture is
        `FROZEN`."

        Design: Corner/state_machines/corner_withdraw_published_report_reverses_side_effects
        """
        ctx = build_published_report_with_a_public_commitment()

        assert ctx["published"]["published_issue_count"] == 1, (
            "the single INCLUDED commitment is disclosed, got "
            f"{ctx['published']['published_issue_count']}"
        )
        assert read_known_issue(ctx["issue"]["id"])["public_target_date"] == "2026-08-15", (
            "publication copies the internal target date into the public one"
        )

        withdrawn = withdraw_report(
            ctx["report"]["id"], withdrawal_reason="Published against the wrong release label"
        )

        assert withdrawn["state"] == "WITHDRAWN"
        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["state"] == "COMMITTED", (
            f"the public commitment is taken back to internal, got {issue['state']}"
        )
        assert issue["public_target_date"] is None, (
            f"the public date is cleared to nothing, got {issue['public_target_date']}"
        )
        assert issue["published_report_id"] is None
        questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
        assert questionnaire["accuracy_status"] == "CORRECTION_REQUIRED", (
            "answers citing a report that is no longer public need correcting, got "
            f"{questionnaire['accuracy_status']}"
        )
        assert questionnaire["correction_due_at"].startswith(f"{CORRECTION_DUE_AT_DATE}T00:00:00"), (
            "the correction deadline is 10 days after the clock, got "
            f"{questionnaire['correction_due_at']}"
        )
        product = read_product(ctx["product"]["id"])
        assert product["correction_required_questionnaire_count"] == 1
        assert product["publication_posture"] == "FROZEN", (
            "one response admitting it is wrong freezes the product, got "
            f"{product['publication_posture']}"
        )
