"""Requests that violate two rules at once, where only the earlier rule may
answer: report state before the empty-inventory check, and segregation of duties
before evidence expiry."""

from test_helpers import (
    LEAD,
    REVIEWER,
    TESTER_USER_ID,
    attestation_payload,
    author_assessment,
    approve_report,
    complete_run,
    create_component,
    create_criterion,
    create_environment,
    create_product,
    create_standard,
    make_role_headers,
    open_report,
    publication_payload,
    read_assessment,
    read_product,
    read_report,
    schedule_run,
    set_clock,
    submit_report,
    validate_error,
)

CHANNEL = "CUSTOMER_TRUST_PORTAL"


def build_draft_report_on_an_all_out_of_scope_inventory():
    """A DRAFT report on a product whose entire inventory is out of scope.

    Both the report-state rule and the in-scope-inventory rule are violated by a
    publish call, so the response settles which one is evaluated first.
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
    create_component(
        product["id"],
        name="Internal Admin Console",
        component_type="DESKTOP_APP",
        in_scope=False,
        assessment_scope="EXCLUDED",
        applicable_criteria_count=40,
        user_reach_pct=5,
    )
    create_component(
        product["id"],
        name="Batch Import CLI",
        component_type="DESKTOP_APP",
        in_scope=False,
        assessment_scope="EXCLUDED",
        applicable_criteria_count=40,
        user_reach_pct=2,
    )
    product = read_product(product["id"])
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    return {"standard": standard, "product": product, "report": report}


def build_draft_assessment_whose_evidence_has_expired():
    """A DRAFT row authored by tester-1 and left unattested for 122 days."""
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
    run = schedule_run(
        component["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start="2026-08-03T09:00:00Z",
        scheduled_end="2026-08-03T12:00:00Z",
        criteria_exercised=40,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    complete_run(run["id"], defects_found=3)
    assessment = author_assessment(component["id"], criterion["id"], support_level="SUPPORTS")

    set_clock("2026-12-01T00:00:00Z")
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
        "run": run,
        "assessment": assessment,
    }


class TestPublishStateErrorPrecedesMissingInScopeComponents:
    """A DRAFT report with an empty in-scope inventory answers on state alone."""

    def test_publishing_a_draft_report_answers_with_the_state_error(self, api):
        """PRD §2.7: "Checks are evaluated strictly in the following order, and
        the first failing check produces the response; later checks are never
        reached and never mask an earlier one."
        PRD §2.7: "10. Conformance-report from-state —
        `ERR_REPORT_NOT_SUBMITTABLE`, `ERR_REPORT_NOT_IN_REVIEW`,
        `ERR_REPORT_NOT_APPROVED` or `ERR_REPORT_NOT_WITHDRAWABLE` (409)."
        PRD §2.7: "28. The product has at least one in-scope component at
        publication — `ERR_NO_IN_SCOPE_COMPONENTS` (422)."
        PRD §3.1: "`components_in_scope_count` is the number of the product's
        components whose in-scope flag is true"

        Design: Difficulty/priority_pair_validation_conflict/publish_report_state_error_precedes_missing_in_scope_components
        """
        ctx = build_draft_report_on_an_all_out_of_scope_inventory()

        assert ctx["product"]["components_in_scope_count"] == 0, (
            "both components carry in_scope false, got "
            f"{ctx['product']['components_in_scope_count']}"
        )
        assert ctx["report"]["state"] == "DRAFT"

        validate_error(
            api.publish_report(ctx["report"]["id"], publication_payload(CHANNEL), LEAD),
            "ERR_REPORT_NOT_APPROVED",
            409,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "DRAFT", (
            f"a rejected publish transitions nothing, got {report['state']}"
        )
        assert report["published_at"] is None

    def test_the_inventory_error_surfaces_once_the_report_is_approved(self, api):
        """PRD §3.7: "It requires the report to be `APPROVED` — otherwise
        `ERR_REPORT_NOT_APPROVED` — and then five substantive conditions,
        evaluated in the order set out in §2.7."
        PRD §3.7: "The product must have at least one in-scope component, since an
        empty inventory cannot be certified, or the request is
        `ERR_NO_IN_SCOPE_COMPONENTS`."

        Design: Difficulty/priority_pair_validation_conflict/publish_report_state_error_precedes_missing_in_scope_components
        """
        ctx = build_draft_report_on_an_all_out_of_scope_inventory()

        submit_report(ctx["report"]["id"], ctx["product"]["id"])
        approve_report(ctx["report"]["id"])

        validate_error(
            api.publish_report(ctx["report"]["id"], publication_payload(CHANNEL), LEAD),
            "ERR_NO_IN_SCOPE_COMPONENTS",
            422,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "APPROVED", (
            "the second rejected publish leaves the report approved, got "
            f"{report['state']}"
        )
        assert report["published_at"] is None


class TestAttestSegregationOfDutiesPrecedesExpiredEvidence:
    """Self-attestation is refused before the 90-day freshness rule is consulted."""

    def test_the_author_is_refused_on_segregation_of_duties(self, api):
        """PRD §2.1: "A reviewer may not attest a criterion assessment whose
        `authored_by_user_id` equals their own `X-User-ID`, and a reviewer may not
        approve a conformance report whose `submitted_by_user_id` equals their own
        `X-User-ID`."
        PRD §2.7: "16. Segregation of duties on assessment attestation and report
        approval — `ERR_SEGREGATION_OF_DUTIES` (403)."
        PRD §2.7: "23. Assessment evidence has not expired —
        `ERR_ASSESSMENT_EVIDENCE_EXPIRED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/attest_segregation_of_duties_precedes_expired_evidence
        """
        ctx = build_draft_assessment_whose_evidence_has_expired()

        author_acting_as_reviewer = make_role_headers(TESTER_USER_ID, "ConformanceReviewer")
        validate_error(
            api.attest_assessment(
                ctx["assessment"]["id"],
                attestation_payload("Self-attesting my own assessment"),
                author_acting_as_reviewer,
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        assessment = read_assessment(ctx["assessment"]["id"])
        assert assessment["attestation_state"] == "DRAFT", (
            f"the refused attestation leaves the row drafted, got {assessment['attestation_state']}"
        )
        assert assessment["attested_by_user_id"] is None

    def test_an_independent_reviewer_then_meets_the_expiry_rule(self, api):
        """PRD §3.5: "And the evidence must be fresh: attestation must happen no
        later than 90 days after the row's `created_at`, measured on the logical
        clock, or the request is `ERR_ASSESSMENT_EVIDENCE_EXPIRED`."
        PRD §3.5: "An attestation exactly 90 days after authoring is still
        accepted; one day later is not."
        PRD §3.6: "The provisional variant treats both `DRAFT` and `ATTESTED` as
        qualifying; the certified variant treats only `ATTESTED` as qualifying, so
        drafts are invisible to it."

        Design: Difficulty/priority_pair_validation_conflict/attest_segregation_of_duties_precedes_expired_evidence
        """
        ctx = build_draft_assessment_whose_evidence_has_expired()

        validate_error(
            api.attest_assessment(
                ctx["assessment"]["id"],
                attestation_payload("Independent reviewer attesting the same row"),
                REVIEWER,
            ),
            "ERR_ASSESSMENT_EVIDENCE_EXPIRED",
            422,
        )

        assessment = read_assessment(ctx["assessment"]["id"])
        assert assessment["attestation_state"] == "DRAFT"
        product = read_product(ctx["product"]["id"])
        assert product["assessed_criteria_count"] == 1, (
            "the still-DRAFT row keeps qualifying for the provisional variant, got "
            f"{product['assessed_criteria_count']}"
        )
