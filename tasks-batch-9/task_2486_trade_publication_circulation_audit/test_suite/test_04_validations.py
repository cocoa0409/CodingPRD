"""Rejection rules: uniqueness, conditional payment, policy gates, evidence ownership."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_AUDIT_WINDOW_CONFLICT,
    ERR_INVALID_PERIOD_RANGE,
    ERR_MANDATORY_CRITERION_NOT_MET,
    ERR_OPEN_FINDINGS_UNRESOLVED,
    ERR_PAID_REQUIRES_PAYMENT,
    ERR_PERIOD_NOT_ELAPSED,
    ERR_QUALIFICATION_RULES_INCOMPLETE,
    ERR_RESTATEMENT_NOT_REQUIRED,
    ERR_RETENTION_NOT_ELAPSED,
    ERR_RULE_DIMENSION_EXISTS,
    ERR_SAMPLE_LIMIT_EXCEEDED,
    ERR_SOURCE_DOCUMENT_SUBSCRIBER_MISMATCH,
)
from test_helpers.assertions import assert_ledger_buckets, assert_pct
from test_helpers.factories import (
    engagement_payload,
    industry_rule_payload,
    issue_report_payload,
    job_function_rule_payload,
    purchasing_authority_rule_payload,
    purge_payload,
    qualification_request_payload,
    reclassify_payload,
    sample_verification_payload,
    source_document_payload,
    statement_payload,
    verify_payload,
)
from test_helpers.fixtures import (
    accept_finding,
    add_complete_rule_set,
    add_rule,
    add_subscriber,
    attach_source_document,
    certify_statement,
    file_statement,
    move_clock,
    open_engagement,
    open_request,
    open_statement,
    qualified_population,
    raise_finding,
    read_publication,
    read_statement,
    read_subscriber,
    record_sample,
    register_publication,
    respond_to_finding,
    review_request,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    EXECUTIVE_HEADERS,
    MANAGER_HEADERS,
    SPECIALIST_HEADERS,
)


def test_duplicate_rule_dimension_rejected():
    """A publication may hold at most one rule per dimension.

    "A publication may hold at most one rule per dimension; a second attempt on
    a dimension the publication already defines is rejected with
    `ERR_RULE_DIMENSION_EXISTS` and HTTP 409."

    Design: Corner/validations/duplicate_rule_dimension_rejected
    """
    publication = register_publication(
        name="One Rule Per Dimension Monthly", industry_code="MANUFACTURING"
    )
    first = add_rule(
        publication["id"],
        job_function_rule_payload(
            allowed_values=["ENGINEERING_MGMT"], points=45, is_mandatory=True
        ),
    )

    response = api_client.create_qualification_rule(
        publication["id"],
        {
            "dimension": "JOB_FUNCTION",
            "allowed_values": ["PLANT_MGMT", "ENGINEERING_MGMT"],
            "points": 20,
        },
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_RULE_DIMENSION_EXISTS, 409)

    rules = validate_success(
        api_client.list_qualification_rules(
            publication["id"], MANAGER_HEADERS, params={"dimension": "JOB_FUNCTION"}
        ),
        200,
    )
    assert len(rules) == 1
    assert rules[0]["id"] == first["id"]
    assert rules[0]["allowed_values"] == ["ENGINEERING_MGMT"]
    assert rules[0]["points"] == 45
    assert rules[0]["is_mandatory"] is True

    # The uniqueness scope is the (publication, dimension) pair.
    validate_success(
        api_client.create_qualification_rule(
            publication["id"], industry_rule_payload(), MANAGER_HEADERS
        ),
        201,
    )


def test_reclassify_to_paid_without_payment_rejected():
    """The payment requirement is conditional on the target class being `PAID`.

    "a recipient created as `PAID`, or reclassified into `PAID`, must end up with
    `paid_amount_cents` of at least 1, counting either the value supplied on the
    request or the value already stored on the row."

    Design: Corner/validations/reclassify_to_paid_without_payment_rejected
    """
    publication = register_publication(
        name="Paid Class Guard Monthly", industry_code="MANUFACTURING"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Charlie Stamping",
        subscription_class="CONTROLLED",
        copies=100,
    )
    assert subscriber["paid_amount_cents"] == 0

    response = api_client.reclassify_subscriber(
        subscriber["id"], reclassify_payload("PAID"), MANAGER_HEADERS
    )
    validate_error(response, ERR_PAID_REQUIRES_PAYMENT, 422)

    assert read_subscriber(subscriber["id"])["subscription_class"] == "CONTROLLED"
    assert_ledger_buckets(read_publication(publication["id"]), total=100, controlled=100)

    response = api_client.reclassify_subscriber(
        subscriber["id"],
        reclassify_payload("PAID", paid_amount_cents=5000),
        MANAGER_HEADERS,
    )
    reclassified = validate_success(response, 200)
    assert reclassified["subscription_class"] == "PAID"
    assert reclassified["paid_amount_cents"] == 5000

    assert_ledger_buckets(
        read_publication(publication["id"]), total=100, paid=100, controlled=0
    )

    # A move back to CONTROLLED never requires a payment amount.
    response = api_client.reclassify_subscriber(
        subscriber["id"], reclassify_payload("CONTROLLED"), MANAGER_HEADERS
    )
    validate_success(response, 200)


def test_verify_with_incomplete_rule_set_rejected():
    """A partial qualification policy cannot produce a meaningful score.

    "The publication must hold a rule row for all three of `JOB_FUNCTION`,
    `INDUSTRY` and `PURCHASING_AUTHORITY`; a missing dimension fails with
    `ERR_QUALIFICATION_RULES_INCOMPLETE` and HTTP 409, and this check runs before
    scoring, since a partial policy cannot produce a meaningful number."

    Design: Corner/validations/verify_with_incomplete_rule_set_rejected
    """
    publication = register_publication(
        name="Incomplete Definition Monthly", industry_code="MANUFACTURING"
    )
    add_rule(
        publication["id"],
        job_function_rule_payload(
            allowed_values=["ENGINEERING_MGMT"], points=45, is_mandatory=True
        ),
    )
    add_rule(
        publication["id"],
        industry_rule_payload(allowed_values=["MANUFACTURING"], points=30),
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Delta Extrusions",
        job_function_code="ENGINEERING_MGMT",
        industry_code="MANUFACTURING",
        subscription_class="QUALIFIED_NON_PAID",
        copies=200,
    )
    document = attach_source_document(
        subscriber["id"],
        SPECIALIST_HEADERS,
        doc_type="EMAIL_CONFIRMATION",
        captured_at="2026-07-25T00:00:00Z",
        storage_ref="s3://circ/d-email",
    )
    request = open_request(
        subscriber["id"],
        document["id"],
        subscriber["version"],
        headers=SPECIALIST_HEADERS,
        request_channel="EMAIL",
        signed_at="2026-07-25T00:00:00Z",
        attested_job_function_code="ENGINEERING_MGMT",
        attested_industry_code="MANUFACTURING",
        attested_purchasing_authority="APPROVES",
    )
    reviewed = review_request(request["id"])
    # 45 + 30 + 0 for the undefined dimension, plus the EMAIL channel bonus of 5.
    assert reviewed["computed_score"] == 80

    response = api_client.verify_qualification_request(
        request["id"],
        verify_payload(
            decision_reason="attempting to qualify against an incomplete definition"
        ),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_QUALIFICATION_RULES_INCOMPLETE, 409)

    stored = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["decided_at"] is None

    recipient = read_subscriber(subscriber["id"])
    assert recipient["qualification_status"] == "PENDING_QUALIFICATION"
    assert recipient["qualification_score"] == 0


def test_mandatory_criterion_missed_after_score_passes_rejected():
    """The mandatory gate is only reachable once the score threshold has been cleared.

    "The threshold is checked first: a request that is both below 70 and short on
    a mandatory dimension reports `ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD` with
    HTTP 422, not the mandatory-criterion error."

    Design: Corner/validations/mandatory_criterion_missed_after_score_passes_rejected
    """
    publication = register_publication(
        name="Mandatory Gate Monthly", industry_code="MANUFACTURING"
    )
    add_rule(
        publication["id"],
        job_function_rule_payload(
            allowed_values=["ENGINEERING_MGMT"], points=20, is_mandatory=True
        ),
    )
    add_rule(
        publication["id"],
        industry_rule_payload(allowed_values=["MANUFACTURING"], points=50),
    )
    add_rule(
        publication["id"],
        purchasing_authority_rule_payload(allowed_values=["APPROVES"], points=30),
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Echo Distribution",
        job_function_code="SALES",
        industry_code="MANUFACTURING",
        subscription_class="QUALIFIED_NON_PAID",
        copies=250,
    )
    document = attach_source_document(
        subscriber["id"],
        SPECIALIST_HEADERS,
        captured_at="2026-07-10T00:00:00Z",
        storage_ref="s3://circ/e-card",
    )
    request = open_request(
        subscriber["id"],
        document["id"],
        subscriber["version"],
        headers=SPECIALIST_HEADERS,
        request_channel="DIRECT_MAIL",
        signed_at="2026-07-10T00:00:00Z",
        attested_job_function_code="SALES",
        attested_industry_code="MANUFACTURING",
        attested_purchasing_authority="APPROVES",
    )
    reviewed = review_request(request["id"])
    # 0 + 50 + 30 base, plus the DIRECT_MAIL channel bonus of 10.
    assert reviewed["computed_score"] == 90

    response = api_client.verify_qualification_request(
        request["id"],
        verify_payload(decision_reason="score is high enough"),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_MANDATORY_CRITERION_NOT_MET, 422)

    stored = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["computed_score"] == 90

    recipient = read_subscriber(subscriber["id"])
    assert recipient["qualification_status"] == "PENDING_QUALIFICATION"
    assert recipient["qualified_at"] is None


def test_request_citing_another_subscribers_document_rejected():
    """Cited evidence must belong to the recipient making the claim.

    "If the named source document's `subscriber_id` is not the `subscriber_id` on
    the request, the create fails with
    `ERR_SOURCE_DOCUMENT_SUBSCRIBER_MISMATCH` and HTTP 422".

    Design: Corner/validations/request_citing_another_subscribers_document_rejected
    """
    publication = register_publication(
        name="Evidence Ownership Monthly", industry_code="MANUFACTURING"
    )
    sub_f = add_subscriber(
        publication["id"],
        company_name="Foxtrot Forging",
        subscription_class="CONTROLLED",
        copies=90,
    )
    sub_g = add_subscriber(
        publication["id"],
        company_name="Golf Gearworks",
        subscription_class="CONTROLLED",
        copies=60,
    )
    document = attach_source_document(
        sub_f["id"],
        SPECIALIST_HEADERS,
        captured_at="2026-07-12T00:00:00Z",
        storage_ref="s3://circ/f-card",
    )
    assert document["purge_status"] == "RETAINED"

    response = api_client.create_qualification_request(
        qualification_request_payload(
            sub_g["id"],
            document["id"],
            sub_g["version"],
            request_channel="DIRECT_MAIL",
            signed_at="2026-07-12T00:00:00Z",
            attested_job_function_code="ENGINEERING_MGMT",
            attested_industry_code="MANUFACTURING",
            attested_purchasing_authority="APPROVES",
        ),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_SOURCE_DOCUMENT_SUBSCRIBER_MISMATCH, 422)
    assert read_subscriber(sub_g["id"])["version"] == sub_g["version"]

    # The mismatch was the only defect: the document's own recipient may cite it.
    response = api_client.create_qualification_request(
        qualification_request_payload(
            sub_f["id"],
            document["id"],
            sub_f["version"],
            signed_at="2026-07-12T00:00:00Z",
        ),
        SPECIALIST_HEADERS,
    )
    validate_success(response, 201)


def test_statement_with_end_before_start_rejected():
    """An inverted range is caught before the period-elapsed check.

    "`period_start` is inclusive and `period_end` is exclusive — and
    `period_start` must fall strictly before `period_end`, or the create is
    rejected with `ERR_INVALID_PERIOD_RANGE`."

    Design: Corner/validations/statement_with_end_before_start_rejected
    """
    publication = register_publication(
        name="Inverted Range Quarterly",
        frequency="QUARTERLY",
        industry_code="MANUFACTURING",
    )
    version = publication["version"]

    # The end lies before the start, and the start also lies in the future, so
    # the not-elapsed rule would fire too. The range check wins.
    response = api_client.create_statement(
        statement_payload(
            publication["id"],
            version,
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_INVALID_PERIOD_RANGE, 422)

    # An empty range is equally inverted: strictly before means strictly before.
    response = api_client.create_statement(
        statement_payload(
            publication["id"],
            version,
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-05-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_INVALID_PERIOD_RANGE, 422)

    assert read_publication(publication["id"])["version"] == version

    response = api_client.create_statement(
        statement_payload(
            publication["id"],
            version,
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    ordered = validate_success(response, 201)
    assert ordered["status"] == "DRAFT"


def test_statement_for_period_not_yet_closed_rejected():
    """A period whose end lies past the clock has not closed and may not be stated.

    "The period must also be over: if `period_end` lies after the current logical
    clock, the create is rejected with `ERR_PERIOD_NOT_ELAPSED`. No statement may
    be produced for a period that has not closed."

    Design: Corner/validations/statement_for_period_not_yet_closed_rejected
    """
    publication = register_publication(
        name="Open Period Monthly", industry_code="LOGISTICS"
    )
    version = publication["version"]

    response = api_client.create_statement(
        statement_payload(
            publication["id"],
            version,
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_PERIOD_NOT_ELAPSED, 422)

    # A rejected create mutates nothing, so the same expected version still holds.
    assert read_publication(publication["id"])["version"] == version

    # A `period_end` exactly equal to the clock counts as closed: the rule only
    # rejects an end that lies *after* the clock.
    response = api_client.create_statement(
        statement_payload(
            publication["id"],
            version,
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    closed = validate_success(response, 201)
    assert closed["status"] == "DRAFT"
    assert closed["period_end"].startswith("2026-08-01T00:00:00")
    assert closed["statement_type"] == "PUBLISHER_STATEMENT"
    assert closed["declared_total_copies"] == 0


def test_second_engagement_inside_fourteen_day_buffer_rejected():
    """Fieldwork separation is measured publication-wide, end-to-start, in either direction.

    "A new engagement's closed fieldwork interval must keep at least fourteen
    clear days — two full weeks — between itself and the interval of every other
    engagement of the same publication, reached through each engagement's
    `statement_id`, whose `status` is anything other than `REPORT_ISSUED`."

    Design: Corner/validations/second_engagement_inside_fourteen_day_buffer_rejected
    """
    publication = register_publication(
        name="Fieldwork Buffer Quarterly",
        frequency="QUARTERLY",
        industry_code="UTILITIES",
    )
    first_statement = file_statement(
        publication["id"],
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
    )
    second_statement = file_statement(
        publication["id"],
        period_start="2026-04-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    assert first_statement["status"] == "FILED"
    assert second_statement["status"] == "FILED"

    early = open_engagement(
        first_statement["id"],
        auditor_org="Bureau of Trade Circulation Audits",
        fieldwork_start="2026-08-05T00:00:00Z",
        fieldwork_end="2026-08-09T00:00:00Z",
        sample_size=2,
    )
    assert early["status"] == "SCHEDULED"
    assert read_statement(first_statement["id"])["status"] == "UNDER_AUDIT"

    # 9 August to 15 August leaves only the five clear days 10-14 August.
    response = api_client.create_audit_engagement(
        engagement_payload(
            second_statement["id"],
            auditor_org="Independent Circulation Review",
            fieldwork_start="2026-08-15T00:00:00Z",
            fieldwork_end="2026-08-20T00:00:00Z",
            sample_size=1,
        ),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_AUDIT_WINDOW_CONFLICT, 409)
    assert read_statement(second_statement["id"])["status"] == "FILED"

    # 9 August to 24 August leaves exactly the fourteen clear days 10-23 August.
    response = api_client.create_audit_engagement(
        engagement_payload(
            second_statement["id"],
            auditor_org="Independent Circulation Review",
            fieldwork_start="2026-08-24T00:00:00Z",
            fieldwork_end="2026-08-28T00:00:00Z",
            sample_size=1,
        ),
        AUDITOR_HEADERS,
    )
    accepted = validate_success(response, 201)
    assert accepted["status"] == "SCHEDULED"
    assert read_statement(second_statement["id"])["status"] == "UNDER_AUDIT"


def test_record_duplicate_sample_subscriber_rejected():
    """One error code guards both sample exhaustion and double-counting a recipient.

    "Once in `RECONCILIATION` the engagement is frozen for further sampling:
    another record is rejected with `ERR_SAMPLE_LIMIT_EXCEEDED` and HTTP 409, and
    that same error also guards against double-counting — recording the same
    `subscriber_id` twice against one engagement is refused, because a sample of
    thirty distinct records is not a sample of one record thirty times."

    Design: Corner/validations/record_duplicate_sample_subscriber_rejected
    """
    publication = register_publication(
        name="Sample Discipline Monthly", industry_code="UTILITIES"
    )
    sub_a = add_subscriber(
        publication["id"],
        company_name="Alpha Grid",
        subscription_class="CONTROLLED",
        copies=500,
    )
    sub_b = add_subscriber(
        publication["id"],
        company_name="Bravo Grid",
        subscription_class="CONTROLLED",
        copies=300,
    )
    sub_c = add_subscriber(
        publication["id"],
        company_name="Charlie Grid",
        subscription_class="CONTROLLED",
        copies=200,
    )
    statement = file_statement(
        publication["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
    )
    engagement = open_engagement(
        statement["id"],
        fieldwork_start="2026-08-05T00:00:00Z",
        fieldwork_end="2026-08-09T00:00:00Z",
        sample_size=2,
    )

    after_first = record_sample(
        engagement["id"], sub_a["id"], evidence_ok=True, verified_copies=480
    )
    assert after_first["status"] == "FIELDWORK"
    assert after_first["sample_verified_count"] == 1
    assert after_first["verified_qualified_copies"] == 480

    response = api_client.record_sample_verification(
        engagement["id"],
        sample_verification_payload(sub_a["id"], evidence_ok=True, verified_copies=480),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_SAMPLE_LIMIT_EXCEEDED, 409)

    rows = validate_success(
        api_client.list_audit_engagements(statement["id"], AUDITOR_HEADERS), 200
    )
    unchanged = [row for row in rows if row["id"] == engagement["id"]][0]
    assert unchanged["status"] == "FIELDWORK"
    assert unchanged["sample_verified_count"] == 1
    assert unchanged["verified_qualified_copies"] == 480

    after_second = record_sample(
        engagement["id"], sub_b["id"], evidence_ok=True, verified_copies=290
    )
    assert after_second["status"] == "RECONCILIATION"
    assert after_second["sample_verified_count"] == 2
    assert after_second["verified_qualified_copies"] == 770

    # A distinct recipient is still refused, because reconciliation has begun.
    response = api_client.record_sample_verification(
        engagement["id"],
        sample_verification_payload(sub_c["id"], evidence_ok=True, verified_copies=200),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_SAMPLE_LIMIT_EXCEEDED, 409)


def test_issue_report_with_immaterial_variance_and_live_finding_rejected():
    """An immaterial variance may not be used to close an engagement with live exceptions.

    "When `discrepancy_pct` is strictly below `materiality_pct` but the statement
    is in `FINDINGS_OPEN` — meaning at least one finding of the engagement is
    still `OPEN`, `RESPONSE_SUBMITTED` or `REJECTED_REOPENED` — the report is
    refused with `ERR_OPEN_FINDINGS_UNRESOLVED` and HTTP 409".

    Design: Corner/validations/issue_report_with_immaterial_variance_and_live_finding_rejected
    """
    publication = register_publication(
        name="Live Exception Monthly", industry_code="MANUFACTURING", materiality_pct=2.00
    )
    add_complete_rule_set(publication["id"])
    members = qualified_population(
        publication["id"],
        [{"subscription_class": "PAID", "paid_amount_cents": 24000, "copies": 1200}],
    )
    recipient = members[0]["subscriber"]

    move_clock("2026-10-01T00:00:00Z")
    statement = open_statement(
        publication["id"],
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )
    filed = certify_statement(statement["id"], EXECUTIVE_HEADERS)
    assert filed["declared_total_copies"] == 1200

    engagement = open_engagement(
        filed["id"],
        fieldwork_start="2026-09-05T00:00:00Z",
        fieldwork_end="2026-09-10T00:00:00Z",
        sample_size=1,
    )
    reconciling = record_sample(
        engagement["id"], recipient["id"], evidence_ok=True, verified_copies=1190
    )
    assert reconciling["status"] == "RECONCILIATION"
    assert reconciling["verified_qualified_copies"] == 1190

    finding = raise_finding(
        engagement["id"],
        subscriber_id=recipient["id"],
        finding_type="EXPIRED_QUALIFICATION",
        severity="MINOR",
        affected_copies=5,
    )
    assert finding["status"] == "OPEN"
    assert read_statement(filed["id"])["status"] == "FINDINGS_OPEN"
    # A MINOR finding moves neither open-findings counter, so posture stays OPEN.
    assert read_publication(publication["id"])["audit_posture"] == "OPEN"

    response = api_client.issue_report(
        engagement["id"], issue_report_payload(), AUDITOR_HEADERS
    )
    validate_error(response, ERR_OPEN_FINDINGS_UNRESOLVED, 409)
    blocked = read_statement(filed["id"])
    assert blocked["status"] == "FINDINGS_OPEN"
    engagement_rows = validate_success(
        api_client.list_audit_engagements(filed["id"], AUDITOR_HEADERS), 200
    )
    still_reconciling = [
        row for row in engagement_rows if row["id"] == engagement["id"]
    ][0]
    assert still_reconciling["status"] == "RECONCILIATION"
    assert still_reconciling["report_issued_at"] is None

    respond_to_finding(finding["id"])
    accept_finding(finding["id"])
    assert read_statement(filed["id"])["status"] == "UNDER_AUDIT"

    reported = validate_success(
        api_client.issue_report(
            engagement["id"], issue_report_payload(), AUDITOR_HEADERS
        ),
        200,
    )
    assert reported["status"] == "REPORT_ISSUED"

    cleared = read_statement(filed["id"])
    assert cleared["status"] == "AUDIT_CLEARED"
    assert cleared["statement_type"] == "PUBLISHER_STATEMENT"
    assert cleared["discrepancy_copies"] == 10
    # 10 copies against 1,200 declared is 0.8333..., rounded half up to 0.83.
    assert_pct(cleared["discrepancy_pct"], 0.83)
    assert reported["report_issued_at"].startswith("2026-10-01T00:00:00")
    assert read_publication(publication["id"])["audit_posture"] == "OPEN"


def test_restating_a_filed_statement_rejected():
    """A restatement may only replace a predecessor the audit actually condemned.

    "when supplied, it must name a statement of the *same* publication whose
    `status` is `RESTATEMENT_REQUIRED`, and anything else — a statement of
    another publication, or one in any other status — is rejected with
    `ERR_RESTATEMENT_NOT_REQUIRED` and HTTP 409."

    Design: Corner/validations/restating_a_filed_statement_rejected
    """
    publication = register_publication(
        name="Restatement Guard Quarterly",
        frequency="QUARTERLY",
        industry_code="LOGISTICS",
    )
    predecessor = file_statement(
        publication["id"],
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
    )
    assert predecessor["status"] == "FILED"
    assert predecessor["restates_statement_id"] is None

    version = read_publication(publication["id"])["version"]
    response = api_client.create_statement(
        statement_payload(
            publication["id"],
            version,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            restates_statement_id=predecessor["id"],
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_RESTATEMENT_NOT_REQUIRED, 409)

    # A predecessor belonging to a different title is refused by the same rule.
    other = register_publication(
        name="Unrelated Title Quarterly",
        frequency="QUARTERLY",
        industry_code="UTILITIES",
    )
    other_version = read_publication(other["id"])["version"]
    response = api_client.create_statement(
        statement_payload(
            other["id"],
            other_version,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            restates_statement_id=predecessor["id"],
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_RESTATEMENT_NOT_REQUIRED, 409)

    # Omitting the field entirely leaves an ordinary original statement.
    original = open_statement(
        publication["id"],
        period_start="2026-04-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    assert original["restates_statement_id"] is None
    assert original["status"] == "DRAFT"


def test_purge_before_retention_elapsed_rejected():
    """The retention comparison is inclusive: reaching the deadline is enough.

    "A purge may only proceed when the current logical clock has reached or
    passed the document's `retention_expires_at`; an early attempt is rejected
    with `ERR_RETENTION_NOT_ELAPSED` and HTTP 409."

    Design: Corner/validations/purge_before_retention_elapsed_rejected
    """
    publication = register_publication(
        name="Retention Clock Monthly", industry_code="MANUFACTURING"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Delta Rolling Mill",
        subscription_class="CONTROLLED",
        copies=70,
    )
    document = validate_success(
        api_client.create_source_document(
            subscriber["id"],
            source_document_payload(
                doc_type="SIGNED_REQUEST_CARD",
                captured_at="2026-07-15T00:00:00Z",
                storage_ref="s3://circ/d-card",
            ),
            SPECIALIST_HEADERS,
        ),
        201,
    )
    # The default retention of 36 months carries the deadline to 2029-07-15.
    assert document["retention_expires_at"].startswith("2029-07-15T00:00:00")
    assert document["purge_status"] == "RETAINED"

    response = api_client.purge_source_document(
        document["id"], purge_payload(purge_reason="early spring cleaning"), MANAGER_HEADERS
    )
    validate_error(response, ERR_RETENTION_NOT_ELAPSED, 409)

    rows = validate_success(
        api_client.list_source_documents(subscriber["id"], SPECIALIST_HEADERS), 200
    )
    survivor = [row for row in rows if row["id"] == document["id"]][0]
    assert survivor["purge_status"] == "RETAINED"
    assert survivor["purged_at"] is None
    assert survivor["version"] == 1

    # One day short of the deadline is still an early attempt.
    move_clock("2029-07-14T00:00:00Z")
    response = api_client.purge_source_document(
        document["id"], purge_payload(purge_reason="one day early"), MANAGER_HEADERS
    )
    validate_error(response, ERR_RETENTION_NOT_ELAPSED, 409)

    move_clock("2029-07-15T00:00:00Z")
    purged = validate_success(
        api_client.purge_source_document(
            document["id"],
            purge_payload(purge_reason="retention period elapsed"),
            MANAGER_HEADERS,
        ),
        200,
    )
    assert purged["purge_status"] == "PURGED"
    assert purged["purged_at"].startswith("2029-07-15T00:00:00")
    assert purged["version"] == 2
