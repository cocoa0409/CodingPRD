"""Platform-wide rules: auth context, authorization, envelope, pagination,
uniqueness, not-found resolution, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_collection,
    assert_storage_zone,
    create_accession,
    create_collection,
    create_zone,
    get_collection,
    get_zone,
    make_board_officer_headers,
    make_researcher_headers,
    post_reading,
    register_researcher,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

REG = {"X-User-ID": "reg-1", "X-User-Role": "Registrar", "Content-Type": "application/json"}
ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}
RRS = {"X-User-ID": "rrs-1", "X-User-Role": "ReadingRoomStaff", "Content-Type": "application/json"}
SYSADMIN = {"X-User-ID": "sys-1", "X-User-Role": "SystemAdmin", "Content-Type": "application/json"}


class TestAuthContext:

    def test_missing_auth_headers_rejected(self):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the
        acting user and `X-User-Role` to specify their operational capacity. A
        request in which either header is missing or empty is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api_client.create_storage_zone(
            {"zone_code": "Z1", "name": "Vault A"}, {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Only one of the two headers present is equally invalid.
        resp2 = api_client.create_storage_zone(
            {"zone_code": "Z1", "name": "Vault A"},
            {"X-User-ID": "reg-1", "Content-Type": "application/json"})
        validate_error(resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestAuthorization:

    def test_researcher_cannot_create_collection(self):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not in the endpoint's authorized list is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/collections` | Create a collection, optionally under
        a parent | Registrar |"

        Design: Corner/rbac/researcher_cannot_create_collection
        """
        researcher = register_researcher()
        resp = api_client.create_collection(
            {"title": "X", "collection_code": "X1",
             "storage_zone_id": "11111111-1111-4111-8111-111111111111"},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403

    def test_board_officer_cannot_manage_accessions(self):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not in the endpoint's authorized list is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/accessions` | Register a new accession (donor lot
        intake) | Registrar |"

        Design: Corner/rbac/board_officer_cannot_manage_accessions
        """
        resp = api_client.create_accession(
            {"donor_name": "X", "donor_contact": "x@example.org",
             "accession_date": "2026-07-15", "lot_appraised_value_cents": 100},
            make_board_officer_headers("board_1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403


class TestNotFoundResolution:

    def test_get_nonexistent_resource_returns_not_found(self):
        """PRD §2.11: "Requests that target nested resources validate path
        identifiers sequentially, left to right, before any body-referenced
        identifier is examined. The first path identifier that does not resolve
        to an existing resource rejects the request with `ERR_NOT_FOUND`, and
        the error message names the resource type that failed to resolve."

        Design: Corner/entities/get_nonexistent_resource_returns_not_found
        """
        accession = create_accession()

        resp = api_client.get_collection(NON_EXISTENT_UUID, REG)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404

        resp2 = api_client.list_deeds(NON_EXISTENT_UUID, REG)
        validate_error(resp2, ApiErrorId.ERR_NOT_FOUND)

        data, meta = validate_paginated(api_client.list_deeds(accession["id"], REG))
        assert data == [], "an existing accession with no deeds lists empty"
        assert meta["total_count"] == 0


class TestUniqueness:

    def test_uniqueness_constraints_enforced(self):
        """PRD §3.2: "a unique `collection_code` (a duplicate is rejected with
        `ERR_COLLECTION_CODE_EXISTS`)"
        PRD §2.6: "Each storage zone is defined by a unique `zone_code` (a
        duplicate code is rejected with `ERR_ZONE_CODE_EXISTS`)"
        PRD §3.6: "a unique `email` (a duplicate is `ERR_DUPLICATE_EMAIL`)"

        Design: Corner/validations/uniqueness_constraints_enforced
        """
        zone = create_zone(zone_code="Z1")
        create_collection(zone["id"], collection_code="C1")
        register_researcher(email="r1@example.org")

        resp1 = api_client.create_collection(
            {"title": "Dup", "collection_code": "C1",
             "storage_zone_id": zone["id"]}, REG)
        validate_error(resp1, ApiErrorId.ERR_COLLECTION_CODE_EXISTS)

        resp2 = api_client.create_storage_zone(
            {"zone_code": "Z1", "name": "Vault B"}, REG)
        validate_error(resp2, ApiErrorId.ERR_ZONE_CODE_EXISTS)

        resp3 = api_client.create_researcher(
            {"full_name": "R. Other", "email": "r1@example.org"}, RRS)
        validate_error(resp3, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestPaginationEnvelope:

    def test_pagination_envelope_and_defaults(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when omitted and must lie between 1 and 100
        inclusive. The `offset` parameter specifies the number of items to skip
        and defaults to 0; it may not be negative. A `limit` outside the
        inclusive 1-to-100 range or a negative `offset` is rejected with
        `ERR_INVALID_PAGINATION_PARAMETERS`."
        PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/validations/pagination_envelope_and_defaults
        """
        zone = create_zone()
        for code in ("CA", "CB", "CC"):
            create_collection(zone["id"], collection_code=code, title=code)

        default_resp = api_client.list_collections(REG)
        body = default_resp.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["response_type"] == "array"
        data, meta = validate_paginated(default_resp)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        for row in data:
            assert_collection(row)

        page, meta2 = validate_paginated(
            api_client.list_collections(REG, params={"limit": 2, "offset": 2}))
        assert len(page) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            resp = api_client.list_collections(REG, params=bad)
            validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)
            assert resp.status_code == 400


class TestImmediateConsistency:

    def test_immediate_readback_after_create_and_cascade(self):
        """PRD §2.10: "The archive observes **immediate consistency**: every
        mutation, including every cascade a mutation triggers, is visible in the
        state returned by the triggering request. There is no deferred
        propagation."
        PRD §2.6: "A reading is severe when its temperature is greater than or
        equal to `temp_high_c` plus 4.0 degrees, or its humidity is greater than
        or equal to `humidity_high_pct` plus 15.0 percentage points; a severe
        reading is always also a breach."
        PRD §2.6: "A severe reading forces the posture to `CLOSED`, extends the
        breach run by one, and resets the in-range run."

        Design: Corner/consistency_model/immediate_readback_after_create_and_cascade
        """
        zone = create_zone()
        collection = create_collection(zone["id"])

        read_back = get_collection(collection["id"])
        assert read_back["title"] == collection["title"]
        assert read_back["version"] == 1

        # 29.0 >= 24.0 + 4.0 -> severe -> CLOSED with breach_streak 1, visible
        # in the POST response itself.
        zone_after = post_reading(zone["id"], "2026-08-01T01:00:00Z", 29.0)
        assert zone_after["posture"] == "CLOSED"
        got = get_zone(zone["id"])
        assert got["posture"] == "CLOSED"
        assert got["breach_streak"] == 1
        assert_storage_zone(got)
