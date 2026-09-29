"""Error identity: entity-scoped not-found codes, provenance gates, authentication."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_DIGITAL_SOURCE_UNCERTIFIED,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_FINDING_NOT_FOUND,
    ERR_MAKEGOOD_NOT_FOUND,
    ERR_QUALIFICATION_REQUEST_NOT_FOUND,
    ERR_SNAPSHOT_NOT_FOUND,
    ERR_SOURCE_DOCUMENT_NOT_FOUND,
    ERR_STATEMENT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.factories import (
    digital_snapshot_payload,
    snapshot_decision_payload,
)
from test_helpers.fixtures import register_publication
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    EXECUTIVE_HEADERS,
    MANAGER_HEADERS,
    SPECIALIST_HEADERS,
)

JSON_ONLY_HEADERS = {"Content-Type": "application/json"}


def test_unknown_ids_across_resources_return_scoped_not_found_errors():
    """Each resource family answers with its own 404 code, never a shared generic one.

    "a `source_document_id` yields `ERR_SOURCE_DOCUMENT_NOT_FOUND`; a
    `qualification_request_id` yields `ERR_QUALIFICATION_REQUEST_NOT_FOUND`; a
    `statement_id` — including a `restates_statement_id` that names nothing —
    yields `ERR_STATEMENT_NOT_FOUND`; an `engagement_id` yields
    `ERR_ENGAGEMENT_NOT_FOUND`; a `finding_id` yields `ERR_FINDING_NOT_FOUND`; a
    `contract_id` yields `ERR_CONTRACT_NOT_FOUND`; a `make_good_id` yields
    `ERR_MAKEGOOD_NOT_FOUND`; and a `snapshot_id` yields
    `ERR_SNAPSHOT_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_across_resources_return_scoped_not_found_errors
    """
    validate_error(
        api_client.purge_source_document(
            "11111111-1111-4111-8111-111111111111",
            {"purge_reason": "no such document"},
            MANAGER_HEADERS,
        ),
        ERR_SOURCE_DOCUMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.review_qualification_request(
            "22222222-2222-4222-8222-222222222222",
            {"review_note": "no such request"},
            SPECIALIST_HEADERS,
        ),
        ERR_QUALIFICATION_REQUEST_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.certify_statement(
            "33333333-3333-4333-8333-333333333333",
            {"certification_note": "no such statement"},
            EXECUTIVE_HEADERS,
        ),
        ERR_STATEMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.issue_report(
            "44444444-4444-4444-8444-444444444444",
            {"report_note": "no such engagement"},
            AUDITOR_HEADERS,
        ),
        ERR_ENGAGEMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.respond_to_finding(
            "55555555-5555-4555-8555-555555555555",
            {"response_note": "no such finding"},
            MANAGER_HEADERS,
        ),
        ERR_FINDING_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_advertiser_contract(
            "66666666-6666-4666-8666-666666666666", MANAGER_HEADERS
        ),
        ERR_CONTRACT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_make_good(
            "77777777-7777-4777-8777-777777777777", MANAGER_HEADERS
        ),
        ERR_MAKEGOOD_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.validate_digital_snapshot(
            "88888888-8888-4888-8888-888888888888",
            snapshot_decision_payload("VALIDATE"),
            AUDITOR_HEADERS,
        ),
        ERR_SNAPSHOT_NOT_FOUND,
        404,
    )


def test_validate_uncertified_digital_snapshot_rejected():
    """Uncertified analytics may be recorded but never validated into audited circulation.

    "a `VALIDATE` decision is permitted solely when `source` is
    `THIRD_PARTY_CERTIFIED`, and attempting to validate an `INTERNAL_ANALYTICS`
    snapshot is rejected with `ERR_DIGITAL_SOURCE_UNCERTIFIED` and HTTP 422."

    Design: Corner/errors/validate_uncertified_digital_snapshot_rejected
    """
    publication = register_publication(
        name="Audience Certification Monthly", industry_code="MANUFACTURING"
    )
    window = dict(
        window_start="2026-06-01T00:00:00Z",
        window_end="2026-07-01T00:00:00Z",
        website_unique_visitors=48000,
        newsletter_sends=40000,
        newsletter_unique_opens=12500,
        overlap_pct=15.00,
    )

    internal = validate_success(
        api_client.create_digital_snapshot(
            publication["id"],
            digital_snapshot_payload(source="INTERNAL_ANALYTICS", **window),
            MANAGER_HEADERS,
        ),
        201,
    )
    certified = validate_success(
        api_client.create_digital_snapshot(
            publication["id"],
            digital_snapshot_payload(source="THIRD_PARTY_CERTIFIED", **window),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert internal["source"] == "INTERNAL_ANALYTICS"
    assert internal["status"] == "RECORDED"
    assert certified["status"] == "RECORDED"

    response = api_client.validate_digital_snapshot(
        internal["id"], snapshot_decision_payload("VALIDATE"), AUDITOR_HEADERS
    )
    validate_error(response, ERR_DIGITAL_SOURCE_UNCERTIFIED, 422)

    listing = api_client.list_digital_snapshots(
        publication["id"], MANAGER_HEADERS, params={"status": "RECORDED"}
    )
    rows = listing.json()["data"]
    still_recorded = [row for row in rows if row["id"] == internal["id"]][0]
    assert still_recorded["status"] == "RECORDED"
    assert still_recorded["validated_by_user_id"] is None

    response = api_client.validate_digital_snapshot(
        certified["id"], snapshot_decision_payload("VALIDATE"), AUDITOR_HEADERS
    )
    validated = validate_success(response, 200)
    assert validated["status"] == "VALIDATED"
    # 12,500 opens discounted by the 15.00 percent overlap is 10,625, plus 48,000.
    assert validated["combined_reach_deduplicated"] == 58625


def test_request_without_identity_headers_unauthenticated():
    """Authentication precedes the existence ladder, so a headerless call is 401 not 404.

    "Authentication. Both headers present and `X-User-Role` one of the five
    declared roles — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint."

    Design: Corner/errors/request_without_identity_headers_unauthenticated
    """
    response = api_client.raw_post(
        "/circulation/statements/99999999-9999-4999-8999-999999999999/certify",
        {"certification_note": "anonymous certification attempt"},
        JSON_ONLY_HEADERS,
    )
    validate_error(response, ERR_UNAUTHENTICATED, 401)

    publication = register_publication(name="Anonymous Read Journal")
    response = api_client.raw_get(
        f"/circulation/publications/{publication['id']}", JSON_ONLY_HEADERS
    )
    validate_error(response, ERR_UNAUTHENTICATED, 401)
