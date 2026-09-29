"""Role breadth: an exclusive action refused before its own preconditions, the
entity-backed owner role refused on someone else's product, and the one write two
roles share."""

from test_helpers import (
    LEAD,
    LIAISON,
    TESTER,
    approve_report,
    create_component,
    create_criterion,
    create_product,
    create_standard,
    known_issue_payload,
    make_product_owner_headers,
    open_report,
    publication_payload,
    read_component,
    read_report,
    submission_payload,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

APPLICABLE_CRITERIA = 40


def build_approved_report_on_an_unreviewed_component():
    """An APPROVED report whose product would also fail publication on its merits.

    The standard holds no criteria, so nothing is in the product's target scope,
    and the single in-scope component was never taken through design review.
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
    component = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=APPLICABLE_CRITERIA,
        user_reach_pct=60,
    )
    report = open_report(product["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    submit_report(report["id"], product["id"], submission_note="Ready for reviewer sign-off")
    approved = approve_report(report["id"], approval_note="Approved for publication")
    return {
        "standard": standard,
        "product": product,
        "component": component,
        "report": approved,
    }


def build_two_products_and_a_draft_report_on_the_first():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    product_a = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    product_b = create_product(
        standard["id"],
        name="Insight Mobile",
        version_label="3.1",
        target_level="AA",
        surface_type="WEB",
    )
    report = open_report(product_a["id"], standard["id"], report_title="ACR Insight Portal 7.0")
    return {
        "standard": standard,
        "product_a": product_a,
        "product_b": product_b,
        "report": report,
    }


def build_product_ready_for_issue_intake():
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
    return {
        "standard": standard,
        "criterion": criterion,
        "product": product,
        "component": component,
    }


class TestExclusiveActions:
    """Publication belongs to the lead, and the role check runs first."""

    def test_a_tester_cannot_publish_and_no_precondition_is_reached(self, api):
        """PRD §2.1: "When the headers are well formed but the named role is not
        authorized for the endpoint being called — as tabulated in §4 — the rejection
        is `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.7: "2. The acting role is authorized for the endpoint —
        `ERR_UNAUTHORIZED` (403)."
        PRD §2.7: "When several rules could reject the same request, the outcome must
        be deterministic. Checks are evaluated strictly in the following order, and
        the first failing check produces the response; later checks are never reached
        and never mask an earlier one."
        PRD §2.1: "An `AccessibilityLead` owns the programme: standards and criteria
        configuration, product enrolment, the component inventory, bench
        registration, release trains and the remediation budget, issue triage and
        prioritization, complaint routing and closure, report publication and
        withdrawal, questionnaire accuracy attestation, and the logical clock."

        Design: Corner/rbac/corner_tester_cannot_publish_a_report
        """
        ctx = build_approved_report_on_an_unreviewed_component()

        validate_error(
            api.publish_report(ctx["report"]["id"], publication_payload(), TESTER),
            "ERR_UNAUTHORIZED",
            403,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "APPROVED", (
            f"the refused publication moves nothing, got {report['state']}"
        )
        assert report["published_at"] is None
        assert read_component(ctx["component"]["id"])["design_review_state"] == "NOT_REVIEWED", (
            "the design-review gate was never reached, so it reports the untouched state"
        )


class TestEntityBackedOwnership:
    """The owner role is bound to one product by its own user id."""

    def test_an_owner_of_another_product_cannot_submit_this_report(self, api):
        """PRD §2.1: "When `X-User-Role` is `ProductOwner`, `X-User-ID` is the `id`
        of the acting `Product`; ownership checks on any resource that references a
        product compare that resource's product reference to `X-User-ID`, so a
        `ProductOwner` submitting a conformance report must present an `X-User-ID`
        equal to the `product_id` recorded on that report, and any mismatch is
        rejected with `ERR_PRODUCT_OWNERSHIP_MISMATCH` (HTTP 403)."
        PRD §3.7: "The owner's `X-User-ID` must equal the report's `product_id`, or
        the request is `ERR_PRODUCT_OWNERSHIP_MISMATCH`."
        PRD §2.7: "3. `ProductOwner` ownership: `X-User-ID` matches the product that
        owns the target resource — `ERR_PRODUCT_OWNERSHIP_MISMATCH` (403)."

        Design: Corner/rbac/corner_product_owner_cannot_submit_another_products_report
        """
        ctx = build_two_products_and_a_draft_report_on_the_first()

        assert ctx["report"]["state"] == "DRAFT"

        validate_error(
            api.submit_report(
                ctx["report"]["id"],
                submission_payload("Submitting a report I do not own"),
                make_product_owner_headers(ctx["product_b"]["id"]),
            ),
            "ERR_PRODUCT_OWNERSHIP_MISMATCH",
            403,
        )

        report = read_report(ctx["report"]["id"])
        assert report["state"] == "DRAFT", (
            f"the review loop never started, got {report['state']}"
        )
        assert report["submitted_by_user_id"] is None, (
            "no provenance is recorded for a refused submission, got "
            f"{report['submitted_by_user_id']}"
        )


class TestSharedWrites:
    """Issue intake is shared by two roles and closed to the third."""

    def test_both_tester_and_lead_log_issues_while_a_liaison_cannot(self, api):
        """PRD §2.1: "Logging a known issue is shared between `AccessibilityTester`
        and `AccessibilityLead`; every read endpoint is open to all five roles."
        PRD §2.1: "A `CustomerLiaison` faces the customer: drafting, submitting and
        revising procurement questionnaire responses, taking complaint and
        accommodation intake, and recording accommodation fulfilment."
        PRD §3.9: "A new issue starts in state `OPEN`, with `release_train_id`,
        `public_target_date`, `published_report_id`, `resolution_run_id`,
        `triage_note`, `board_review_note` and `resolution_note` all empty,
        `funded_cents` at 0, `funding_state` at `UNFUNDED`, `linked_complaint_count`
        at 0, `risk_variant` at `INTAKE_ESTIMATE`, and a `risk_score` computed
        immediately under that variant."

        Design: Corner/rbac/corner_known_issue_intake_shared_by_lead_and_tester
        """
        ctx = build_product_ready_for_issue_intake()
        by_tester = known_issue_payload(
            ctx["product"]["id"],
            ctx["component"]["id"],
            ctx["criterion"]["id"],
            severity="SERIOUS",
            effort_points=2,
            target_remediation_date="2026-12-01",
            publish_intent="INCLUDED",
            summary="Media library thumbnails expose no accessible name",
        )
        by_lead = known_issue_payload(
            ctx["product"]["id"],
            ctx["component"]["id"],
            ctx["criterion"]["id"],
            severity="MINOR",
            effort_points=1,
            target_remediation_date="2026-12-01",
            publish_intent="EXCLUDED",
            summary="Decorative icons expose redundant alternative text",
        )

        tester_issue = validate_success(api.create_known_issue(by_tester, TESTER), 201)
        lead_issue = validate_success(api.create_known_issue(by_lead, LEAD), 201)

        assert tester_issue["state"] == "OPEN"
        assert lead_issue["state"] == "OPEN"
        assert tester_issue["id"] != lead_issue["id"], "two intakes are two rows"

        validate_error(
            api.create_known_issue(by_tester, LIAISON), "ERR_UNAUTHORIZED", 403
        )

        _rows, meta = validate_paginated(
            api.list_known_issues(TESTER, {"product_id": ctx["product"]["id"]})
        )
        assert meta["total_count"] == 2, (
            "the two accepted intakes are the only rows, and the refused one added "
            f"nothing, got {meta['total_count']}"
        )
