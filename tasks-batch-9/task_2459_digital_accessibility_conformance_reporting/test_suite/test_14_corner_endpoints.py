"""Endpoint breadth: the forced recomputation that a clock move deliberately does
not perform, a cross-reference link that writes both sides, the clock control
operation itself, and a reversal that is illegal before anything was allocated."""

import pytest

from test_helpers import (
    LEAD,
    approve_report,
    commit_issue,
    create_component,
    create_criterion,
    create_product,
    create_release_train,
    create_standard,
    deallocate_budget_payload,
    intake_complaint,
    link_issue_payload,
    log_issue,
    open_report,
    publish_report,
    read_known_issue,
    read_product,
    read_release_train,
    recompute_payload,
    record_design_review,
    set_clock,
    submit_report,
    triage_complaint,
    triage_issue,
    validate_error,
    validate_success,
)

APPLICABLE_CRITERIA = 40

# The blocker promises 2026-08-15 in public; the clock is then moved one day past
# that promise.
PUBLIC_TARGET_DATE = "2026-08-15"
CLOCK_PAST_THE_PROMISE = "2026-08-16T00:00:00Z"

# A 65-day jump, far enough to lapse any cadence, made with no write behind it.
FAR_FUTURE_CLOCK = "2026-10-05T00:00:00Z"

# SERIOUS is 25 points, a single protected category gives a breadth factor of 1,
# and a user_reach_pct of 60 gives a reach factor of 0.80: 25 x 1 x 0.80 = 20.00.
INTAKE_RISK_SCORE = 20.00

TRAIN_BUDGET_CENTS = 60327


def build_product_with_one_component():
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
    return {"standard": standard, "product": product, "component": component}


def build_published_blocker_then_move_the_clock():
    """A published BLOCKER commitment whose public promise the clock has passed.

    The standard's only criterion is at `AAA` while the product targets `AA`, so
    no criterion is in the target scope and publication has no per-criterion
    precondition to satisfy.
    """
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion = create_criterion(
        standard["id"],
        criterion_number="1.4.6",
        title="Contrast Enhanced",
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
        severity="BLOCKER",
        effort_points=2,
        target_remediation_date=PUBLIC_TARGET_DATE,
        publish_intent="INCLUDED",
        summary="Primary navigation is unreachable by keyboard",
    )
    triage_issue(issue["id"], triage_note="Reproduced on NVDA and on keyboard only")
    commit_issue(issue["id"], train["id"])
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    submit_report(report["id"], product["id"], submission_note="Ready for reviewer sign-off")
    approve_report(report["id"], approval_note="Approved with no in-scope criteria pinned")
    publish_report(report["id"], publication_channel="CUSTOMER_TRUST_PORTAL")
    posture_before = read_product(product["id"])["publication_posture"]
    set_clock(CLOCK_PAST_THE_PROMISE)
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "train": train,
        "issue": issue,
        "report": report,
        "posture_before": posture_before,
    }


def build_triaged_complaint_and_open_issue():
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
        effort_points=2,
        target_remediation_date="2026-12-01",
        publish_intent="INCLUDED",
        summary="Media library thumbnails expose no accessible name",
    )
    complaint = intake_complaint(
        product["id"],
        component_id=component["id"],
        criterion_id=criterion["id"],
        channel="EMAIL",
        description="Images in the report viewer have no alternative text",
        disability_category="VISION",
    )
    triage_complaint(complaint["id"], route="REMEDIATION")
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "issue": issue,
        "complaint": complaint,
    }


