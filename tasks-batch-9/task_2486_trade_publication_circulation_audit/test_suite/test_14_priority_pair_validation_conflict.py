"""Requests that break two rules at once must report the higher rung of §2.12's ladder."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SOURCE_DOCUMENT_PURGED,
    ERR_STATEMENT_NOT_DRAFT,
)
from test_helpers.factories import (
    certify_payload,
    purge_payload,
    recompute_payload,
    verify_payload,
)
from test_helpers.fixtures import (
    add_complete_rule_set,
    add_subscriber,
    attach_source_document,
    certify_statement,
    move_clock,
    open_request,
    open_statement,
    read_statement,
    read_subscriber,
    register_publication,
    review_request,
)
from test_helpers.test_users import (
    EXECUTIVE_HEADERS,
    EXECUTIVE_PRIMARY,
    MANAGER_HEADERS,
    MANAGER_PRIMARY,
    SPECIALIST_HEADERS,
)

QUARTER_START = "2026-01-01T00:00:00Z"
QUARTER_END = "2026-04-01T00:00:00Z"


def empty_publication(name):
    """A publication with no recipients at all, so every copy counter is 0."""
    publication = register_publication(name=name, industry_code="MANUFACTURING")
    assert publication["copies_on_file_total"] == 0
    assert publication["audit_posture"] == "OPEN"
    return publication


def test_recertifying_a_filed_statement_reports_the_state_rung_not_the_duties_rung():
    """The preparer re-certifying a FILED statement is refused for the state, not the duties.

    "**State preconditions**, in this internal order: the statement-must-be-`DRAFT`
    check (`ERR_STATEMENT_NOT_DRAFT`), then the request-must-be-`UNDER_REVIEW` check
    (`ERR_REQUEST_NOT_UNDER_REVIEW`), then the general "this trigger is not declared
    from the entity's current state" check (`ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/certify_filed_statement_by_preparer_rejects_not_draft_over_sod
    """
    publication = empty_publication("Ladder Order Monthly")

    # Prepared by mgr-01 at the default clock, so the quarter has closed.
    statement = open_statement(
        publication["id"],
        period_start=QUARTER_START,
        period_end=QUARTER_END,
        basis="AS_OF_PERIOD_END",
        headers=MANAGER_HEADERS,
    )
    assert statement["prepared_by_user_id"] == MANAGER_PRIMARY
    assert statement["declared_total_copies"] == 0

    filed = certify_statement(statement["id"], headers=EXECUTIVE_HEADERS)
    assert filed["status"] == "FILED"
    assert filed["certified_by_user_id"] == EXECUTIVE_PRIMARY
    assert filed["declared_total_copies"] == 0

    # The acting user is the preparer, so the duties gate is violated too.
    response = api_client.certify_statement(
        statement["id"],
        certify_payload(certification_note="preparer tries to re-certify"),
        MANAGER_HEADERS,
    )
    error = validate_error(response, ERR_STATEMENT_NOT_DRAFT, 409)
    assert error["error_id"] != ERR_SEGREGATION_OF_DUTIES

    unchanged = read_statement(statement["id"])
    assert unchanged["status"] == "FILED"
    assert unchanged["certified_by_user_id"] == EXECUTIVE_PRIMARY
    assert unchanged["declared_total_copies"] == 0


def test_duties_rung_is_the_one_that_answers_while_the_statement_is_still_draft():
    """With the state precondition satisfied the same caller hits the duties gate instead.

    "**First**, separation of duties: the acting `X-User-ID` must differ from the
    statement's `prepared_by_user_id`. The operator who assembled the numbers may
    never be the one who swears to them, and an attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/certify_filed_statement_by_preparer_rejects_not_draft_over_sod
    """
    publication = empty_publication("Duties Gate Monthly")
    statement = open_statement(
        publication["id"],
        period_start=QUARTER_START,
        period_end=QUARTER_END,
        basis="AS_OF_PERIOD_END",
        headers=MANAGER_HEADERS,
    )
    assert statement["status"] == "DRAFT"
    assert statement["prepared_by_user_id"] == MANAGER_PRIMARY

    # Only one rule is broken now, and it is the lower rung, so it answers.
    validate_error(
        api_client.certify_statement(
            statement["id"],
            certify_payload(certification_note="preparer swears to its own numbers"),
            MANAGER_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    still_draft = read_statement(statement["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["filed_at"] is None

    filed = certify_statement(statement["id"], headers=EXECUTIVE_HEADERS)
    assert filed["status"] == "FILED"

    # Recompute is guarded by the same state rung as certification.
    validate_error(
        api_client.recompute_statement(
            statement["id"], recompute_payload(), MANAGER_HEADERS
        ),
        ERR_STATEMENT_NOT_DRAFT,
        409,
    )


def reviewed_request_scoring_sixty_five(publication_name, signed_at="2025-06-01T00:00:00Z"):
    """A reviewed request whose stale signature and unlisted authority leave it under 70."""
    publication = register_publication(
        name=publication_name,
        industry_code="MANUFACTURING",
        source_doc_retention_months=1,
    )
    add_complete_rule_set(publication["id"])
    recipient = add_subscriber(
        publication["id"],
        company_name="Charlie Metalworks",
        subscription_class="CONTROLLED",
        copies=80,
    )
    document = attach_source_document(
        recipient["id"], MANAGER_HEADERS, captured_at="2026-07-15T00:00:00Z"
    )
    assert document["purge_status"] == "RETAINED"
    # One month of retention from capture, so the card may be destroyed in August.
    assert document["retention_expires_at"].startswith("2026-08-15T00:00:00")

    request = open_request(
        recipient["id"],
        document["id"],
        recipient["version"],
        headers=SPECIALIST_HEADERS,
        request_channel="TELEPHONE",
        signed_at=signed_at,
        attested_purchasing_authority="NONE",
    )
    reviewed = review_request(request["id"])
    assert reviewed["status"] == "UNDER_REVIEW"
    # 45 + 30 + 0 base, no TELEPHONE bonus, less 10 for a 14-month-old signature.
    assert reviewed["computed_score"] == 65
    return publication, recipient, document, request


def test_verify_on_purged_evidence_reports_integrity_before_the_score():
    """Destroyed evidence is adjudicated before the arithmetic that would also fail.

    "**Evidentiary referential integrity**: purged source document
    (`ERR_SOURCE_DOCUMENT_PURGED`), then source document belonging to a different
    recipient (`ERR_SOURCE_DOCUMENT_SUBSCRIBER_MISMATCH`), then a predecessor
    statement that is not awaiting restatement (`ERR_RESTATEMENT_NOT_REQUIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/verify_with_purged_doc_and_low_score_rejects_purged_over_threshold
    """
    _, recipient, document, request = reviewed_request_scoring_sixty_five(
        "Evidence Integrity Monthly"
    )

    move_clock("2026-08-20T00:00:00Z")
    purged = validate_success(
        api_client.purge_source_document(
            document["id"], purge_payload(purge_reason="retention elapsed"), MANAGER_HEADERS
        ),
        200,
    )
    assert purged["purge_status"] == "PURGED"
    assert purged["purged_at"].startswith("2026-08-20T00:00:00")

    response = api_client.verify_qualification_request(
        request["id"],
        verify_payload(decision_reason="attempt to verify on purged evidence"),
        SPECIALIST_HEADERS,
    )
    error = validate_error(response, ERR_SOURCE_DOCUMENT_PURGED, 422)
    # The score is 65, below the threshold of 70, yet that rung never spoke.
    assert error["error_id"] != ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD

    stored = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["computed_score"] == 65
    assert read_subscriber(recipient["id"])["qualification_status"] == "PENDING_QUALIFICATION"


def test_score_rung_answers_once_the_evidence_is_intact():
    """The same request with a retained card is refused for the score alone.

    "The threshold is checked first: a request that is both below 70 and short on a
    mandatory dimension reports `ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD` with HTTP
    422, not the mandatory-criterion error."

    Design: Difficulty/priority_pair_validation_conflict/verify_with_purged_doc_and_low_score_rejects_purged_over_threshold
    """
    _, recipient, document, request = reviewed_request_scoring_sixty_five(
        "Score Only Monthly"
    )

    response = api_client.verify_qualification_request(
        request["id"],
        verify_payload(decision_reason="attempt to verify on a short score"),
        SPECIALIST_HEADERS,
    )
    error = validate_error(response, ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD, 422)
    assert error["error_id"] != ERR_SOURCE_DOCUMENT_PURGED

    stored = validate_success(
        api_client.get_qualification_request(request["id"], SPECIALIST_HEADERS), 200
    )
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["decided_at"] is None
    unqualified = read_subscriber(recipient["id"])
    assert unqualified["qualification_status"] == "PENDING_QUALIFICATION"
    assert unqualified["qualification_score"] == 0
    documents, _ = validate_paginated(
        api_client.list_source_documents(recipient["id"], MANAGER_HEADERS)
    )
    assert [doc["purge_status"] for doc in documents if doc["id"] == document["id"]] == [
        "RETAINED"
    ]
