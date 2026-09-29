"""Lifecycle behaviour: birth states, refused transitions, terminal locks and loops."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_REQUEST_NOT_UNDER_REVIEW,
)
from test_helpers.factories import (
    digital_snapshot_payload,
    engagement_payload,
    resubmit_payload,
    snapshot_decision_payload,
    verify_payload,
)
from test_helpers.fixtures import (
    add_subscriber,
    attach_source_document,
    certify_statement,
    open_engagement,
    open_request,
    open_statement,
    raise_finding,
    read_publication,
    read_statement,
    read_subscriber,
    register_publication,
    respond_to_finding,
    review_request,
)
from test_helpers.test_users import (
    AUDITOR_2_HEADERS,
    AUDITOR_HEADERS,
    AUDITOR_PRIMARY,
    MANAGER_HEADERS,
    MANAGER_PRIMARY,
    SPECIALIST_HEADERS,
)


def test_new_statement_starts_in_draft_with_null_certification_fields():
    """A statement is born in DRAFT with every certification field still empty.

    "A statement is born in `DRAFT`, with `prepared_by_user_id` stamped from the
    acting `X-User-ID`, `breakdown_stale` false, and the publication's `version`
    advanced by 1. `declared_total_copies` is not written by creation or by any
    recompute; it holds its initial value of 0 until certification freezes it."

    Design: Corner/state_machines/new_statement_starts_in_draft_with_null_certification_fields
    """
    publication = register_publication(
        name="Initial State Monthly", industry_code="MANUFACTURING"
    )
    add_subscriber(
        publication["id"],
        company_name="Sierra Castings",
        subscription_class="CONTROLLED",
        copies=500,
    )

    statement = open_statement(
        publication["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
    )
    assert statement["status"] == "DRAFT"
    # `basis` defaults to the publisher's own view and drives `statement_type`.
    assert statement["basis"] == "AS_OF_PERIOD_END"
    assert statement["statement_type"] == "PUBLISHER_STATEMENT"

    assert statement["filed_at"] is None
    assert statement["certified_by_user_id"] is None
    assert statement["guarantees_settled_at"] is None
    assert statement["prepared_by_user_id"] == MANAGER_PRIMARY
    assert statement["breakdown_stale"] is False
    assert statement["declared_total_copies"] == 0
    # The single CONTROLLED recipient was never verified, so nothing qualifies.
    assert statement["total_qualified_copies"] == 0
    assert statement["restates_statement_id"] is None


def test_verify_request_from_submitted_rejected():
    """Verification is declared only from UNDER_REVIEW, and that gate outranks policy checks.

    "Rejecting a request requires a `decision_reason` and is permitted only from
    `UNDER_REVIEW`; on any other status the attempt is rejected with
    `ERR_REQUEST_NOT_UNDER_REVIEW` and HTTP 409, and that same error guards
    information requests and verifications."

    Design: Corner/state_machines/verify_request_from_submitted_rejected
    """
    # The publication deliberately holds no qualification rules at all, so a
    # verification that got past the state gate would fail on policy instead.
    publication = register_publication(
        name="Review Gate Journal", industry_code="MANUFACTURING"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Uniform Presses",
        contact_email="u@uniform.test",
        subscription_class="CONTROLLED",
        copies=70,
    )
    document = attach_source_document(
        subscriber["id"],
        SPECIALIST_HEADERS,
        captured_at="2026-07-10T00:00:00Z",
        storage_ref="s3://circ/u-card",
    )
    request = open_request(
        subscriber["id"],
        document["id"],
        subscriber["version"],
        headers=SPECIALIST_HEADERS,
        signed_at="2026-07-01T00:00:00Z",
    )
    assert request["status"] == "SUBMITTED"

    response = api_client.verify_qualification_request(
        request["id"], verify_payload(decision_reason="skipping review"), SPECIALIST_HEADERS
    )
    validate_error(response, ERR_REQUEST_NOT_UNDER_REVIEW, 409)

    stored = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert stored["status"] == "SUBMITTED"
    assert stored["decided_at"] is None
    assert stored["computed_score"] == 0
    assert read_subscriber(subscriber["id"])["qualification_status"] == "PENDING_QUALIFICATION"


def test_resubmit_rejected_request_rejected():
    """REJECTED is terminal, and a refused resubmission applies none of its payload.

    "the 'entity is already terminal' check (`ERR_ALREADY_TERMINAL`)".

    Design: Corner/state_machines/resubmit_rejected_request_rejected
    """
    publication = register_publication(
        name="Terminal Lock Journal", industry_code="MANUFACTURING"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Victor Grinding",
        contact_email="v@victor.test",
        job_function_code="SALES",
        industry_code="RETAIL",
        purchasing_authority_level="NONE",
        subscription_class="CONTROLLED",
        copies=20,
    )
    document = attach_source_document(
        subscriber["id"],
        SPECIALIST_HEADERS,
        doc_type="TELEPHONE_SCRIPT_LOG",
        captured_at="2026-07-05T00:00:00Z",
        storage_ref="s3://circ/v-log",
    )
    request = open_request(
        subscriber["id"],
        document["id"],
        subscriber["version"],
        headers=SPECIALIST_HEADERS,
        request_channel="TELEPHONE",
        signed_at="2026-07-05T00:00:00Z",
        attested_job_function_code="SALES",
        attested_industry_code="RETAIL",
        attested_purchasing_authority="NONE",
    )
    review_request(request["id"])

    rejected = validate_success(
        api_client.reject_qualification_request(
            request["id"],
            {
                "decision_reason": (
                    "job function and industry both outside the qualified definition"
                )
            },
            SPECIALIST_HEADERS,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["decided_at"].startswith("2026-08-01T00:00:00")

    response = api_client.resubmit_qualification_request(
        request["id"],
        resubmit_payload(attested_purchasing_authority="APPROVES"),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_ALREADY_TERMINAL, 409)

    stored = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert stored["status"] == "REJECTED"
    # The refused payload is not partially applied.
    assert stored["attested_purchasing_authority"] == "NONE"
    # The recipient had never been qualified, so refusal drops it to UNQUALIFIED.
    assert read_subscriber(subscriber["id"])["qualification_status"] == "UNQUALIFIED"


def test_finding_response_rejection_reopens_then_resolves_on_second_response():
    """The response cycle may turn indefinitely, and `response_count` records the turns.

    "The cycle `RESPONSE_SUBMITTED → REJECTED_REOPENED → RESPONSE_SUBMITTED` may
    turn indefinitely, and `response_count` is the record of how many turns it
    took."

    Design: Corner/state_machines/finding_response_rejection_reopens_then_resolves_on_second_response
    """
    publication = register_publication(
        name="Finding Loop Monthly", industry_code="MANUFACTURING"
    )
    subscriber = add_subscriber(
        publication["id"],
        company_name="Whiskey Alloys",
        subscription_class="CONTROLLED",
        copies=500,
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
    assert engagement["status"] == "SCHEDULED"
    assert read_statement(filed["id"])["status"] == "UNDER_AUDIT"

    # A finding may only be raised once the engagement has entered fieldwork, and
    # the sample of two keeps it there rather than auto-advancing.
    in_fieldwork = validate_success(
        api_client.record_sample_verification(
            engagement["id"],
            {"subscriber_id": subscriber["id"], "evidence_ok": False, "verified_copies": 0},
            AUDITOR_HEADERS,
        ),
        200,
    )
    assert in_fieldwork["status"] == "FIELDWORK"

    finding = raise_finding(
        engagement["id"],
        subscriber_id=subscriber["id"],
        finding_type="MISSING_SOURCE_DOC",
        severity="MATERIAL",
        affected_copies=100,
    )
    assert finding["status"] == "OPEN"
    assert finding["response_count"] == 0
    assert finding["raised_by_user_id"] == AUDITOR_PRIMARY
    assert read_statement(filed["id"])["status"] == "FINDINGS_OPEN"

    first = respond_to_finding(
        finding["id"], response_note="card located in the archive, scan attached"
    )
    assert first["status"] == "RESPONSE_SUBMITTED"
    assert first["response_count"] == 1

    reopened = validate_success(
        api_client.reject_finding_response(
            finding["id"],
            {"rejection_note": "scan is undated and unsigned"},
            AUDITOR_HEADERS,
        ),
        200,
    )
    assert reopened["status"] == "REJECTED_REOPENED"
    # The finding stays counted, so the publication does not relax.
    assert read_publication(publication["id"])["open_material_findings_count"] == 1
    assert read_publication(publication["id"])["audit_posture"] == "RESTRICTED"

    second = respond_to_finding(
        finding["id"], response_note="signed and dated card re-scanned"
    )
    assert second["status"] == "RESPONSE_SUBMITTED"
    assert second["response_count"] == 2

    resolved = validate_success(
        api_client.accept_finding_resolution(
            finding["id"], {"resolution_note": "evidence accepted"}, AUDITOR_2_HEADERS
        ),
        200,
    )
    assert resolved["status"] == "ACCEPTED_RESOLVED"
    assert resolved["resolved_at"].startswith("2026-08-01T00:00:00")

    assert read_statement(filed["id"])["status"] == "UNDER_AUDIT"
    stored_publication = read_publication(publication["id"])
    assert stored_publication["open_material_findings_count"] == 0
    assert stored_publication["audit_posture"] == "OPEN"

    rows = validate_success(
        api_client.list_audit_engagements(filed["id"], AUDITOR_HEADERS), 200
    )
    closed_engagement = [row for row in rows if row["id"] == engagement["id"]][0]
    assert closed_engagement["status"] == "FIELDWORK"
    assert closed_engagement["open_findings_count"] == 0


def test_create_engagement_on_draft_statement_rejected():
    """An audit may only be opened against a statement the publisher has certified.

    "Opening an engagement requires the target statement to be in `FILED`; from
    any other status the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/create_engagement_on_draft_statement_rejected
    """
    publication = register_publication(
        name="Draft Guard Monthly", industry_code="LOGISTICS"
    )
    statement = open_statement(
        publication["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
    )
    assert statement["status"] == "DRAFT"

    response = api_client.create_audit_engagement(
        engagement_payload(
            statement["id"],
            auditor_org="Verified Audit Bureau",
            fieldwork_start="2026-08-05T00:00:00Z",
            fieldwork_end="2026-08-09T00:00:00Z",
            sample_size=1,
        ),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_INVALID_STATE, 409)

    rows = validate_success(
        api_client.list_audit_engagements(statement["id"], AUDITOR_HEADERS), 200
    )
    assert rows == []
    assert read_statement(statement["id"])["status"] == "DRAFT"


def test_reject_uncertified_digital_snapshot_moves_to_rejected():
    """Uncertified analytics may be recorded and rejected; only validation is gated.

    "A `REJECT` decision moves it `RECORDED → REJECTED`, also stamping
    `validated_by_user_id`, and the snapshot never contributes to any statement."

    Design: Corner/state_machines/reject_uncertified_digital_snapshot_moves_to_rejected
    """
    publication = register_publication(
        name="Digital Audience Monthly", industry_code="MANUFACTURING"
    )
    snapshot = validate_success(
        api_client.create_digital_snapshot(
            publication["id"],
            digital_snapshot_payload(
                window_start="2026-06-01T00:00:00Z",
                window_end="2026-07-01T00:00:00Z",
                website_unique_visitors=20000,
                newsletter_sends=30000,
                newsletter_unique_opens=9000,
                overlap_pct=10.00,
                source="INTERNAL_ANALYTICS",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert snapshot["status"] == "RECORDED"
    assert snapshot["combined_reach_gross"] == 29000
    # 9,000 opens discounted by the 10.00 percent overlap is 8,100, plus 20,000.
    assert snapshot["combined_reach_deduplicated"] == 28100

    rejected = validate_success(
        api_client.validate_digital_snapshot(
            snapshot["id"], snapshot_decision_payload("REJECT"), AUDITOR_HEADERS
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["validated_by_user_id"] == AUDITOR_PRIMARY

    # A rejected snapshot never reaches a statement's verified digital reach.
    statement = open_statement(
        publication["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
    )
    assert statement["digital_reach_verified"] == 0

    # Both adjudicated states are terminal.
    response = api_client.validate_digital_snapshot(
        snapshot["id"], snapshot_decision_payload("REJECT"), AUDITOR_HEADERS
    )
    validate_error(response, ERR_ALREADY_TERMINAL, 409)