class TestForcedRecomputation:
    """The posture only notices the passed promise when someone asks it to."""

    def test_recompute_posture_freezes_the_product_after_the_clock_passes_the_promise(
        self, api
    ):
        """PRD §3.8: "`overdue_committed_blocker_count` counts the product's known
        issues of `BLOCKER` severity in state `PUBLISHED_COMMITTED` whose
        `public_target_date` is earlier than the logical clock's date."
        PRD §3.8: "If `overdue_committed_blocker_count` is at least 1, or
        `correction_required_questionnaire_count` is at least 1, the posture is
        `FROZEN`."
        PRD §3.8: "Recomputation is triggered by every write that could move one of
        those inputs: attesting, authoring or superseding a criterion assessment; a
        criterion assessment flipping to `NEEDS_REVALIDATION`; completing or voiding
        an assessment run; any known-issue state change, including intake, triage,
        board review, commitment, publication-driven commitment and resolution; any
        questionnaire accuracy change originating from an API action; publishing or
        withdrawing a report; adding a component; and the explicit product-wide
        recomputation an `AccessibilityLead` can force after moving the logical
        clock."

        Design: Corner/endpoints/corner_recompute_posture_refreshes_after_clock_move
        """
        ctx = build_published_blocker_then_move_the_clock()

        assert ctx["posture_before"] == "OPEN", (
            "at publication the promise was still in the future, got "
            f"{ctx['posture_before']}"
        )

        recomputed = validate_success(
            api.recompute_posture(
                ctx["product"]["id"],
                recompute_payload(
                    "Nightly overdue sweep after the clock passed the public target date"
                ),
                LEAD,
            )
        )

        assert recomputed["publication_posture"] == "FROZEN", (
            "a broken public commitment freezes the product, got "
            f"{recomputed['publication_posture']}"
        )
        assert recomputed["overdue_committed_blocker_count"] == 1, (
            "the single published blocker is now past its public date, got "
            f"{recomputed['overdue_committed_blocker_count']}"
        )
        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["state"] == "PUBLISHED_COMMITTED", (
            f"the recomputation moves no issue state, got {issue['state']}"
        )
        assert issue["public_target_date"] == PUBLIC_TARGET_DATE


class TestCrossReferenceLinks:
    """One request writes the complaint side and the issue side together."""

    def test_linking_writes_both_sides_without_amplifying_an_intake_score(self, api):
        """PRD §3.11: "On success the complaint moves `TRIAGED → LINKED`, its
        `linked_issue_id` is recorded, the issue's `linked_complaint_count` rises by
        1, and the issue's `risk_score` is recomputed under whichever `risk_variant`
        it currently carries — which is how customer pressure feeds back into
        prioritization, since the `BOARD_REVIEW` variant amplifies by the complaint
        count while the `INTAKE_ESTIMATE` variant ignores it."
        PRD §3.9: "Under the `INTAKE_ESTIMATE` variant — used when the issue is
        first logged and again at triage, before the prioritization board has looked
        at it — the `risk_score` is simply that base term rounded half-up to two
        decimal places, with no aging, no complaint amplification and no ceiling."
        PRD §3.9: "A new issue starts in state `OPEN`, with `release_train_id`,
        `public_target_date`, `published_report_id`, `resolution_run_id`,
        `triage_note`, `board_review_note` and `resolution_note` all empty,
        `funded_cents` at 0, `funding_state` at `UNFUNDED`, `linked_complaint_count`
        at 0, `risk_variant` at `INTAKE_ESTIMATE`, and a `risk_score` computed
        immediately under that variant."

        Design: Corner/endpoints/corner_link_issue_associates_complaint_and_issue
        """
        ctx = build_triaged_complaint_and_open_issue()

        assert ctx["issue"]["risk_score"] == pytest.approx(INTAKE_RISK_SCORE, abs=0.01), (
            f"25 x 1 x 0.80 is 20.00, got {ctx['issue']['risk_score']}"
        )
        assert ctx["issue"]["linked_complaint_count"] == 0

        linked = validate_success(
            api.link_issue(
                ctx["complaint"]["id"], link_issue_payload(ctx["issue"]["id"]), LEAD
            )
        )

        assert linked["state"] == "LINKED"
        assert linked["linked_issue_id"] == ctx["issue"]["id"]
        issue = read_known_issue(ctx["issue"]["id"])
        assert issue["linked_complaint_count"] == 1, (
            f"the issue side of the link is written too, got {issue['linked_complaint_count']}"
        )
        assert issue["risk_score"] == pytest.approx(INTAKE_RISK_SCORE, abs=0.01), (
            "the intake variant ignores complaint pressure, got "
            f"{issue['risk_score']}"
        )
        assert issue["risk_variant"] == "INTAKE_ESTIMATE"


