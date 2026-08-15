"""API basics: envelope shape, pagination, filters, defaults, schema and
existence validation (PRD §2.2, §2.3, §2.9, §2.10, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_timestamp_prefix,
    create_appraiser_payload,
    create_client_payload,
    create_engagement_payload,
    create_parties,
    validate_error,
    validate_paginated,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]


def test_envelope_success_and_error_shapes(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format" with meta.api_request_id,
    response_type and data; and "All error API responses (4xx status codes)
    follow this standard envelope format" carrying data.error_id. PRD §2.2
    also states the api_request_id "is a server-generated unique identifier
    for the request that starts with `req_`".

    Design: Corner/endpoints/response_envelope_success_and_error
    """
    res = api.create_client(create_client_payload(), EM)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    client_id = body["data"]["id"]

    err_res = api.get_client(NON_EXISTENT_UUID, EM)
    assert err_res.status_code == 404, err_res.text
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert client_id


def test_list_engagements_pagination_has_more(api):
    """PRD §2.3: "Paginated list responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`." With 3 engagements and limit 2 the first
    page carries 2 items with has_more true and the offset-2 page carries the
    remaining 1 with has_more false.

    Design: Corner/endpoints/list_pagination_has_more
    """
    parties = create_parties()
    for addr in ("1 A St", "2 B St", "3 C St"):
        api.create_engagement(
            create_engagement_payload(
                parties["client"]["id"], parties["author"]["id"],
                parties["reviewer"]["id"], property_address=addr),
            EM)

    page1, meta1 = validate_paginated(
        api.list_engagements(EM, params={"limit": 2}))
    assert len(page1) == 2, f"page 1 should hold 2 engagements, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_engagements(EM, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1, f"page 2 should hold 1 engagement, got {len(page2)}"
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 3


def test_list_engagements_filter_by_client_id(api):
    """PRD §2.3: "Engagements filter by `client_id`, `author_appraiser_id`,
    `reviewer_appraiser_id`, or `status`." Filtering by client A's id returns
    exactly A's engagement.

    Design: Corner/endpoints/filtered_list_reverse_reachability
    """
    parties = create_parties()
    eng_a = validate_success(api.create_engagement(
        create_engagement_payload(
            parties["client"]["id"], parties["author"]["id"],
            parties["reviewer"]["id"], property_address="1 A St"),
        EM), 201)
    other_client = validate_success(api.create_client(
        create_client_payload(name="Beta Trust", client_type="INVESTOR"),
        EM), 201)
    api.create_engagement(
        create_engagement_payload(
            other_client["id"], parties["author"]["id"],
            parties["reviewer"]["id"], property_address="2 B St",
            intended_users=["Beta Trust"]),
        EM)

    data, meta = validate_paginated(api.list_engagements(
        EM, params={"client_id": parties["client"]["id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == eng_a["id"]


def test_client_creation_defaults_and_default_clock(api):
    """PRD §3.1: "Every client begins life with `total_billed_cents` at zero
    and `volume_discount_tier` at `NONE`." PRD §2.4: "Before any
    clock-setting call has been made, the logical clock reads exactly
    2026-08-01T00:00:00Z."

    Design: Corner/entities/client_creation_defaults_and_clock_default
    """
    res = api.create_client(create_client_payload(), EM)
    client = validate_success(res, 201)
    assert client["total_billed_cents"] == 0
    assert client["volume_discount_tier"] == "NONE"
    assert_timestamp_prefix(client["created_at"], "2026-08-01T00:00:00")


def test_client_computed_total_billed_input_ignored(api):
    """PRD §3.1: "A new client is registered with a `name` and a
    `client_type`" and "Every client begins life with `total_billed_cents`
    at zero and `volume_discount_tier` at `NONE`." A client-supplied
    total_billed_cents is not part of registration input; the new client
    still begins at zero.

    Design: Corner/entities/client_computed_field_input_ignored
    """
    payload = create_client_payload()
    payload["total_billed_cents"] = 999999
    client = validate_success(api.create_client(payload, EM), 201)
    assert client["total_billed_cents"] == 0, (
        f"computed total_billed_cents must begin at zero, got {client['total_billed_cents']}")


def test_appraiser_creation_default_license_active(api):
    """PRD §3.1: "Each appraiser's `license_status` begins at `ACTIVE`".

    Design: Corner/entities/appraiser_creation_default_license
    """
    appraiser = validate_success(
        api.create_appraiser(create_appraiser_payload(), EM), 201)
    assert appraiser["license_status"] == "ACTIVE"


def test_get_report_not_found_returns_404(api):
    """PRD §2.9: "Path identifiers and body foreign-key references must
    resolve to existing resources, validated left to right — otherwise
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/report_get_not_found_returns_404
    """
    res = api.get_report(NON_EXISTENT_UUID, EM)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_engagement_create_unknown_client_returns_404(api):
    """PRD §2.10: "body-carried foreign-key references such as `client_id`
    or `author_appraiser_id` are validated the same way" — rejected with
    `ERR_NOT_FOUND` when they do not resolve.

    Design: Corner/entities/engagement_create_unknown_client_returns_404
    """
    parties = create_parties()
    payload = create_engagement_payload(
        NON_EXISTENT_UUID, parties["author"]["id"], parties["reviewer"]["id"])
    res = api.create_engagement(payload, EM)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_engagement_create_missing_building_sf_returns_400(api):
    """PRD §2.9: "Required fields must be present, enum members valid,
    integers positive where required, `period_end` not earlier than
    `period_start`, and `weight_pct` within 0 to 100 — otherwise
    `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.2 lists `building_sf` among the
    assignment's drafting fields, "which must be greater than zero".

    Design: Corner/entities/engagement_create_missing_required_returns_400
    """
    parties = create_parties()
    payload = create_engagement_payload(
        parties["client"]["id"], parties["author"]["id"],
        parties["reviewer"]["id"])
    del payload["building_sf"]
    res = api.create_engagement(payload, EM)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_engagement_create_invalid_property_type_returns_400(api):
    """PRD §3.2 limits `property_type` to "`OFFICE`, `RETAIL`, `INDUSTRIAL`,
    `MULTIFAMILY`, or `SPECIAL_PURPOSE`" and PRD §2.9 rejects invalid enum
    members with `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/entities/engagement_invalid_enum_returns_400
    """
    parties = create_parties()
    payload = create_engagement_payload(
        parties["client"]["id"], parties["author"]["id"],
        parties["reviewer"]["id"], property_type="CASTLE")
    res = api.create_engagement(payload, EM)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request with a missing or malformed header is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    res = api.create_client(create_client_payload(), headers={})
    validate_error(
        res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)
