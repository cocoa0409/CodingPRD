"""Two quantities the API computes twice with different levels of charity: the
provisional against the certified conformance index, and the intake against the
board-review remediation risk score."""

import pytest

from test_helpers import (
    LEAD,
    attested_assessment,
    author_assessment,
    board_review_payload,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_standard,
    expected_board_review_risk_score,
    expected_intake_risk_score,
    intake_complaint,
    link_complaint_issue,
    log_issue,
    open_report,
    publication_payload,
    read_known_issue,
    read_product,
    record_design_review,
    schedule_and_complete_run,
    set_clock,
    submit_report,
    triage_complaint,
    triage_issue,
    approve_report,
    read_report,
    validate_success,
)


def build_approved_report_with_one_attested_and_one_draft_row():
    """A product whose two in-scope criteria carry one ATTESTED and one DRAFT row.

    Criterion 1.1.1 is attested as SUPPORTS (weight 1.0) and criterion 1.4.3 is
    only drafted as PARTIALLY_SUPPORTS (weight 0.5), so the two index variants
    must disagree: the provisional one counts both rows over a denominator of 2,
    the certified one counts only the attested row and still charges the
    unattested criterion inside its denominator.
    """
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    criterion_a = create_criterion(
        standard["id"],
        criterion_number="1.1.1",
        title="Non-text Content",
        level="A",
        disability_categories=["VISION", "COGNITIVE"],
        applies_to_surfaces=["WEB"],
    )
    criterion_aa = create_criterion(
        standard["id"],
        criterion_number="1.4.3",
        title="Contrast Minimum",
        level="AA",
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
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=40,
        user_reach_pct=60,
    )
    bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    run = schedule_and_complete_run(
        component["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        criteria_exercised=40,
        disability_categories_validated=["VISION", "COGNITIVE"],
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T12:00:00Z",
        defects_found=3,
    )
    attested = attested_assessment(component["id"], criterion_a["id"], support_level="SUPPORTS")
    drafted = author_assessment(
        component["id"],
        criterion_aa["id"],
        support_level="PARTIALLY_SUPPORTS",
        remarks="Contrast fails on the legacy chrome only",
    )
    record_design_review(component["id"], "PASS")
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    submit_report(report["id"], product["id"])
    approve_report(report["id"])
    return {
        "standard": standard,
        "criterion_a": criterion_a,
        "criterion_aa": criterion_aa,
        "product": product,
        "component": component,
        "run": run,
        "attested": attested,
        "drafted": drafted,
        "report": report,
    }


def build_triaged_issue_with_one_linked_complaint():
    """A SERIOUS issue on a two-category criterion, 20 days past its target date.

    The issue is triaged (so its score is still the intake estimate) and carries
    one linked complaint, which only the board-review variant amplifies.
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
    issue = log_issue(
        product["id"],
        component["id"],
        criterion["id"],
        severity="SERIOUS",
        effort_points=1,
        target_remediation_date="2026-08-05",
        publish_intent="INCLUDED",
        summary="Media library thumbnails expose no accessible name",
    )
    triage_issue(issue["id"])
    complaint = intake_complaint(
        product["id"],
        component_id=component["id"],
        criterion_id=criterion["id"],
        channel="EMAIL",
        description="Screen reader users cannot identify library images",
        disability_category="VISION",
    )
    triage_complaint(complaint["id"], route="REMEDIATION")
    link_complaint_issue(complaint["id"], issue["id"])
    return {
        "product": product,
        "component": component,
        "criterion": criterion,
        "issue": issue,
        "complaint": complaint,
    }


class TestProvisionalVersusCertifiedConformanceIndex:
    """The running view and the certified one on identical evidence."""

    def test_provisional_index_counts_the_draft_row_and_the_certified_one_does_not(self, api):
        """PRD §3.6: "The provisional variant treats both `DRAFT` and `ATTESTED`
        as qualifying; the certified variant treats only `ATTESTED` as
        qualifying, so drafts are invisible to it."
        PRD §3.6: "Qualifying rows whose `support_level` is `NOT_APPLICABLE` are
        ignored and contribute nothing; every other qualifying row contributes a
        support weight of 1.0 for `SUPPORTS`, 0.5 for `PARTIALLY_SUPPORTS` and
        0.0 for `DOES_NOT_SUPPORT`."
        PRD §3.6: "The product's `assessed_criteria_count` is the provisional
        variant's denominator — that is, the number of in-scope criteria that
        have at least one qualifying provisional assessment — and it is what
        tells the posture gate whether the index floor is meaningful yet."

        Design: Difficulty/dual_variant_calc/provisional_versus_certified_conformance_index_divergence
        """
        ctx = build_approved_report_with_one_attested_and_one_draft_row()

        product = read_product(ctx["product"]["id"])

        assert product["assessed_criteria_count"] == 2, (
            "both the ATTESTED and the DRAFT row qualify for the provisional variant, "
            f"expected a denominator of 2, got {product['assessed_criteria_count']}"
        )
        assert product["conformance_index_provisional"] == pytest.approx(75.00, abs=0.01), (
            "SUPPORTS 1.0 plus PARTIALLY_SUPPORTS 0.5 over 2 included criteria is 75.00, got "
            f"{product['conformance_index_provisional']}"
        )

        published = validate_success(
            api.publish_report(
                ctx["report"]["id"], publication_payload("CUSTOMER_TRUST_PORTAL"), LEAD
            )
        )

        assert published["state"] == "PUBLISHED"
        assert published["conformance_index_certified"] == pytest.approx(50.00, abs=0.01), (
            "the certified variant scores the attested criterion 1.0 and charges the "
            "unattested criterion 0.0 inside the same denominator of 2, expected 50.00, got "
            f"{published['conformance_index_certified']}"
        )

    def test_publication_pins_and_snapshots_only_the_attested_row(self, api):
        """PRD §3.7: "On approval the acting `X-User-ID` is recorded as
        `approved_by_user_id`, an approval instant is stamped from the logical
        clock, and the evidence is **pinned**: `pinned_assessment_ids` is frozen
        as the identifiers of every criterion assessment currently in `ATTESTED`
        state belonging to one of the product's in-scope components, ordered by
        the assessments' `created_at` ascending, and `pinned_assessment_versions`
        captures those same rows' `version` values in the same index-aligned
        order."
        PRD §3.8: "Otherwise, if the product has at least one assessed criterion
        and its `conformance_index_provisional` is strictly below 85.00, or its
        `stale_questionnaire_count` is at least 2, the posture is `RESTRICTED`."

        Design: Difficulty/dual_variant_calc/provisional_versus_certified_conformance_index_divergence
        """
        ctx = build_approved_report_with_one_attested_and_one_draft_row()

        approved = read_report(ctx["report"]["id"])
        assert approved["pinned_assessment_ids"] == [ctx["attested"]["id"]], (
            "only the ATTESTED row is pinned at approval, expected "
            f"[{ctx['attested']['id']}], got {approved['pinned_assessment_ids']}"
        )
        assert ctx["drafted"]["id"] not in approved["pinned_assessment_ids"], (
            "the DRAFT row must never be pinned"
        )

        validate_success(
            api.publish_report(
                ctx["report"]["id"], publication_payload("CUSTOMER_TRUST_PORTAL"), LEAD
            )
        )
        product = read_product(ctx["product"]["id"])

        assert product["publication_posture"] == "RESTRICTED", (
            "a provisional index of 75.00 over 2 assessed criteria is below the 85.00 floor, "
            f"expected RESTRICTED, got {product['publication_posture']}"
        )


class TestIntakeVersusBoardReviewRiskScore:
    """The two remediation risk variants on one known issue."""

    def test_intake_estimate_ignores_aging_and_linked_complaints(self, api):
        """PRD §3.9: "The severity contributes fixed points: 40 for `BLOCKER`,
        25 for `SERIOUS`, 12 for `MODERATE` and 5 for `MINOR`."
        PRD §3.9: "The breadth factor counts how many distinct disability
        categories the violated criterion protects — a number from 1 to 4, read
        from that criterion's `disability_categories` — and equals 1 plus
        fifteen hundredths for each category beyond the first, so a criterion
        protecting all four categories carries a breadth factor of 1.45."
        PRD §3.9: "The reach factor equals one half plus one half multiplied by
        the affected component's `user_reach_pct` divided by 100, so a component
        nobody touches still carries half weight and a component every user
        touches carries full weight."
        PRD §3.9: "Under the `INTAKE_ESTIMATE` variant — used when the issue is
        first logged and again at triage, before the prioritization board has
        looked at it — the `risk_score` is simply that base term rounded half-up
        to two decimal places, with no aging, no complaint amplification and no
        ceiling."

        Design: Difficulty/dual_variant_calc/intake_versus_board_review_remediation_risk_divergence
        """
        ctx = build_triaged_issue_with_one_linked_complaint()

        set_clock("2026-08-25T00:00:00Z")
        issue = read_known_issue(ctx["issue"]["id"])

        expected = expected_intake_risk_score("SERIOUS", 2, 60)
        assert expected == pytest.approx(23.00, abs=0.01)
        assert issue["risk_variant"] == "INTAKE_ESTIMATE", (
            f"a triaged issue still carries the intake variant, got {issue['risk_variant']}"
        )
        assert issue["risk_score"] == pytest.approx(expected, abs=0.01), (
            "SERIOUS 25 points times the two-category breadth factor 1.15 times the reach "
            f"factor 0.8 is 23.00, got {issue['risk_score']}"
        )
        assert issue["linked_complaint_count"] == 1, (
            "the linked complaint is counted but not priced by the intake variant, got "
            f"{issue['linked_complaint_count']}"
        )

    def test_board_review_multiplies_the_same_base_by_aging_and_complaints(self, api):
        """PRD §3.9: "The aging multiplier is 1 plus two hundredths for each
        whole day by which the logical clock's date has passed the issue's
        `target_remediation_date`, counting no days at all when the target date
        is still in the future, and counting no more than 60 days however late
        the issue is; an issue two months past target therefore carries an aging
        multiplier of 2.2 at most."
        PRD §3.9: "The complaint multiplier is 1 plus one tenth for each
        complaint linked to the issue, counted from `linked_complaint_count` and
        capped at 5 complaints, so the amplification never exceeds 1.5."
        PRD §3.9: "The board-review score is the base term multiplied by the
        aging multiplier multiplied by the complaint multiplier, clamped so it
        can never exceed 100.00, and only then rounded half-up to two decimal
        places."
        PRD §3.9: "When `defer` is false the issue stays in `TRIAGED` — the
        transition is a self-loop that exists purely to switch the scoring
        variant — and remains committable."

        Design: Difficulty/dual_variant_calc/intake_versus_board_review_remediation_risk_divergence
        """
        ctx = build_triaged_issue_with_one_linked_complaint()
        set_clock("2026-08-25T00:00:00Z")

        reviewed = validate_success(
            api.board_review_issue(
                ctx["issue"]["id"],
                board_review_payload(False, "Board keeps the issue committable"),
                LEAD,
            )
        )

        expected = expected_board_review_risk_score(
            "SERIOUS", 2, 60, days_past_target=20, linked_complaint_count=1
        )
        assert expected == pytest.approx(35.42, abs=0.01)
        assert reviewed["risk_score"] == pytest.approx(expected, abs=0.01), (
            "the unrounded base 23.00 times the 20-day aging factor 1.4 times the "
            f"one-complaint factor 1.1 is 35.42, got {reviewed['risk_score']}"
        )
        assert reviewed["risk_variant"] == "BOARD_REVIEW"
        assert reviewed["state"] == "TRIAGED", (
            "a board review that does not defer leaves the issue committable in TRIAGED, got "
            f"{reviewed['state']}"
        )
        assert reviewed["linked_complaint_count"] == 1