class TestTheClockIsAPureControlOperation:
    """Moving the clock writes nothing and recomputes nothing."""

    def test_a_sixty_five_day_jump_leaves_the_product_row_untouched(self, api):
        """PRD §2.4: "Moving the clock is a pure control operation: it performs no
        writes of its own and recomputes nothing, so derived fields that depend on
        the current instant refresh only on the next mutating call that touches
        them, or when an `AccessibilityLead` explicitly forces a product-wide
        recomputation."
        PRD §2.4: "The clock begins at `2026-08-01T00:00:00Z` and an
        `AccessibilityLead` may move it to any instant supplied as `to_iso8601`."
        PRD §2.9: "A client that reads a derived field is reading the value as of
        the last write that touched it, which is why an explicit product-wide
        recomputation capability exists for use after the logical clock moves."

        Design: Corner/endpoints/corner_clock_endpoint_advances_time_without_writing
        """
        ctx = build_product_with_one_component()
        before = read_product(ctx["product"]["id"])

        assert before["publication_posture"] == "OPEN", (
            "nothing has been assessed or promised, got "
            f"{before['publication_posture']}"
        )

        validate_success(api.set_clock(FAR_FUTURE_CLOCK, LEAD))

        after = read_product(ctx["product"]["id"])
        assert after["version"] == before["version"], (
            "the clock call bumped no version, got "
            f"{after['version']} against {before['version']}"
        )
        assert after["updated_at"] == before["updated_at"], (
            "the clock call touched no row, got "
            f"{after['updated_at']} against {before['updated_at']}"
        )
        assert after["publication_posture"] == "OPEN", (
            "no derived field refreshed on its own, got "
            f"{after['publication_posture']}"
        )


class TestConditionalActions:
    """A reversal needs something to reverse."""

    def test_deallocating_an_unallocated_train_is_refused(self, api):
        """PRD §3.9: "Reversing an allocation requires the train to be `ALLOCATED` —
        otherwise `ERR_TRAIN_BUDGET_NOT_ALLOCATED` — and carries the `product_id`
        whose allocation is being reversed together with a `reason`."
        PRD §3.9: "A new train reports `committed_effort_points` of 0,
        `unallocated_cents` equal to its whole `remediation_budget_cents`, and
        `allocation_state` of `UNALLOCATED`."

        Design: Corner/endpoints/corner_deallocate_budget_without_allocation_rejected
        """
        ctx = build_product_with_one_component()
        train = create_release_train(
            name="Train 2026.09",
            window_start="2026-09-05",
            window_end="2026-09-27",
            freeze_days=2,
            effort_capacity_points=10,
            remediation_budget_cents=TRAIN_BUDGET_CENTS,
        )

        assert train["allocation_state"] == "UNALLOCATED"

        validate_error(
            api.deallocate_budget(
                train["id"],
                deallocate_budget_payload(
                    ctx["product"]["id"], "Rolling back an allocation that never happened"
                ),
                LEAD,
            ),
            "ERR_TRAIN_BUDGET_NOT_ALLOCATED",
            409,
        )

        stored = read_release_train(train["id"])
        assert stored["unallocated_cents"] == TRAIN_BUDGET_CENTS, (
            "no cent was ever granted, so none can be returned, got "
            f"{stored['unallocated_cents']}"
        )
        assert stored["allocation_state"] == "UNALLOCATED"
