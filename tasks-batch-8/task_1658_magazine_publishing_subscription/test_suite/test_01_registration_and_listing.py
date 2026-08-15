"""Registration, defaults, envelope shape, and fleet-wide input validation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ANONYMOUS_HEADERS,
    assert_publication,
    assert_subscriber,
    create_publication,
    create_subscriber,
    create_publication_payload,
    set_clock,
    PD,
    CM,
)

PD_H = TEST_USERS["publishing_director_headers"]


class TestPublicationRegistration:
    def test_publication_creation_applies_defaults(self, api):
        """Creating a publication without deferred_revenue_method applies the
        PRO_RATA_ISSUE default, derives issues_per_year from frequency, and
        starts ACTIVE.

        PRD §3.1: "The publisher may optionally declare the publication's `deferred_revenue_method` — `PRO_RATA_ISSUE` or `STRAIGHT_LINE_MONTH` — which defaults to `PRO_RATA_ISSUE` when omitted and governs how subscription cash becomes earned revenue (§2.10)."
        PRD §3.1: "From the declared frequency the system derives `issues_per_year`: fifty-two for a weekly, twelve for a monthly, four for a quarterly."
        PRD §3.1: "A new publication begins life `ACTIVE`."

        Design: Corner/entities/publication_creation_applies_defaults
        """
        set_clock()
        resp = api.create_publication(
            {
                "title": "DefaultTest",
                "issn": "12345678",
                "frequency": "MONTHLY",
                "circulation_model": "PAID",
                "base_cover_price_cents": 599,
            },
            PD_H,
        )
        data = validate_success(resp, 201)
        assert_publication(data)
        assert data["deferred_revenue_method"] == "PRO_RATA_ISSUE", (
            f"default deferred_revenue_method must be PRO_RATA_ISSUE, got {data['deferred_revenue_method']}"
        )
        assert data["status"] == "ACTIVE", f"new publication must be ACTIVE, got {data['status']}"
        assert data["issues_per_year"] == 12, (
            f"MONTHLY publication must derive issues_per_year 12, got {data['issues_per_year']}"
        )

    def test_publication_missing_issn_returns_invalid_request(self, api):
        """Omitting the required issn field is rejected with ERR_INVALID_REQUEST.

        PRD §2.7: "Seventeenth and last, the presence and well-formedness of required input fields — an `issn` of exactly eight characters, a `state_code` of exactly two characters, a `quantity` greater than zero — whose violations surface as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `PublishingDirector` brings a title into the system by creating a **Publication** with its `title`, its eight-character `issn`, a `frequency` of `WEEKLY`, `MONTHLY`, or `QUARTERLY`, a `circulation_model` of `PAID`, `CONTROLLED`, or `MIXED`, and the `base_cover_price_cents` that anchors single-copy pricing."

        Design: Corner/entities/publication_missing_required_field_returns_invalid_request
        """
        set_clock()
        resp = api.create_publication(
            {
                "title": "NoISSN",
                "frequency": "MONTHLY",
                "circulation_model": "PAID",
                "base_cover_price_cents": 599,
            },
            PD_H,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_get_publication_not_found_returns_404(self, api):
        """GET on a non-existent publication id yields ERR_PUBLICATION_NOT_FOUND.

        PRD §2.6: "When an endpoint path contains multiple resource identifiers, the system validates them sequentially from left to right, and the request is rejected immediately with the 404 error belonging to the first identifier that does not resolve: a missing publication yields `ERR_PUBLICATION_NOT_FOUND`;"

        Design: Corner/entities/publication_get_not_found_returns_404
        """
        set_clock()
        resp = api.get_publication(NON_EXISTENT_UUID, PD_H)
        validate_error(resp, ApiErrorId.ERR_PUBLICATION_NOT_FOUND, 404)

    def test_list_publications_pagination_envelope(self, api):
        """List responses carry the array envelope with pagination meta fields.

        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0 and must never be negative."

        Design: Corner/endpoints/list_publications_pagination_envelope
        """
        set_clock()
        create_publication(title="P1")
        create_publication(title="P2", frequency="WEEKLY")
        create_publication(title="P3", frequency="QUARTERLY", circulation_model="CONTROLLED")

        resp = api.list_publications(PD_H, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array", (
            f"list endpoint must answer response_type 'array', got {body['response_type']}"
        )
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
            "meta.api_request_id must be present and start with req_"
        )
        assert isinstance(meta.get("api_request_timestamp"), str), "meta.api_request_timestamp must be present"
        assert len(data) == 2, f"limit=2 must return exactly 2 records, got {len(data)}"
        assert meta["limit"] == 2 and meta["offset"] == 0
        assert meta["total_count"] == 3, f"total_count must be 3, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more must be true for offset=0, limit=2, total=3"


class TestRequestValidation:
    def test_missing_auth_headers_rejected(self, api):
        """A request with neither X-User-ID nor X-User-Role is rejected.

        PRD §2.1: "A request in which either header is missing or invalid is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_publications(ANONYMOUS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_pagination_limit_zero_rejected(self, api):
        """limit=0 falls outside the permitted 1..100 range.

        PRD §2.3: "A `limit` outside the range of 1 to 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400)."

        Design: Corner/validations/invalid_pagination_limit_zero_returns_400
        """
        set_clock()
        resp = api.list_publications(PD_H, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS, 400)


class TestSubscriberRegistration:
    def test_subscriber_creation_defaults_country_code_us(self, api):
        """A subscriber registered without country_code defaults to US.

        PRD §3.2: "The `country_code` defaults to `US` when omitted; a non-US address is treated as foreign for mailing-batch splitting and for back-issue shipping."

        Design: Corner/entities/subscriber_creation_defaults_country_code_us
        """
        set_clock()
        subscriber = create_subscriber()
        assert_subscriber(subscriber)
        assert subscriber["country_code"] == "US", (
            f"omitted country_code must default to US, got {subscriber['country_code']}"
        )

    def test_subscriber_initial_circulation_class_non_qualified(self, api):
        """A freshly registered subscriber stands at NON_QUALIFIED.

        PRD §3.2: "At registration the subscriber is assumed reachable — `is_deliverable` starts true — and stands outside any circulation qualification, with `circulation_class` equal to `NON_QUALIFIED`."

        Design: Corner/entities/subscriber_computed_circulation_class_initial_non_qualified
        """
        set_clock()
        subscriber = create_subscriber()
        assert_subscriber(subscriber)
        assert subscriber["circulation_class"] == "NON_QUALIFIED", (
            f"new subscriber must be NON_QUALIFIED, got {subscriber['circulation_class']}"
        )
        assert subscriber["is_deliverable"] is True, "new subscriber must start deliverable"
