"""Layered behaviour: optimistic concurrency against listing, filtering and paging."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_STALE_PUBLICATION_VERSION,
    ERR_STALE_SUBSCRIBER_VERSION,
)
from test_helpers.factories import (
    qualification_request_payload,
    statement_payload,
    undeliverable_event_payload,
)
from test_helpers.fixtures import (
    add_complete_rule_set,
    add_subscriber,
    attach_source_document,
    certify_statement,
    move_clock,
    open_statement,
    read_publication,
    read_subscriber,
    register_publication,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    MANAGER_HEADERS,
    SPECIALIST_HEADERS,
)


def test_stale_publication_version_on_statement_create_rejected():
    """A successful create consumes the very version the next create needs.

    "Opening a circulation statement requires `expected_publication_version`,
    carrying the client's last observed `version` of the target `Publication`. If
    that value does not equal the publication's current `version`, the create is
    rejected with `ERR_STALE_PUBLICATION_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_publication_version_on_statement_create_rejected
    """
    publication = register_publication(
        name="Optimistic Concurrency Monthly", industry_code="MANUFACTURING"
    )
    add_subscriber(
        publication["id"],
        company_name="November Foundry",
        subscription_class="CONTROLLED",
        copies=400,
    )
    observed_version = read_publication(publication["id"])["version"]

    first = validate_success(
        api_client.create_statement(
            statement_payload(
                publication["id"],
                observed_version,
                period_start="2026-01-01T00:00:00Z",
                period_end="2026-04-01T00:00:00Z",
                basis="AS_OF_PERIOD_END",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert first["status"] == "DRAFT"

    # The second period is disjoint from the first, so only the version is stale.
    response = api_client.create_statement(
        statement_payload(
            publication["id"],
            observed_version,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            basis="AS_OF_PERIOD_END",
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_STALE_PUBLICATION_VERSION, 412)

    rows, _ = validate_paginated(
        api_client.list_statements(
            MANAGER_HEADERS, params={"publication_id": publication["id"]}
        )
    )
    assert [row["id"] for row in rows] == [first["id"]]

    fresh_version = read_publication(publication["id"])["version"]
    assert fresh_version == observed_version + 1

    second = validate_success(
        api_client.create_statement(
            statement_payload(
                publication["id"],
                fresh_version,
                period_start="2026-04-01T00:00:00Z",
                period_end="2026-07-01T00:00:00Z",
                basis="AS_OF_PERIOD_END",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert second["status"] == "DRAFT"
    assert second["id"] != first["id"]
    assert read_publication(publication["id"])["version"] == observed_version + 2


def test_stale_subscriber_version_on_request_create_rejected():
    """A bounce that moves no status still moves the version, invalidating an attestation.

    "Opening a qualification request requires `expected_subscriber_version`,
    carrying the client's last observed `version` of the target `Subscriber`. If
    that value does not equal the subscriber's current `version`, the create is
    rejected with `ERR_STALE_SUBSCRIBER_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_subscriber_version_on_request_create_rejected
    """
    publication = register_publication(
        name="Attestation Concurrency Monthly", industry_code="LOGISTICS"
    )
    add_complete_rule_set(publication["id"])
    subscriber = add_subscriber(
        publication["id"],
        company_name="November Freight",
        subscription_class="PAID",
        copies=60,
        paid_amount_cents=9900,
    )
    document = attach_source_document(
        subscriber["id"], SPECIALIST_HEADERS, captured_at="2026-07-10T00:00:00Z"
    )
    observed_version = read_subscriber(subscriber["id"])["version"]

    bounced = validate_success(
        api_client.record_undeliverable_event(
            subscriber["id"],
            undeliverable_event_payload(reason_code="MOVED_NO_FORWARDING"),
            MANAGER_HEADERS,
        ),
        200,
    )
    # The event is a signal only, yet the recipient's version still advances by 1.
    assert bounced["undeliverable_count"] == 1
    assert bounced["delivery_status"] == "DELIVERABLE"
    # No request has been opened yet, and a bounce moves neither status dimension.
    assert bounced["qualification_status"] == "UNQUALIFIED"
    assert bounced["version"] == observed_version + 1

    response = api_client.create_qualification_request(
        qualification_request_payload(
            subscriber["id"],
            document["id"],
            observed_version,
            signed_at="2026-07-20T00:00:00Z",
        ),
        SPECIALIST_HEADERS,
    )
    validate_error(response, ERR_STALE_SUBSCRIBER_VERSION, 412)

    rows, _ = validate_paginated(
        api_client.list_qualification_requests(
            SPECIALIST_HEADERS, params={"subscriber_id": subscriber["id"]}
        )
    )
    assert rows == []

    accepted = validate_success(
        api_client.create_qualification_request(
            qualification_request_payload(
                subscriber["id"],
                document["id"],
                bounced["version"],
                signed_at="2026-07-20T00:00:00Z",
            ),
            SPECIALIST_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"

    after = read_subscriber(subscriber["id"])
    assert after["version"] == observed_version + 2
    assert after["qualification_status"] == "PENDING_QUALIFICATION"


def test_statement_list_filter_and_offset_paging_stay_consistent():
    """Filtering runs before paging, so certifying one row shrinks the count itself.

    "Filters supplied as query parameters narrow the result set before pagination
    and before `total_count` is computed." "Unless a specific endpoint description
    states otherwise, list results are ordered by `created_at` ascending." "`limit`
    controls page size: its default is 10, its minimum accepted value is 1, and its
    maximum accepted value is 100."

    Design: Corner/cross_cutting_complexity_layers/statement_list_filter_and_offset_paging_stay_consistent
    """
    publication = register_publication(
        name="Paging Consistency Monthly", industry_code="MANUFACTURING"
    )
    add_subscriber(
        publication["id"],
        company_name="Oscar Presses",
        subscription_class="CONTROLLED",
        copies=300,
    )

    quarters = [
        ("2025-10-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-08-01T00:00:00Z"),
        ("2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", "2026-08-02T00:00:00Z"),
        ("2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z", "2026-08-03T00:00:00Z"),
    ]
    drafts = []
    for period_start, period_end, created_at in quarters:
        move_clock(created_at)
        drafts.append(
            open_statement(
                publication["id"],
                period_start=period_start,
                period_end=period_end,
                basis="AS_OF_PERIOD_END",
            )
        )
    oldest, middle, newest = drafts
    assert [draft["status"] for draft in drafts] == ["DRAFT", "DRAFT", "DRAFT"]

    draft_filter = {"publication_id": publication["id"], "status": "DRAFT"}

    page_one, meta_one = validate_paginated(
        api_client.list_statements(
            AUDITOR_HEADERS, params=dict(draft_filter, limit=2, offset=0)
        )
    )
    assert [row["id"] for row in page_one] == [oldest["id"], middle["id"]]
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api_client.list_statements(
            AUDITOR_HEADERS, params=dict(draft_filter, limit=2, offset=2)
        )
    )
    assert [row["id"] for row in page_two] == [newest["id"]]
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    filed = certify_statement(oldest["id"])
    assert filed["status"] == "FILED"

    after, meta_after = validate_paginated(
        api_client.list_statements(
            AUDITOR_HEADERS, params=dict(draft_filter, limit=2, offset=0)
        )
    )
    # The filter shrinks the matching set rather than leaving a hole in page one.
    assert [row["id"] for row in after] == [middle["id"], newest["id"]]
    assert meta_after["total_count"] == 2
    assert meta_after["has_more"] is False

    filed_rows, filed_meta = validate_paginated(
        api_client.list_statements(
            AUDITOR_HEADERS,
            params={"publication_id": publication["id"], "status": "FILED"},
        )
    )
    assert [row["id"] for row in filed_rows] == [oldest["id"]]
    assert filed_meta["total_count"] == 1

    unpaged, unpaged_meta = validate_paginated(
        api_client.list_statements(
            AUDITOR_HEADERS, params={"publication_id": publication["id"]}
        )
    )
    assert [row["id"] for row in unpaged] == [draft["id"] for draft in drafts]
    assert unpaged_meta["limit"] == 10
    assert unpaged_meta["offset"] == 0
    assert unpaged_meta["total_count"] == 3
    assert unpaged_meta["has_more"] is False
