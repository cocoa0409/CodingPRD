"""A write's fate decided by a neighbour's state: the parent publication, and a sibling card."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_PUBLICATION_FROZEN,
    ERR_RESTATEMENT_NOT_REQUIRED,
    ERR_SOURCE_DOCUMENT_PURGED,
)
from test_helpers.factories import (
    certify_payload,
    purge_payload,
    qualification_request_payload,
    statement_payload,
)
from test_helpers.fixtures import (
    add_complete_rule_set,
    add_subscriber,
    attach_source_document,
    certify_statement,
    issue_report,
    move_clock,
    open_engagement,
    open_statement,
    qualify_subscriber,
    read_contract,
    read_publication,
    read_statement,
    read_subscriber,
    record_sample,
    register_contract,
    register_publication,
)
from test_helpers.test_users import EXECUTIVE_HEADERS, MANAGER_HEADERS, SPECIALIST_HEADERS

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
AUDIT_CLOCK = "2026-10-01T00:00:00Z"
LATER_CLOCK = "2026-11-01T00:00:00Z"


def publication_with_one_paid_recipient(name):
    """A configured publication whose only recipient holds 1,200 qualified PAID copies."""
    publication = register_publication(
        name=name, industry_code="MANUFACTURING", materiality_pct=2.00
    )
    add_complete_rule_set(publication["id"])
    recipient = qualify_subscriber(
        publication["id"],
        signed_at="2026-07-01T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name="Oscar Paid Works",
        subscription_class="PAID",
        copies=1200,
        paid_amount_cents=96000,
    )
    return publication, recipient


def test_freeze_blocks_an_unrelated_certification_but_admits_the_restatement():
    """The same FROZEN posture that refuses one draft admits the one naming the condemned statement.

    "Certification of that successor is permitted despite `FROZEN` precisely because
    it names the offending statement, and it unwinds the freeze in three hops."

    Design: Difficulty/cross_entity_state_dependency/certify_blocked_by_frozen_publication_then_restatement_exemption
    """
    publication, recipient = publication_with_one_paid_recipient("Escape Hatch Monthly")
    contract = register_contract(
        publication["id"],
        advertiser_name="Frozen Guarantee Media",
        insertion_count=6,
        gross_rate_cents_per_insertion=500000,
        guaranteed_rate_base=1000,
    )
    assert contract["guarantee_status"] == "ACTIVE"

    move_clock(AUDIT_CLOCK)
    condemned = certify_statement(
        open_statement(
            publication["id"],
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            basis="AS_OF_PERIOD_END",
        )["id"]
    )
    assert condemned["declared_total_copies"] == 1200

    engagement = open_engagement(
        condemned["id"],
        auditor_org="Verified Audit Bureau",
        fieldwork_start="2026-10-05T00:00:00Z",
        fieldwork_end="2026-10-09T00:00:00Z",
        sample_size=1,
    )
    record_sample(
        engagement["id"],
        recipient["subscriber"]["id"],
        evidence_ok=True,
        verified_copies=900,
    )
    issue_report(engagement["id"], report_note="300 copies unsupported")
    assert read_statement(condemned["id"])["status"] == "RESTATEMENT_REQUIRED"
    frozen = read_publication(publication["id"])
    assert frozen["audit_posture"] == "FROZEN"
    assert read_contract(contract["id"])["guarantee_status"] == (
        "SUSPENDED_PENDING_RESTATEMENT"
    )

    move_clock(LATER_CLOCK)
    unrelated = open_statement(
        publication["id"],
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    # Nothing about this statement is wrong; its parent publication is frozen.
    validate_error(
        api_client.certify_statement(
            unrelated["id"],
            certify_payload(certification_note="unrelated period, frozen publication"),
            EXECUTIVE_HEADERS,
        ),
        ERR_PUBLICATION_FROZEN,
        409,
    )
    assert read_statement(unrelated["id"])["status"] == "DRAFT"

    restatement = open_statement(
        publication["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AUDIT_VERIFIED",
        restates_statement_id=condemned["id"],
    )
    assert restatement["statement_type"] == "AUDITED"
    assert restatement["restates_statement_id"] == condemned["id"]
    # The card is RETAINED and its retention runs to 2029-07-15, after period_end.
    assert restatement["total_qualified_copies"] == 1200

    filed = certify_statement(restatement["id"])
    assert filed["status"] == "FILED"

    # Hop 1: the predecessor is retired by the system, with no separate call.
    assert read_statement(condemned["id"])["status"] == "SUPERSEDED"
    # Hop 2: nothing awaits restatement any more, so the ladder falls through to OPEN.
    assert read_publication(publication["id"])["audit_posture"] == "OPEN"
    # Hop 3: the suspended guarantee is enforceable again.
    assert read_contract(contract["id"])["guarantee_status"] == "ACTIVE"

    # The posture moved again, which marks the still-open draft stale.
    stale = read_statement(unrelated["id"])
    assert stale["status"] == "DRAFT"
    assert stale["breakdown_stale"] is True


def test_certification_flows_freely_while_the_parent_is_open_and_needs_a_condemned_predecessor():
    """An OPEN parent blocks nothing, and the exemption cannot be claimed against a FILED statement.

    "`restates_statement_id` is null on an original statement and is set only when
    this statement is the replacement for a predecessor the audit condemned; when
    supplied, it must name a statement of the *same* publication whose `status` is
    `RESTATEMENT_REQUIRED`, and anything else — a statement of another publication, or
    one in any other status — is rejected with `ERR_RESTATEMENT_NOT_REQUIRED` and HTTP
    409."

    Design: Difficulty/cross_entity_state_dependency/certify_blocked_by_frozen_publication_then_restatement_exemption
    """
    publication, _ = publication_with_one_paid_recipient("Open Parent Monthly")

    move_clock(AUDIT_CLOCK)
    filed = certify_statement(
        open_statement(
            publication["id"],
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            basis="AS_OF_PERIOD_END",
        )["id"]
    )
    assert filed["status"] == "FILED"
    assert read_publication(publication["id"])["audit_posture"] == "OPEN"

    move_clock(LATER_CLOCK)
    adjacent = open_statement(
        publication["id"],
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
        basis="AS_OF_PERIOD_END",
    )
    # The parent is OPEN, so the same call that was refused under a freeze succeeds.
    assert certify_statement(adjacent["id"])["status"] == "FILED"

    publication_now = read_publication(publication["id"])
    validate_error(
        api_client.create_statement(
            statement_payload(
                publication["id"],
                publication_now["version"],
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                basis="AUDIT_VERIFIED",
                restates_statement_id=filed["id"],
            ),
            MANAGER_HEADERS,
        ),
        ERR_RESTATEMENT_NOT_REQUIRED,
        409,
    )
    # The predecessor was never condemned, so nothing was retired.
    assert read_statement(filed["id"])["status"] == "FILED"


def purged_card_publication(name):
    """A recipient at rest whose only source document has been lawfully destroyed."""
    publication = register_publication(
        name=name, industry_code="MANUFACTURING", source_doc_retention_months=1
    )
    add_complete_rule_set(publication["id"])
    recipient = add_subscriber(
        publication["id"],
        company_name="Papa Evidence Works",
        subscription_class="CONTROLLED",
        copies=60,
    )
    assert recipient["qualification_status"] == "UNQUALIFIED"
    document = attach_source_document(
        recipient["id"], MANAGER_HEADERS, captured_at="2026-07-15T00:00:00Z"
    )

    move_clock("2026-08-20T00:00:00Z")
    purged = validate_success(
        api_client.purge_source_document(
            document["id"], purge_payload(), MANAGER_HEADERS
        ),
        200,
    )
    assert purged["purge_status"] == "PURGED"
    return publication, recipient, document


def test_request_citing_a_purged_card_is_refused_however_good_the_attestation():
    """The sibling evidence row's state decides the create, not the request's own merits.

    "The cited evidence must be the recipient's own and must still exist. If the named
    source document's `subscriber_id` is not the `subscriber_id` on the request, the
    create fails with `ERR_SOURCE_DOCUMENT_SUBSCRIBER_MISMATCH` and HTTP 422; if the
    document's `purge_status` is `PURGED`, it fails with `ERR_SOURCE_DOCUMENT_PURGED`,
    also HTTP 422."

    Design: Difficulty/cross_entity_state_dependency/create_request_citing_purged_source_document_rejected
    """
    _, recipient, document = purged_card_publication("Destroyed Evidence Monthly")

    # Every attested dimension is on its rule's allowed list, so this would score 100.
    response = api_client.create_qualification_request(
        qualification_request_payload(
            recipient["id"],
            document["id"],
            recipient["version"],
            request_channel="DIRECT_MAIL",
            signed_at="2026-08-15T00:00:00Z",
        ),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_SOURCE_DOCUMENT_PURGED, 422)

    requests, meta = validate_paginated(
        api_client.list_qualification_requests(
            SPECIALIST_HEADERS, params={"subscriber_id": recipient["id"]}
        )
    )
    assert requests == []
    assert meta["total_count"] == 0

    at_rest = read_subscriber(recipient["id"])
    assert at_rest["qualification_status"] == "UNQUALIFIED"
    # A rejected write consumes nothing, least of all the concurrency counter.
    assert at_rest["version"] == recipient["version"]


def test_a_fresh_card_revives_the_same_recipient_at_the_same_expected_version():
    """Because the refusal changed nothing, the caller's stale-looking version still holds.

    "In every case the new request is created with `status` `SUBMITTED`,
    `info_request_count` 0, `computed_score` 0, and the recipient's `version` advances
    by 1."

    Design: Difficulty/cross_entity_state_dependency/create_request_citing_purged_source_document_rejected
    """
    _, recipient, document = purged_card_publication("Fresh Card Monthly")

    validate_error(
        api_client.create_qualification_request(
            qualification_request_payload(
                recipient["id"],
                document["id"],
                recipient["version"],
                signed_at="2026-08-15T00:00:00Z",
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_SOURCE_DOCUMENT_PURGED,
        422,
    )

    replacement = attach_source_document(
        recipient["id"], MANAGER_HEADERS, captured_at="2026-08-18T00:00:00Z"
    )
    assert replacement["purge_status"] == "RETAINED"

    # The very same expected_subscriber_version is still current.
    opened = validate_success(
        api_client.create_qualification_request(
            qualification_request_payload(
                recipient["id"],
                replacement["id"],
                recipient["version"],
                signed_at="2026-08-15T00:00:00Z",
            ),
            SPECIALIST_HEADERS,
        ),
        201,
    )
    assert opened["status"] == "SUBMITTED"
    assert opened["source_document_id"] == replacement["id"]
    assert opened["computed_score"] == 0
    assert opened["info_request_count"] == 0

    pending = read_subscriber(recipient["id"])
    assert pending["qualification_status"] == "PENDING_QUALIFICATION"
    assert pending["version"] == recipient["version"] + 1

    # The tombstone survives the purge; it was never deleted.
    documents, _ = validate_paginated(
        api_client.list_source_documents(recipient["id"], MANAGER_HEADERS)
    )
    assert sorted(doc["purge_status"] for doc in documents) == ["PURGED", "RETAINED"]
