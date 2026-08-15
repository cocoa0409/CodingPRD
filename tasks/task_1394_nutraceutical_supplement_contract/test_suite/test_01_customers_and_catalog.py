"""Customer onboarding, catalog entities, system fields, and batch listing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    WINDOW_DAY1,
    WINDOW_DAY2,
    ApiErrorId,
    assert_customer,
    create_customer,
    create_customer_payload,
    create_formula,
    create_material_lot_payload,
    create_raw_material,
    create_raw_material_payload,
    is_valid_uuid,
    make_catalog,
    run_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestCustomerCreation:
    def test_create_customer_applies_zero_aggregates_and_object_envelope(self, api):
        """PRD §2.12: "These aggregates are initialized to zero at customer creation
        and are adjusted on order placement, cancellation, completion (via batch
        release), rejection (via batch reject), and recall tracing, so that at all
        times `committed_order_value_cents` plus `lifetime_receipts_cents` equals
        the sum of `total_price_cents` over all of the customer's non-`CANCELLED`
        orders."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/entities/create_customer_success_defaults_and_envelope
        """
        resp = api.create_customer(create_customer_payload("Acme"), PLANNER)
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["committed_order_value_cents"] == 0
        assert data["open_order_count"] == 0
        assert data["lifetime_receipts_cents"] == 0
        assert data["open_recall_count"] == 0

        get_resp = api.get_customer(data["id"], QA)
        body = get_resp.json()
        assert get_resp.status_code == 200
        assert body["response_type"] == "object", (
            f"single-resource GET must use the object envelope, got {body['response_type']}"
        )
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        fetched = validate_success(get_resp, 200)
        assert fetched["id"] == data["id"]

    def test_create_customer_without_brand_name_returns_invalid_request(self, api):
        """PRD §3.1: "A `ProductionPlanner` onboards a brand by creating a Customer
        with a non-empty `brand_name`".
        PRD §2.9: "14. Request-body shape: required fields present, types and enum
        values valid (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/create_customer_missing_brand_name_returns_invalid_request
        """
        resp = api.create_customer({}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_create_raw_material_with_undeclared_allergen_class_rejected(self, api):
        """PRD §3.2: "Raw materials are registered by a `ProductionPlanner` with a
        non-empty `name` and an `allergen_class` from the same ten-value enumeration
        used on formulas."
        PRD §2.9: "14. Request-body shape: required fields present, types and enum
        values valid (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/create_raw_material_invalid_enum_returns_invalid_request
        """
        resp = api.create_raw_material(
            create_raw_material_payload("Mystery", "LATEX"), PLANNER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_get_batch_with_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "The system checks each path identifier in sequence and rejects
        the request with `ERR_NOT_FOUND` at the first identifier that does not
        correspond to an existing resource, before examining any later identifier
        or any business rule."

        Design: Corner/entities/get_batch_unknown_id_returns_not_found
        """
        resp = api.get_batch(NON_EXISTENT_UUID, QA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestMaterialLotReceipt:
    def test_lot_receipt_enters_quarantine_with_full_qty_remaining(self, api):
        """PRD §3.2: "The lot enters in `QUARANTINE` status with `qty_remaining`
        initialized to `qty_received`; it cannot be consumed by production until
        quality releases it."

        Design: Corner/entities/material_lot_receipt_initializes_qty_remaining
        """
        material = create_raw_material("VitC", "NONE")
        resp = api.create_material_lot(
            create_material_lot_payload(material["id"], qty_received=250000),
            TEST_USERS["production_operator_headers"],
        )
        data = validate_success(resp, 201)
        assert data["status"] == "QUARANTINE"
        assert data["qty_remaining"] == 250000, (
            f"qty_remaining must initialize to qty_received, got {data['qty_remaining']}"
        )
        assert is_valid_uuid(data["id"])


class TestFormulaCreation:
    def test_formula_created_under_customer_starts_draft_with_lines(self, api):
        """PRD §3.1: "A newly created formula starts in `DRAFT` status, and its
        FormulaLine rows are created from the `lines` payload with `formula_id`
        pointing back at their formula."
        PRD §3.1: "Anyone may later inspect a formula's lines or enumerate which
        formulas a customer owns."

        Design: Corner/entities/formula_created_nested_under_customer_in_draft
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        formula = create_formula(customer["id"], material["id"])
        assert formula["status"] == "DRAFT"
        assert formula["customer_id"] == customer["id"], (
            "nested creation must bind the formula to the path customer"
        )

        lines, _meta = validate_paginated(
            api.list_formula_lines(formula["id"], QA)
        )
        assert len(lines) == 1
        assert lines[0]["formula_id"] == formula["id"]
        assert lines[0]["raw_material_id"] == material["id"]

        owned, _ = validate_paginated(
            api.list_customer_formulas(customer["id"], QA)
        )
        assert [f["id"] for f in owned] == [formula["id"]], (
            "the customer's formula listing must contain exactly the created formula"
        )


class TestLogicalClockDefault:
    def test_created_at_uses_default_logical_clock_without_set(self, api):
        """PRD §2.6: "At startup, before any explicit set, the logical clock reads
        exactly 2026-08-01T00:00:00Z."
        PRD §2.4: "The `created_at` timestamp records creation time as ISO 8601 UTC
        with three fractional digits."

        Design: Corner/entities/clock_default_timestamp_applied_without_set
        """
        resp = api.create_customer(create_customer_payload("Acme"), PLANNER)
        data = validate_success(resp, 201)
        assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
            f"created_at must read the default logical clock, got {data['created_at']}"
        )


class TestBatchListing:
    def test_list_batches_paginates_and_filters_by_order(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.4: "The batch registry can be browsed with optional `mo_id`,
        `production_line_id`, and `quality_status` filters alongside `limit` and
        `offset`."

        Design: Corner/entities/list_batches_pagination_and_filter
        """
        ctx = make_catalog()
        run1 = run_batch(ctx, window=WINDOW_DAY1, stage="SCHEDULED")
        run_batch(ctx, window=WINDOW_DAY2, stage="SCHEDULED")

        page, meta = validate_paginated(api.list_batches(QA, params={"limit": 1}))
        assert len(page) == 1, f"limit=1 must return exactly 1 row, got {len(page)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

        filtered, fmeta = validate_paginated(
            api.list_batches(QA, params={"mo_id": run1["mo"]["id"]})
        )
        assert len(filtered) == 1
        assert fmeta["total_count"] == 1
        assert filtered[0]["id"] == run1["batch"]["id"], (
            "mo_id filter must narrow to the batch created by that order's scheduling"
        )
