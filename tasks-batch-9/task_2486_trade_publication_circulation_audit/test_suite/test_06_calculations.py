"""Derived arithmetic: the scoring model, breakdown eligibility, and threshold ladders."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_pct
from test_helpers.factories import (
    finding_payload,
    industry_rule_payload,
    issue_report_payload,
    job_function_rule_payload,
    purchasing_authority_rule_payload,
    undeliverable_event_payload,
)
from test_helpers.fixtures import (
    add_rule,
    add_subscriber,
    attach_source_document,
    certify_statement,
    move_clock,
    open_engagement,
    open_request,
    open_statement,
    read_publication,
    read_statement,
    read_subscriber,
    record_sample,
    register_publication,
    review_request,
    run_hygiene_sweep,
    verify_request,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    MANAGER_HEADERS,
    SPECIALIST_HEADERS,
)


def three_dimension_policy(publication_id):
    """Give a publication the complete three-dimension qualification definition."""
    add_rule(
        publication_id,
        job_function_rule_payload(
            allowed_values=["ENGINEERING_MGMT"], points=45, is_mandatory=True
        ),
    )
    add_rule(
        publication_id,
        industry_rule_payload(
            allowed_values=["MANUFACTURING"], points=30, is_mandatory=False
        ),
    )
    add_rule(
        publication_id,
        purchasing_authority_rule_payload(
            allowed_values=["APPROVES"], points=25, is_mandatory=False
        ),
    )


def test_qualification_score_channel_bonus_with_partial_criteria_match():
    """A missed non-mandatory dimension scores zero, and the channel bonus is channel-specific.

    "A dimension scores that rule's `points` when the attested value is an exact
    member of the list, and scores 0 otherwise ... a request whose
    `request_channel` is `DIRECT_MAIL` earns 10 bonus points, and one whose
    channel is `WEB` or `EMAIL` earns 5, but only while the signature is no more
    than twelve complete months old."

    Design: Corner/calculations/qualification_score_channel_bonus_with_partial_criteria_match
    """
    publication = register_publication(
        name="Scoring Component Monthly", industry_code="MANUFACTURING"
    )
    three_dimension_policy(publication["id"])

    def score_through_channel(company_name, request_channel, doc_type):
        subscriber = add_subscriber(
            publication["id"],
            company_name=company_name,
            job_function_code="ENGINEERING_MGMT",
            industry_code="RETAIL",
            purchasing_authority_level="APPROVES",
            subscription_class="QUALIFIED_NON_PAID",
            copies=150,
        )
        document = attach_source_document(
            subscriber["id"],
            SPECIALIST_HEADERS,
            doc_type=doc_type,
            captured_at="2026-07-20T00:00:00Z",
        )
        request = open_request(
            subscriber["id"],
            document["id"],
            subscriber["version"],
            headers=SPECIALIST_HEADERS,
            request_channel=request_channel,
            signed_at="2026-07-20T00:00:00Z",
            attested_job_function_code="ENGINEERING_MGMT",
            attested_industry_code="RETAIL",
            attested_purchasing_authority="APPROVES",
        )
        return subscriber, request

    subscriber, request = score_through_channel(
        "Xray Retail Group", "WEB", "WEB_FORM_CAPTURE"
    )
    reviewed = review_request(request["id"])
    # 45 for job function, 0 for the missed industry, 25 for authority, +5 for WEB.
    assert reviewed["computed_score"] == 75

    verified = verify_request(
        request["id"],
        decision_reason="qualifies on job function and purchasing authority",
    )
    assert verified["status"] == "VERIFIED"
    assert verified["computed_score"] == 75

    recipient = read_subscriber(subscriber["id"])
    assert recipient["qualification_score"] == 75
    assert recipient["qualification_status"] == "QUALIFIED"
    assert recipient["qualified_at"].startswith("2026-08-01T00:00:00")
    assert recipient["qualification_expires_at"].startswith("2029-08-01T00:00:00")

    # An identical claim arriving by post earns 10 instead of 5.
    _, mail_request = score_through_channel(
        "Yankee Retail Group", "DIRECT_MAIL", "SIGNED_REQUEST_CARD"
    )
    assert review_request(mail_request["id"])["computed_score"] == 80


def test_breakdown_counts_only_qualified_recipients_inside_the_period():
    """The breakdown reads the two date fields, so an unqualified recipient contributes nothing.

    "A recipient contributes its `copies` to the statement when all of the
    following hold: it belongs to the statement's publication; its
    `delivery_status` is `DELIVERABLE`; its `qualified_at` is not null; its
    `qualified_at` falls strictly before `period_end`; and its
    `qualification_expires_at` is at or after `period_end`."

    Design: Corner/calculations/breakdown_counts_only_qualified_recipients_inside_the_period
    """
    publication = register_publication(
        name="Eligibility Filter Monthly", industry_code="MANUFACTURING"
    )
    three_dimension_policy(publication["id"])

    qualified = add_subscriber(
        publication["id"],
        company_name="Yankee Machining",
        job_function_code="ENGINEERING_MGMT",
        industry_code="MANUFACTURING",
        purchasing_authority_level="APPROVES",
        subscription_class="QUALIFIED_NON_PAID",
        copies=300,
    )
    never_claimed = add_subscriber(
        publication["id"],
        company_name="Zulu Machining",
        job_function_code="ENGINEERING_MGMT",
        industry_code="MANUFACTURING",
        purchasing_authority_level="APPROVES",
        subscription_class="QUALIFIED_NON_PAID",
        copies=300,
    )
    document = attach_source_document(
        qualified["id"], SPECIALIST_HEADERS, captured_at="2026-07-20T00:00:00Z"
    )
    request = open_request(
        qualified["id"],
        document["id"],
        qualified["version"],
        headers=SPECIALIST_HEADERS,
        signed_at="2026-07-20T00:00:00Z",
        attested_job_function_code="ENGINEERING_MGMT",
        attested_industry_code="MANUFACTURING",
        attested_purchasing_authority="APPROVES",
    )
    review_request(request["id"])
    verify_request(request["id"], decision_reason="qualified")

    move_clock("2026-10-01T00:00:00Z")
    stored_publication = read_publication(publication["id"])
    # Both recipients are on file even though only one of them qualifies.
    assert stored_publication["copies_on_file_total"] == 600

    statement = open_statement(
        publication["id"],
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    assert statement["qualified_non_paid_copies"] == 300
    assert statement["total_qualified_copies"] == 300
    assert statement["paid_copies"] == 0
    assert statement["controlled_copies_included"] == 0
    # The declared figure is frozen only by certification, never by creation.
    assert statement["declared_total_copies"] == 0

    assert read_subscriber(never_claimed["id"])["qualification_status"] == "UNQUALIFIED"
    assert read_subscriber(never_claimed["id"])["qualified_at"] is None
    assert_pct(statement["undeliverable_pct_at_close"], 0.00)


def test_reconciliation_discrepancy_exactly_at_materiality_forces_restatement():
    """The materiality comparison is inclusive, so exactly 2.00 percent condemns.

    "The boundary is inclusive and the arithmetic is unforgiving: 1,200 declared
    copies against 1,176 verified copies is a 24-copy discrepancy, which is 2.00
    percent, which against a materiality threshold of 2.00 forces a restatement
    rather than clearing."

    Design: Corner/calculations/reconciliation_discrepancy_exactly_at_materiality_forces_restatement
    """
    publication = register_publication(
        name="Materiality Boundary Monthly",
        industry_code="MANUFACTURING",
        materiality_pct=2.00,
    )
    three_dimension_policy(publication["id"])
    subscriber = add_subscriber(
        publication["id"],
        company_name="Acme Fabrication",
        job_function_code="ENGINEERING_MGMT",
        industry_code="MANUFACTURING",
        purchasing_authority_level="APPROVES",
        subscription_class="PAID",
        copies=1200,
        paid_amount_cents=24000,
    )
    document = attach_source_document(
        subscriber["id"], SPECIALIST_HEADERS, captured_at="2026-07-15T00:00:00Z"
    )
    request = open_request(
        subscriber["id"],
        document["id"],
        subscriber["version"],
        headers=SPECIALIST_HEADERS,
        signed_at="2026-07-01T00:00:00Z",
        attested_job_function_code="ENGINEERING_MGMT",
        attested_industry_code="MANUFACTURING",
        attested_purchasing_authority="APPROVES",
    )
    review_request(request["id"])
    verify_request(request["id"], decision_reason="qualified")

    move_clock("2026-10-01T00:00:00Z")
    statement = open_statement(
        publication["id"],
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    filed = certify_statement(statement["id"])
    assert filed["declared_total_copies"] == 1200

    engagement = open_engagement(
        filed["id"],
        auditor_org="Verified Audit Bureau",
        fieldwork_start="2026-10-05T00:00:00Z",
        fieldwork_end="2026-10-09T00:00:00Z",
        sample_size=1,
    )
    reconciling = record_sample(
        engagement["id"], subscriber["id"], evidence_ok=True, verified_copies=1176
    )
    # A sample size of 1 auto-advances past FIELDWORK inside the same request.
    assert reconciling["status"] == "RECONCILIATION"
    assert reconciling["verified_qualified_copies"] == 1176

    reported = validate_success(
        api_client.issue_report(
            engagement["id"],
            issue_report_payload(report_note="24 copies unsupported"),
            AUDITOR_HEADERS,
        ),
        200,
    )
    assert reported["status"] == "REPORT_ISSUED"

    condemned = read_statement(filed["id"])
    assert condemned["discrepancy_copies"] == 24
    assert_pct(condemned["discrepancy_pct"], 2.00)
    assert condemned["status"] == "RESTATEMENT_REQUIRED"
    assert read_publication(publication["id"])["audit_posture"] == "FROZEN"


def test_critical_finding_freezes_posture_over_the_restricted_clause():
    """The first matching clause wins, so a critical finding freezes over a restricted ratio.

    "1. If the publication's count of open critical findings,
    `open_critical_findings_count`, is greater than zero, the posture is
    `FROZEN`."

    Design: Corner/calculations/critical_finding_freezes_posture_over_the_restricted_clause
    """
    publication = register_publication(
        name="Posture Clause Monthly", industry_code="UTILITIES"
    )
    big = add_subscriber(
        publication["id"],
        company_name="Alpha Grid",
        job_function_code="PLANT_MGMT",
        industry_code="UTILITIES",
        subscription_class="CONTROLLED",
        copies=500,
    )
    small = add_subscriber(
        publication["id"],
        company_name="Bravo Grid",
        job_function_code="PLANT_MGMT",
        industry_code="UTILITIES",
        purchasing_authority_level="SPECIFIES",
        subscription_class="CONTROLLED",
        copies=100,
    )
    statement = open_statement(
        publication["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    filed = certify_statement(statement["id"])
    engagement = open_engagement(
        filed["id"],
        auditor_org="Verified Audit Bureau",
        fieldwork_start="2026-08-05T00:00:00Z",
        fieldwork_end="2026-08-09T00:00:00Z",
        sample_size=2,
    )
    in_fieldwork = record_sample(
        engagement["id"], big["id"], evidence_ok=False, verified_copies=0
    )
    assert in_fieldwork["status"] == "FIELDWORK"

    # One bounce is a signal only; the sweep is what turns it into a flag.
    validate_success(
        api_client.record_undeliverable_event(
            small["id"],
            undeliverable_event_payload(reason_code="RETURNED_MAIL"),
            MANAGER_HEADERS,
        ),
        200,
    )
    sweep = run_hygiene_sweep(publication["id"])
    assert sweep["posture_before"] == "OPEN"
    assert sweep["posture_after"] == "RESTRICTED"
    assert sweep["undeliverable_flagged_count"] == 1
    assert sweep["removed_count"] == 0
    # No DRAFT statement existed, so the posture move invalidated nothing.
    assert sweep["statements_invalidated_count"] == 0

    restricted = read_publication(publication["id"])
    # 100 undeliverable copies out of 600 on file is 16.67 percent.
    assert_pct(restricted["undeliverable_pct"], 16.67)
    assert restricted["audit_posture"] == "RESTRICTED"

    finding = validate_success(
        api_client.create_audit_finding(
            finding_payload(
                engagement["id"],
                subscriber_id=big["id"],
                finding_type="MISSING_SOURCE_DOC",
                severity="CRITICAL",
                affected_copies=500,
            ),
            AUDITOR_HEADERS,
        ),
        201,
    )
    assert finding["status"] == "OPEN"

    frozen = read_publication(publication["id"])
    assert frozen["open_critical_findings_count"] == 1
    # A CRITICAL finding is never also counted as MATERIAL.
    assert frozen["open_material_findings_count"] == 0
    # The restricted ratio is still true, but clause 1 matched first.
    assert_pct(frozen["undeliverable_pct"], 16.67)
    assert frozen["audit_posture"] == "FROZEN"

    assert read_statement(filed["id"])["status"] == "FINDINGS_OPEN"
