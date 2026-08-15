"""Entity creation defaults, required/unknown fields, pagination, version counters."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    make_project, make_order, make_opening, configure_order, make_drawing,
    get_order, create_order_payload, create_opening_payload,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
ANY_H = TEST_USERS["any_headers"]
SC_H = TEST_USERS["shipping_coordinator_headers"]


class TestEntityCreation:
    def test_create_project_applies_defaults(self, api):
        """PRD §3.1: "A new project opens in `OPEN` status". PRD §2.4: "`id`
        (string): a server-minted UUID, with no type prefix." and "`created_at`
        (string): an ISO 8601 UTC timestamp with three fractional digits".

        Design: Corner/entities/create_project_applies_defaults
        """
        project = make_project(name="Atrium", site_address="1 Main St", contract_code="CC-1")
        fetched = validate_success(api.get_project(project["id"], ANY_H), 200)
        assert fetched["status"] == "OPEN"
        assert is_valid_uuid(fetched["id"]), "id must be a UUID without type prefix"
        assert is_iso8601_timestamp(fetched["created_at"]), "created_at must be ISO 8601"
        assert isinstance(fetched["version"], int) and fetched["version"] >= 1

    def test_create_order_missing_required_species_returns_invalid_request(self, api):
        """PRD §2.5: "Required fields must be present, unknown fields are
        rejected, enum values must be in range, and the structural time rules
        of §2.8 and §3.7 must hold; failures return `ERR_INVALID_REQUEST`".

        Design: Corner/entities/create_order_missing_required_species_returns_invalid_request
        """
        project = make_project(name="P", contract_code="CC-2")
        payload = create_order_payload(project["id"], order_code="O-X")
        del payload["species"]
        resp = api.create_order(payload, EST_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_order_with_unknown_field_returns_invalid_request(self, api):
        """PRD §2.5: "Required fields must be present, unknown fields are
        rejected, enum values must be in range, and the structural time rules
        of §2.8 and §3.7 must hold; failures return `ERR_INVALID_REQUEST`".

        Design: Corner/entities/create_order_with_unknown_field_returns_invalid_request
        """
        project = make_project(name="P", contract_code="CC-3")
        payload = create_order_payload(project["id"], order_code="O-Y")
        payload["budget_quote_cents"] = 1
        resp = api.create_order(payload, EST_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_opening_applies_leaf_count_default(self, api):
        """PRD §3.2: "A `leaf_count` may be supplied for multi-leaf openings
        and defaults to 1."

        Design: Corner/entities/create_opening_applies_leaf_count_default
        """
        project = make_project(name="P", contract_code="CC-4")
        order = make_order(project["id"], order_code="O-D")
        payload = create_opening_payload(order["id"], opening_no="D1")
        payload.pop("leaf_count", None)  # ensure leaf_count is omitted entirely
        opening = validate_success(api.create_opening(payload, EST_H), 201)
        assert opening["leaf_count"] == 1, "omitted leaf_count must default to 1"

    def test_create_order_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.5: "Required fields must be present, unknown fields are
        rejected, enum values must be in range". PRD §3.2: "a `species` of
        `OAK`, `MAPLE`, `CHERRY`, `WALNUT`, or `PAINT_GRADE`".

        Design: Corner/entities/create_order_invalid_enum_returns_invalid_request
        """
        project = make_project(name="P", contract_code="CC-5")
        payload = create_order_payload(project["id"], order_code="O-E", species="PINE")
        resp = api.create_order(payload, EST_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_get_opening_not_found_returns_404(self, api):
        """PRD §2.5: "each missing resource returns its own
        `ERR_{RESOURCE}_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/get_opening_not_found_returns_404
        """
        resp = api.get_opening("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ANY_H)
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_FOUND, 404)

    def test_create_opening_with_unknown_order_returns_404(self, api):
        """PRD §2.5: "Path identifiers are validated left to right first, then
        foreign-key fields in the request body in their declared input order;
        each missing resource returns its own `ERR_{RESOURCE}_NOT_FOUND`
        (HTTP 404)".

        Design: Corner/entities/create_opening_with_unknown_order_returns_404
        """
        payload = create_opening_payload(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", opening_no="Z1",
        )
        resp = api.create_opening(payload, EST_H)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)

    def test_list_openings_filter_and_pagination(self, api):
        """PRD §2.3: "Every list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more` inside the `meta`
        object of the envelope." PRD §3.2: "The opening list filters by
        `order_id`, `assigned_trip_id`, `fab_status`, and `ship_status`."

        Design: Corner/entities/list_openings_filter_and_pagination
        """
        project = make_project(name="P", contract_code="CC-6")
        order_a = make_order(project["id"], order_code="O-LA")
        order_b = make_order(project["id"], order_code="O-LB", species="MAPLE")
        for no in ("A1", "A2", "A3"):
            make_opening(order_a["id"], opening_no=no)
        make_opening(order_b["id"], opening_no="B1")

        page1, meta1 = validate_paginated(
            api.list_openings(ANY_H, params={"order_id": order_a["id"], "limit": 2, "offset": 0})
        )
        assert meta1["total_count"] == 3, f"expected total_count 3, got {meta1}"
        assert meta1["has_more"] is True
        assert len(page1) == 2
        assert all(item["order_id"] == order_a["id"] for item in page1), (
            "filter correctness: only order A's openings may appear"
        )

        page2, meta2 = validate_paginated(
            api.list_openings(ANY_H, params={"order_id": order_a["id"], "limit": 2, "offset": 2})
        )
        assert meta2["has_more"] is False
        assert len(page2) == 1, "offset 2 lands on the third opening"
        assert page2[0]["opening_no"] == "A3"

    def test_order_version_increments_on_each_mutation(self, api):
        """PRD §2.4: "`version` (integer): a counter that increments by exactly
        one on every mutation of the resource, whether the mutation arrives
        directly or through a cascade from another resource." PRD §3.3:
        "Creating a revision is itself an order mutation and increments the
        order's `version` by one."

        Design: Corner/entities/order_version_increments_on_each_mutation
        """
        project = make_project(name="P", contract_code="CC-7")
        order = make_order(project["id"], order_code="O-V")
        make_opening(order["id"], opening_no="V1")
        v0 = order["version"]
        configured = validate_success(
            api.set_order_status(order["id"], {"target_status": "CONFIGURED"}, EST_H), 200,
        )
        assert configured["version"] == v0 + 1, (
            f"configure must increment version by exactly 1: {v0} -> {configured['version']}"
        )
        drawing = make_drawing(order["id"])
        assert drawing["status"] == "DRAFT"
        v2 = get_order(order["id"])["version"]
        assert v2 == configured["version"] + 1, (
            f"drawing create must increment order version by exactly 1: "
            f"{configured['version']} -> {v2}"
        )
