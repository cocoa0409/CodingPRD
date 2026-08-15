"""Buying-point intake posture, response envelope, pagination, clock, auth."""
from test_helpers import (
    CLOCK_STARTUP_DEFAULT_MS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_warehouse,
    api_client,
    assert_buying_point,
    assert_grower,
    create_buying_point_payload,
    create_grower_payload,
    get_buying_point,
    is_valid_uuid,
    make_grower_headers,
    report_load,
    setup_buying_point,
    weigh_load,
    setup_grower,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestBuyingPointPosture:

    def test_buying_point_without_warehouses_starts_suspended(self):
        """PRD section 2.7: "A buying point with no warehouses has zero
        aggregate free tonnage and is therefore `SUSPENDED` from the moment it
        is created."
        PRD section 3.1: "The buying point's `ops_run_index` starts at zero and
        increments only through the operations checkpoint described in §3.6."

        Design: Corner/entities/buying_point_without_warehouses_starts_suspended
        """
        bp = setup_buying_point()
        assert_buying_point(bp)
        assert bp["intake_posture"] == "SUSPENDED", \
            f"no warehouses => free_total 0 => SUSPENDED, got {bp['intake_posture']}"
        assert bp["ops_run_index"] == 0
        assert isinstance(bp["version"], int) and bp["version"] >= 1

        fetched = get_buying_point(bp["id"])
        assert fetched["intake_posture"] == "SUSPENDED"
        assert fetched["ops_run_index"] == 0

    def test_posture_threshold_boundaries(self):
        """PRD section 2.7: "The boundaries are exact: exactly zero free tons
        means `SUSPENDED`, exactly 500 means `RESTRICTED`, and 501 means
        `OPEN`."

        Design: Corner/calculations/posture_threshold_boundaries
        """
        bp = setup_buying_point()
        assert get_buying_point(bp["id"])["intake_posture"] == "SUSPENDED"

        add_warehouse(bp["id"], name="WH-1", capacity_tons=500)
        assert get_buying_point(bp["id"])["intake_posture"] == "RESTRICTED", \
            "free_total exactly 500 must be RESTRICTED (inclusive threshold)"

        add_warehouse(bp["id"], name="WH-2", capacity_tons=1)
        assert get_buying_point(bp["id"])["intake_posture"] == "OPEN", \
            "free_total 501 must be OPEN"

    def test_intake_suspended_blocks_load_create(self):
        """PRD section 3.3: "the grower must be `ACTIVE`, or the report is
        rejected with `ERR_GROWER_SUSPENDED`, and the buying point's posture
        must not be `SUSPENDED`, or the report is rejected with
        `ERR_INTAKE_SUSPENDED`."

        Design: Corner/validations/intake_suspended_blocks_load_create
        """
        bp = setup_buying_point()
        grower = setup_grower()
        resp = api_client.create_load(
            {"grower_id": grower["id"], "crop_year": 2026},
            make_grower_headers(grower["id"]))
        validate_error(resp, ApiErrorId.ERR_INTAKE_SUSPENDED)

    def test_restricted_weigh_cap_boundary(self):
        """PRD section 2.7: "When aggregate free tonnage is above zero but no
        more than 500 tons, the posture is `RESTRICTED`: load reporting remains
        open, but any weigh-in whose `gross_tons` exceeds 50 tons is rejected
        with `ERR_RESTRICTED_LOAD_LIMIT`."

        Design: Corner/validations/restricted_weigh_cap_boundary
        """
        bp = setup_buying_point()
        add_warehouse(bp["id"], capacity_tons=400)
        grower = setup_grower()
        assert get_buying_point(bp["id"])["intake_posture"] == "RESTRICTED"

        load_a = report_load(grower["id"])
        load_b = report_load(grower["id"])

        # exactly at the cap: allowed
        weighed = weigh_load(load_a["id"], 50.0)
        assert weighed["status"] == "WEIGHED"

        # one millitonne over the cap: rejected
        resp = api_client.weigh_load(load_b["id"], {"gross_tons": 50.001}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_RESTRICTED_LOAD_LIMIT)
        load_b_after = api_client.get_load(load_b["id"], ADMIN)
        assert load_b_after.json()["data"]["status"] == "REPORTED"
        assert get_buying_point(bp["id"])["intake_posture"] == "RESTRICTED"


class TestEnvelopeAndMeta:

    def test_response_envelope_and_meta_fields(self):
        """PRD section 2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their JSON body"
        and "All error API responses (4xx status codes) follow this standard
        envelope format".
        PRD section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_and_meta_fields
        """
        setup_buying_point()

        resp = api_client.create_grower(create_grower_payload(), ADMIN)
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        grower = body["data"]
        assert is_valid_uuid(grower["id"])

        resp = api_client.get_grower(NON_EXISTENT_UUID, ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]

        resp = api_client.list_growers(ADMIN)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta
        assert meta["total_count"] == 1

    def test_pagination_limit_offset_has_more(self):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter says how many items to skip and defaults to 0."
        PRD section 2.3: "List responses carry four pagination fields in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/pagination_limit_offset_has_more
        """
        setup_buying_point()
        for i in range(1, 4):
            api_client.create_grower(
                create_grower_payload(name=f"G{i}", farm_number=f"F-100{i}"),
                ADMIN)

        page1 = api_client.list_growers(ADMIN, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2 = api_client.list_growers(ADMIN, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        default_page = api_client.list_growers(ADMIN)
        data3, meta3 = validate_paginated(default_page)
        assert meta3["limit"] == 10
        assert len(data3) == 3
        assert meta3["has_more"] is False

    def test_logical_clock_default_fixed_at_startup(self):
        """PRD section 2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; before any operator action it remains at that
        default."
        PRD section 2.4: "`created_at` (string): an ISO 8601 UTC timestamp with
        three fractional digits, set when the resource is created."

        Design: Corner/cross_cutting/logical_clock_default_fixed_at_startup
        """
        # No clock call anywhere in this test: server stays at startup default.
        resp = api_client.create_buying_point(create_buying_point_payload(), ADMIN)
        bp = validate_success(resp, expected_status=201)
        add_warehouse(bp["id"])
        grower = setup_grower()
        load = report_load(grower["id"])
        assert load["created_at"] == CLOCK_STARTUP_DEFAULT_MS, (
            f"without any clock call, created_at must be the startup default "
            f"2026-08-01T00:00:00.000Z, got {load['created_at']}"
        )


class TestAuthentication:

    def test_missing_auth_headers_return_unauthenticated(self):
        """PRD section 2.1: "A request whose headers are missing, or whose role
        value is not one of the declared role names, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_return_unauthenticated
        """
        bp = setup_buying_point()
        resp = api_client.get_buying_point(bp["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_load_get_not_found_returns_404(self):
        """PRD section 2.10: "The request is rejected with `ERR_NOT_FOUND` at
        the first identifier that does not resolve to an existing resource,
        before any later identifier or body reference is examined."

        Design: Corner/entities/load_get_not_found_returns_404
        """
        setup_buying_point()
        resp = api_client.get_load(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
