"""API baseline: response envelopes, pagination, reverse-lookup filters,
existence-tier 404s, auth-header presence, and uniqueness constraints."""
from test_helpers import (
    validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_operator, create_truck, create_lease, create_active_lease,
    create_settlement, set_clock,
    create_owner_operator_payload, create_truck_payload, create_lease_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
COORD = TEST_USERS["maintenance_coordinator_headers"]


# ─── Queue B: corner/endpoints ───────────────────────

def test_list_pagination_envelope(api):
    """PRD section 2.3: "The `limit` parameter caps the number of returned items:
    it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100.
    The `offset` parameter skips a number of items from the front of the result
    set and defaults to 0." PRD section 2.3: "Paginated list responses carry
    `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/endpoints/list_pagination_envelope
    """
    operator = create_operator()
    truck1 = create_truck()
    truck2 = create_truck()
    create_lease(operator["id"], truck1["id"])
    create_lease(operator["id"], truck2["id"])

    res1 = api.list_lease_agreements(ADMIN, params={"limit": 1, "offset": 0})
    page1, meta1 = validate_paginated(res1)
    assert res1.json()["response_type"] == "array"
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1 and meta1["offset"] == 0
    assert isinstance(res1.json()["meta"]["api_request_id"], str)
    assert isinstance(res1.json()["meta"]["api_request_timestamp"], str)

    res2 = api.list_lease_agreements(ADMIN, params={"limit": 1, "offset": 1})
    page2, meta2 = validate_paginated(res2)
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert meta2["offset"] == 1
    assert page1[0]["id"] != page2[0]["id"]


def test_error_envelope_shape(api):
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." PRD section 2.2: "The
    `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/endpoints/error_envelope_shape
    """
    res = api.get_truck(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_TRUCK_NOT_FOUND.value)

    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"].startswith("req_")


def test_filtered_list_reverse_fk_lookup(api):
    """PRD section 2.9: "Reverse lookups are served by query-parameter filters on
    the list endpoints — for example, listing settlements with a `lease_id`
    filter returns that lease's statements, and the same pattern serves escrow
    accounts". PRD section 2.9: "The escrow relationship to its lease is
    one-to-one, so the escrow list filtered by `lease_id` returns an array of at
    most one element."

    Design: Corner/endpoints/filtered_list_reverse_fk_lookup
    """
    scenario_a = create_active_lease()
    scenario_b = create_active_lease()
    lease_a = scenario_a["lease"]["id"]
    lease_b = scenario_b["lease"]["id"]
    set_clock("2026-08-12T00:00:00Z")
    st_a = create_settlement(lease_a, "2026-08-03")

    data_a, meta_a = validate_paginated(
        api.list_settlements(CLERK, params={"lease_id": lease_a}))
    assert len(data_a) == 1
    assert data_a[0]["id"] == st_a["id"]
    assert data_a[0]["lease_id"] == lease_a

    data_b, meta_b = validate_paginated(
        api.list_settlements(CLERK, params={"lease_id": lease_b}))
    assert len(data_b) == 0
    assert meta_b["total_count"] == 0
    assert meta_b["has_more"] is False

    escrow_b, meta_esc = validate_paginated(
        api.list_escrow_accounts(CLERK, params={"lease_id": lease_b}))
    assert len(escrow_b) == 1, "1:1 escrow account surfaced as a 0..1 array"
    assert escrow_b[0]["lease_id"] == lease_b


# ─── Queue B: corner/errors + corner/entities (not-found) ──

def test_not_found_family_remaining_resources_returns_404(api):
    """PRD section 2.8: "Third, existence of path identifiers and body
    foreign-key references, validated left-to-right — path first, then body —
    yielding the appropriate `ERR_{RESOURCE}_NOT_FOUND`."

    Design: Corner/errors/not_found_family_remaining_resources_returns_404
    """
    cases = [
        (api.get_owner_operator(NON_EXISTENT_UUID, ADMIN), "ERR_OPERATOR_NOT_FOUND"),
        (api.get_escrow_account(NON_EXISTENT_UUID, CLERK), "ERR_ESCROW_NOT_FOUND"),
        (api.get_lane_assignment(NON_EXISTENT_UUID, ADMIN), "ERR_LANE_NOT_FOUND"),
        (api.get_service_bay(NON_EXISTENT_UUID, COORD), "ERR_BAY_NOT_FOUND"),
        (api.get_work_order(NON_EXISTENT_UUID, COORD), "ERR_WORK_ORDER_NOT_FOUND"),
        (api.get_compliance_document(NON_EXISTENT_UUID, OFFICER), "ERR_DOC_NOT_FOUND"),
    ]
    for res, expected in cases:
        validate_error(res, expected)


def test_truck_get_not_found_returns_404(api):
    """PRD section 2.8: "Third, existence of path identifiers and body
    foreign-key references, validated left-to-right — path first, then body —
    yielding the appropriate `ERR_{RESOURCE}_NOT_FOUND`." PRD section 3.3: "the
    referenced truck must exist (`ERR_TRUCK_NOT_FOUND`)".

    Design: Corner/entities/truck_get_not_found_returns_404
    """
    res = api.get_truck(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_TRUCK_NOT_FOUND.value)


def test_generic_get_not_found_sample_returns_404(api):
    """PRD section 2.8: "Third, existence of path identifiers and body
    foreign-key references, validated left-to-right — path first, then body —
    yielding the appropriate `ERR_{RESOURCE}_NOT_FOUND`."

    Design: Corner/entities/generic_get_not_found_sample_returns_404
    """
    res1 = api.get_buyout_quote(NON_EXISTENT_UUID, ADMIN)
    validate_error(res1, ApiErrorId.ERR_QUOTE_NOT_FOUND.value)
    res2 = api.get_settlement(NON_EXISTENT_UUID, CLERK)
    validate_error(res2, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value)


def test_lease_create_nonexistent_truck_and_operator_returns_404(api):
    """PRD section 3.3: "The referenced operator must exist
    (`ERR_OPERATOR_NOT_FOUND`) and the referenced truck must exist
    (`ERR_TRUCK_NOT_FOUND`)". PRD section 2.8: "Third, existence of path
    identifiers and body foreign-key references, validated left-to-right — path
    first, then body — yielding the appropriate `ERR_{RESOURCE}_NOT_FOUND`."

    Design: Corner/validations/lease_create_nonexistent_truck_and_operator_returns_404
    """
    operator = create_operator()

    res1 = api.create_lease_agreement(
        create_lease_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), ADMIN)
    validate_error(res1, ApiErrorId.ERR_OPERATOR_NOT_FOUND.value)

    res2 = api.create_lease_agreement(
        create_lease_payload(operator["id"], NON_EXISTENT_UUID), ADMIN)
    validate_error(res2, ApiErrorId.ERR_TRUCK_NOT_FOUND.value)


# ─── Queue B: corner/validations (auth + uniqueness) ──

def test_missing_auth_header_returns_400(api):
    """PRD section 2.1: "Every request carries two mandatory headers: `X-User-ID`
    identifies the acting user and `X-User-Role` names their operational role. A
    request missing either header, or presenting a role string outside the
    declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    operator = create_operator()
    res = api.get_owner_operator(operator["id"], headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_duplicate_unique_values_return_409(api):
    """PRD section 3.1: "The CDL number is unique across operators; a collision
    is rejected with `ERR_DUPLICATE_VALUE` (HTTP 409)." PRD section 3.1: "A truck
    enters the system with its `vin` (unique; collisions also yield
    `ERR_DUPLICATE_VALUE`)".

    Design: Corner/validations/duplicate_unique_values_return_409
    """
    first = create_operator()
    truck = create_truck()

    res1 = api.create_owner_operator(
        create_owner_operator_payload(legal_name="Other Owner",
                                      cdl_number=first["cdl_number"]), ADMIN)
    validate_error(res1, ApiErrorId.ERR_DUPLICATE_VALUE.value)

    res2 = api.create_truck(create_truck_payload(vin=truck["vin"]), ADMIN)
    validate_error(res2, ApiErrorId.ERR_DUPLICATE_VALUE.value)
