"""Entity-level breadth: declared defaults on creation, retrieval of the two parallel
listing dimensions, list pagination and filtering, the two not-found families, shape
validation, computed-field authority and the two append-only record kinds."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_line_item,
    api_client,
    assert_append_only_fields,
    confirm_plan,
    create_forecast,
    create_listing,
    create_plan,
    make_seller_operator_headers,
    read_listing,
    read_lot,
    read_plan,
    read_seller,
    register_seller,
    run_storage_billing,
    seller_payload,
    seller_version,
    set_clock,
    setup_baseline,
    setup_received_lot,
    sku_listing_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# Fixed, deliberately unresolvable identifiers, one per resource family.
UNKNOWN_SELLER_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_FC_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_LISTING_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_PLAN_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_LOT_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_REMOVAL_ORDER_ID = "66666666-6666-4666-8666-666666666666"
UNKNOWN_CLAIM_ID = "77777777-7777-4777-8777-777777777777"


class TestSellerAccountCreation:
    """Registration answers with the declared inputs and a fully zeroed ledger set."""

    def test_a_new_seller_opens_active_with_every_ledger_at_zero(self):
        """The three declared inputs come back unchanged, all six ledgers and the
        utilization ratio start at zero, and the row is stamped from the logical clock.

        PRD 3.1: "The new account opens with `seller_status` of `ACTIVE` and every derived
        ledger at zero: `restock_reserved_units`, `open_discrepancy_units`,
        `suppressed_listing_count`, `storage_fee_accrued_cents`,
        `reimbursement_credit_cents` and `mcf_fee_accrued_cents` all start at 0, and
        `storage_utilization_ratio` starts at 0.0."
        PRD 2.4: "`version` (integer): starts at 1 when the resource is created and
        increments by exactly 1 on every subsequent mutation of that resource, again
        including derived-field-only mutations."

        Design: Corner/entities/seller_account_creation_returns_declared_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        response = api_client.create_seller(
            seller_payload(
                legal_name="Northwind Goods",
                storage_cubic_feet_entitlement=1000.0000,
                unit_cost_cap_cents=200000,
            ),
            ADMIN,
        )
        seller = validate_success(response, 201)
        assert seller["legal_name"] == "Northwind Goods"
        assert float(seller["storage_cubic_feet_entitlement"]) == pytest.approx(1000.0)
        assert seller["unit_cost_cap_cents"] == 200000
        assert seller["seller_status"] == "ACTIVE"
        assert seller["restock_reserved_units"] == 0
        assert seller["open_discrepancy_units"] == 0
        assert seller["suppressed_listing_count"] == 0
        assert seller["storage_fee_accrued_cents"] == 0
        assert seller["reimbursement_credit_cents"] == 0
        assert seller["mcf_fee_accrued_cents"] == 0
        assert float(seller["storage_utilization_ratio"]) == pytest.approx(0.0)
        assert seller["version"] == 1
        assert seller["created_at"].startswith("2026-08-01T00:00:00")

    def test_client_supplied_system_fields_are_discarded(self):
        """An identifier, a creation stamp, a version and a status supplied by the client
        are all ignored in favour of server-minted values.

        PRD 2.4: "Every persisted resource carries an `id`: a server-minted UUID with no
        type prefix, never supplied by the client."
        PRD 2.4: "The clock's startup value is exactly `2026-08-01T00:00:00Z`, and it never
        falls back to real time; a `MarketplaceAdmin` moves it by supplying a `to_iso8601`
        instant to the clock-setting capability, which answers with the resulting
        `current_utc`."

        Design: Corner/entities/seller_system_fields_generated_and_client_input_ignored
        """
        set_clock("2026-08-01T00:00:00Z")
        response = api_client.create_seller(
            seller_payload(
                id="99999999-9999-4999-8999-999999999999",
                created_at="2000-01-01T00:00:00Z",
                version=77,
                seller_status="SUSPENDED",
            ),
            ADMIN,
        )
        seller = validate_success(response, 201)
        assert seller["id"] != "99999999-9999-4999-8999-999999999999"
        assert seller["created_at"].startswith("2026-08-01T00:00:00")
        assert seller["version"] == 1
        assert seller["seller_status"] == "ACTIVE"


class TestSkuListingRetrieval:
    """The two parallel dimensions of a fresh listing start on different values."""

    def test_a_fresh_listing_reads_back_active_but_out_of_stock(self):
        """Nothing has ever been received, so the listing is ACTIVE and unsuppressed while
        its health already reports OUT_OF_STOCK and every rollup is 0.

        PRD 3.2: "A fresh listing opens at `listing_status` of `ACTIVE`, `inventory_health`
        of `OUT_OF_STOCK`, `suppression_reason` of `NONE`, `lot_ever_created` of false, and
        every unit rollup at 0 — `fulfillable_units`, `unfulfillable_units`,
        `missing_units`, `aged_over_365_units` and `recommended_replenishment_units`."
        PRD 2.8: "A `SkuListing` has a `listing_status` (either `ACTIVE` or `SUPPRESSED`)
        and an `inventory_health` (one of `HEALTHY`, `EXCESS_AGED`, `STRANDED` or
        `OUT_OF_STOCK`)."

        Design: Corner/entities/sku_listing_retrieval_returns_stored_and_initial_derived_fields
        """
        set_clock("2026-08-01T00:00:00Z")
        seller = register_seller()
        created = create_listing(
            seller["id"], sku="SKU-ALPHA", unit_cubic_feet=1.0000, unit_cost_cents=1250
        )

        listing = read_listing(created["id"], seller["id"])
        assert listing["sku"] == "SKU-ALPHA"
        assert float(listing["unit_cubic_feet"]) == pytest.approx(1.0)
        assert listing["unit_cost_cents"] == 1250
        assert listing["listing_status"] == "ACTIVE"
        assert listing["suppression_reason"] == "NONE"
        assert listing["inventory_health"] == "OUT_OF_STOCK"
        assert listing["fulfillable_units"] == 0
        assert listing["unfulfillable_units"] == 0
        assert listing["missing_units"] == 0
        assert listing["aged_over_365_units"] == 0
        assert listing["lot_ever_created"] is False
        assert listing["recommended_replenishment_units"] == 0


class TestInboundShipmentPlanListing:
    """Three plans of one seller, one of them confirmed, read through two pages."""

    def _three_plans_one_confirmed(self) -> dict:
        ctx = setup_baseline()
        first = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        add_line_item(first["id"], ctx["seller_id"], ctx["listing_id"], 100)
        confirm_plan(first["id"], ctx["seller_id"])
        second = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z"
        )
        third = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-14T00:00:00Z", "2026-08-15T00:00:00Z"
        )
        ctx.update({"first": first, "second": second, "third": third})
        return ctx

    def _page(self, ctx: dict, **params):
        params["seller_account_id"] = ctx["seller_id"]
        return validate_paginated(
            api_client.list_inbound_shipment_plans(ctx["seller_headers"], params=params)
        )

    def test_two_pages_report_the_same_total_and_flip_has_more(self):
        """A limit of 2 returns the two oldest plans with `has_more` true, and offsetting
        past them returns the single remaining plan with `has_more` false.

        PRD 2.3: "Both appear in the `meta` object of the response envelope alongside
        `total_count` (the total number of items matching the filter, ignoring pagination)
        and `has_more` (true when items remain beyond the current page)."
        PRD 2.3: "Unless a specific list operation says otherwise, list results are sorted
        by `created_at` in ascending order."

        Design: Corner/entities/inbound_shipment_plan_listing_paginates_and_filters_by_status
        """
        ctx = self._three_plans_one_confirmed()

        rows, meta = self._page(ctx, limit=2, offset=0)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(rows) == 2
        assert rows[0]["id"] == ctx["first"]["id"]

        rows, meta = self._page(ctx, limit=2, offset=2)
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["third"]["id"]

    def test_filtering_by_status_narrows_the_total_count_to_the_confirmed_plan(self):
        """`status=CONFIRMED` is exact-match equality, so only the confirmed plan counts
        while the two drafts stay behind untouched.

        PRD 2.3: "Filters, where a list operation offers them, are exact-match equality on
        the named field and combine conjunctively."
        PRD 3.3: "A new plan opens with `status` of `DRAFT`, `declared_units` of 0,
        `allocation_status` of `WITHIN_LIMIT`, `prep_compliance_status` of `PENDING`,
        `confirmed_at` of null, and every allocation and receipt figure at 0."

        Design: Corner/entities/inbound_shipment_plan_listing_paginates_and_filters_by_status
        """
        ctx = self._three_plans_one_confirmed()

        rows, meta = self._page(ctx, status="CONFIRMED")
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["id"] == ctx["first"]["id"]

        assert read_plan(ctx["second"]["id"], ctx["seller_id"])["status"] == "DRAFT"
        assert read_plan(ctx["third"]["id"], ctx["seller_id"])["status"] == "DRAFT"


class TestNotFoundFamilies:
    """Seven resource families, seven distinct 404 identifiers."""

    def test_each_family_answers_with_its_own_not_found_identifier(self):
        """An unresolvable path identifier never collapses into one shared code: each of
        the seven families reports its own.

        PRD 2.5: "Path parameters are resolved strictly left to right, and the first
        identifier that fails to resolve determines the error."
        PRD 2.5: "The full set of path-resolution failures is `ERR_SELLER_NOT_FOUND`,
        `ERR_FC_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_LOT_NOT_FOUND`, `ERR_REMOVAL_ORDER_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each
        carrying HTTP 404."

        Design: Corner/entities/path_ids_that_do_not_resolve_return_family_specific_not_found
        """
        set_clock("2026-08-01T00:00:00Z")
        validate_error(
            api_client.get_seller(UNKNOWN_SELLER_ID, ADMIN),
            ApiErrorId.ERR_SELLER_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_fulfillment_center(UNKNOWN_FC_ID, ADMIN),
            ApiErrorId.ERR_FC_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_sku_listing(UNKNOWN_LISTING_ID, ADMIN),
            ApiErrorId.ERR_LISTING_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_inbound_shipment_plan(UNKNOWN_PLAN_ID, ADMIN),
            ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_inventory_lot(UNKNOWN_LOT_ID, ADMIN),
            ApiErrorId.ERR_LOT_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_removal_order(UNKNOWN_REMOVAL_ORDER_ID, ADMIN),
            ApiErrorId.ERR_REMOVAL_ORDER_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_reimbursement_claim(UNKNOWN_CLAIM_ID, ADMIN),
            ApiErrorId.ERR_CLAIM_NOT_FOUND.value, 404,
        )


class TestBodyForeignKeyResolution:
    """Foreign keys carried in a body use the same vocabulary as path identifiers."""

    def _baseline_with_one_draft_plan(self) -> dict:
        ctx = setup_baseline()
        ctx["plan"] = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        return ctx

    def test_each_unresolvable_body_key_reports_its_own_family(self):
        """Four write endpoints, four different orphaned keys, four family-specific 404s.

        PRD 2.5: "Foreign keys supplied in a request body are resolved with the same
        vocabulary."
        PRD 2.5: "A `seller_account_id` that does not resolve yields
        `ERR_SELLER_NOT_FOUND`; a `destination_fc_id` yields `ERR_FC_NOT_FOUND`; a
        `sku_listing_id` yields `ERR_LISTING_NOT_FOUND`; an `inventory_lot_id` yields
        `ERR_LOT_NOT_FOUND`."

        Design: Corner/entities/body_foreign_keys_that_do_not_resolve_are_not_found
        """
        ctx = self._baseline_with_one_draft_plan()
        validate_error(
            api_client.create_sku_listing(
                sku_listing_payload(UNKNOWN_SELLER_ID, sku="SKU-ORPHAN"),
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_SELLER_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.create_inbound_shipment_plan(
                {
                    "seller_account_id": ctx["seller_id"],
                    "destination_fc_id": UNKNOWN_FC_ID,
                    "appointment_window_start": "2026-08-10T00:00:00Z",
                    "appointment_window_end": "2026-08-11T00:00:00Z",
                    "expected_seller_account_version": seller_version(ctx["seller_id"]),
                },
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_FC_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.create_line_item(
                ctx["plan"]["id"],
                {
                    "sku_listing_id": UNKNOWN_LISTING_ID,
                    "units": 100,
                    "case_pack_units": 10,
                    "polybagged": True,
                    "label_type": "FNSKU",
                },
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_LISTING_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.file_reimbursement_claim(
                {
                    "inventory_lot_id": UNKNOWN_LOT_ID,
                    "claim_type": "LOST_INBOUND",
                    "claimed_units": 5,
                    "evidence_document_count": 2,
                    "evidence_reference": "X-1",
                },
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_LOT_NOT_FOUND.value, 404,
        )

    def test_a_rejected_creation_persists_nothing_at_all(self):
        """The plan creation that failed on its centre key leaves the seller's version and
        the surviving draft's declaration exactly where they were.

        PRD 2.10: "A successful plan creation itself increments the seller's `version` by
        1, so the next creation must quote the new value."
        PRD 2.10: "If `expected_seller_account_version` does not equal the seller's current
        `version`, the request is rejected with `ERR_STALE_SELLER_VERSION` (HTTP 412) and
        nothing is persisted."

        Design: Corner/entities/body_foreign_keys_that_do_not_resolve_are_not_found
        """
        ctx = self._baseline_with_one_draft_plan()
        version_before = seller_version(ctx["seller_id"])

        api_client.create_inbound_shipment_plan(
            {
                "seller_account_id": ctx["seller_id"],
                "destination_fc_id": UNKNOWN_FC_ID,
                "appointment_window_start": "2026-08-10T00:00:00Z",
                "appointment_window_end": "2026-08-11T00:00:00Z",
                "expected_seller_account_version": version_before,
            },
            ctx["seller_headers"],
        )
        assert seller_version(ctx["seller_id"]) == version_before
        assert read_plan(ctx["plan"]["id"], ctx["seller_id"])["declared_units"] == 0


class TestRequiredFieldValidation:
    """Shape validation runs before any foreign key is resolved."""

    def test_a_listing_without_its_volume_is_an_invalid_request(self):
        """Omitting `unit_cubic_feet` is refused as a shape failure and no listing row
        survives under the seller.

        PRD 2.6: "Request-body shape on every write: required fields present, enum values
        drawn from their declared member sets, numeric fields inside their declared bounds,
        arrays non-null and well-formed — `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD 3.2: "A `SellerOperator` creates a listing by supplying the owning
        `seller_account_id`, a `sku`, a positive `unit_cubic_feet` carried to four decimals,
        and a non-negative `unit_cost_cents` that later drives both liquidation recovery and
        reimbursement valuation."

        Design: Corner/entities/sku_listing_creation_missing_required_field_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        seller = register_seller()
        headers = make_seller_operator_headers(seller["id"])

        response = api_client.create_sku_listing(
            {
                "seller_account_id": seller["id"],
                "sku": "SKU-ALPHA",
                "unit_cost_cents": 1250,
            },
            headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _rows, meta = validate_paginated(
            api_client.list_seller_sku_listings(seller["id"], headers)
        )
        assert meta["total_count"] == 0


class TestPlanCreationDefaults:
    """Every computed counter on a new plan starts at its declared default."""

    def test_a_new_plan_opens_as_an_empty_within_limit_draft(self):
        """All six counters read 0, both status dimensions read their defaults, there is no
        confirmation stamp, and the guarded creation moved the seller's version by one.

        PRD 3.3: "A new plan opens with `status` of `DRAFT`, `declared_units` of 0,
        `allocation_status` of `WITHIN_LIMIT`, `prep_compliance_status` of `PENDING`,
        `confirmed_at` of null, and every allocation and receipt figure at 0."
        PRD 2.10: "A successful plan creation itself increments the seller's `version` by
        1, so the next creation must quote the new value."

        Design: Corner/entities/plan_creation_defaults_applied_to_every_computed_counter
        """
        ctx = setup_baseline()
        version_before = seller_version(ctx["seller_id"])
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z",
            expected_seller_account_version=version_before,
        )
        assert plan["status"] == "DRAFT"

        stored = read_plan(plan["id"], ctx["seller_id"])
        assert stored["declared_units"] == 0
        assert stored["provisional_allocated_units"] == 0
        assert stored["final_allocated_units"] == 0
        assert stored["allocated_units"] == 0
        assert stored["allocation_status"] == "WITHIN_LIMIT"
        assert stored["prep_compliance_status"] == "PENDING"
        assert stored["received_units"] == 0
        assert stored["missing_units"] == 0
        assert stored["confirmed_at"] is None
        assert read_seller(ctx["seller_id"])["version"] == version_before + 1


class TestLineItemComputedAllocation:
    """Allocation figures belong to the waterfall, not to the caller."""

    def test_client_supplied_allocation_and_receipt_figures_are_ignored(self):
        """The line is granted its full 100 units by the provisional waterfall regardless
        of the 99999 the client asked for, and its receipt counters stay at 0.

        PRD 3.3: "For `PROVISIONAL`, each line's grant is written to its
        `provisional_allocated_units` and the total to the plan's
        `provisional_allocated_units`; the plan's `allocation_status` becomes
        `WITHIN_LIMIT` when that total equals `declared_units` and `OVER_LIMIT` otherwise."
        PRD 3.3: "Adding a line recomputes the plan's `declared_units` as the sum of
        `units` across its line items, and re-runs the provisional allocation waterfall."

        Design: Corner/entities/line_item_computed_allocation_client_input_ignored
        """
        ctx = setup_baseline()
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        line = add_line_item(
            plan["id"], ctx["seller_id"], ctx["listing_id"], 100,
            provisional_allocated_units=99999, received_units=4242,
        )
        assert line["provisional_allocated_units"] == 100
        assert line["received_units"] == 0
        assert line["final_allocated_units"] == 0
        assert line["shortfall_units"] == 0

        stored = read_plan(plan["id"], ctx["seller_id"])
        assert stored["declared_units"] == 100
        assert stored["provisional_allocated_units"] == 100
        assert stored["allocation_status"] == "WITHIN_LIMIT"


class TestRemovalOrderTypeConstraints:
    """Shape failures outrank the lot's optimistic-concurrency guard."""

    def test_an_unknown_removal_method_is_an_invalid_request(self):
        """`SHRED` is not a declared member of the enum, so the request never reaches the
        pool arithmetic and the lot keeps every unit unreserved.

        PRD 3.6: "A `SellerOperator` requests a removal against a lot by naming the
        `inventory_lot_id`, a `removal_method` of `DISPOSAL`, `RETURN_TO_SELLER` or
        `LIQUIDATION`, a `unit_pool` of either `FULFILLABLE` or `UNFULFILLABLE`, a
        `requested_units` count of at least 1, a `removal_window_start` and a
        `removal_window_end` (strictly after the start), and the
        `expected_inventory_lot_version` guard."
        PRD 2.6: "Request-body shape on every write: required fields present, enum values
        drawn from their declared member sets, numeric fields inside their declared bounds,
        arrays non-null and well-formed — `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/removal_order_invalid_enum_and_non_positive_units_rejected
        """
        ctx = setup_received_lot(units=100)
        version_before = read_lot(ctx["lot_id"], ctx["seller_id"])["version"]

        response = api_client.create_removal_order(
            {
                "inventory_lot_id": ctx["lot_id"],
                "removal_method": "SHRED",
                "unit_pool": "FULFILLABLE",
                "requested_units": 10,
                "removal_window_start": "2026-09-01T00:00:00Z",
                "removal_window_end": "2026-09-02T00:00:00Z",
                "expected_inventory_lot_version": version_before,
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["units_reserved_for_removal"] == 0
        assert lot["version"] == version_before

    def test_zero_requested_units_is_an_invalid_request_even_with_a_stale_version(self):
        """The body carries both a non-positive count and a deliberately stale lot version;
        shape validation sits above the version guard, so the answer is the 400 and no
        removal order exists afterwards.

        PRD 2.6: "Because several operations are guarded by many rules at once, the order
        of evaluation is part of the contract: the first rule that fails determines the
        response, and no later rule may mask an earlier one."
        PRD 2.6: "Version guards on the two sizing writes described in §2.10 —
        `ERR_STALE_SELLER_VERSION` and `ERR_STALE_LOT_VERSION`, both HTTP 412."

        Design: Corner/entities/removal_order_invalid_enum_and_non_positive_units_rejected
        """
        ctx = setup_received_lot(units=100)
        version_before = read_lot(ctx["lot_id"], ctx["seller_id"])["version"]

        response = api_client.create_removal_order(
            {
                "inventory_lot_id": ctx["lot_id"],
                "removal_method": "DISPOSAL",
                "unit_pool": "FULFILLABLE",
                "requested_units": 0,
                "removal_window_start": "2026-09-01T00:00:00Z",
                "removal_window_end": "2026-09-02T00:00:00Z",
                "expected_inventory_lot_version": version_before - 1,
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["units_reserved_for_removal"] == 0
        assert lot["version"] == version_before

        _rows, meta = validate_paginated(
            api_client.list_lot_removal_orders(ctx["lot_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 0


class TestAppendOnlyComputationRecords:
    """Assessments and forecasts accumulate rows; they are never rewritten."""

    def _thirty_stored_units(self) -> dict:
        return setup_received_lot(
            units=30,
            appointment_window_start="2026-08-01T00:00:00Z",
            appointment_window_end="2026-08-02T00:00:00Z",
        )

    def test_a_second_billing_run_appends_a_row_rather_than_updating_the_first(self):
        """Two runs at the same instant each assess 2610 cents, leaving two immutable rows
        oldest-first and a lot accrual of their sum.

        PRD 2.4: "Two resource kinds are append-only records of a computation rather than
        living entities, and they carry only `id` and `created_at`: `StorageFeeAssessment`
        and `VelocityForecast` both omit `updated_at` and omit `version` entirely."
        PRD 3.9: "Each lot's `monthly_storage_fee_cents` and `ltsf_surcharge_cents` are
        rounded half up to whole cents **first**, then added together per lot, then the
        per-lot integers are summed into the lot's `storage_fee_accrued_cents` and into the
        seller's `storage_fee_accrued_cents`."

        Design: Corner/entities/storage_fee_assessment_and_velocity_forecast_are_immutable_records
        """
        ctx = self._thirty_stored_units()
        first_run = run_storage_billing()
        second_run = run_storage_billing()
        assert first_run["total_assessed_cents"] == 2610
        assert second_run["billing_run_sequence"] == 2
        assert second_run["total_assessed_cents"] == 2610

        rows, meta = validate_paginated(
            api_client.list_storage_fee_assessments(
                ctx["lot_id"], ctx["seller_headers"], params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert rows[0]["billing_run_sequence"] == 1
        assert rows[1]["billing_run_sequence"] == 2
        for row in rows:
            assert_append_only_fields(row)

        assert read_lot(ctx["lot_id"], ctx["seller_id"])["storage_fee_accrued_cents"] == 5220
        assert read_seller(ctx["seller_id"])["storage_fee_accrued_cents"] == 5220

    def test_two_forecasts_leave_two_rows_with_the_newest_read_first(self):
        """The second forecast does not overwrite the first: both rows survive, the list
        answers newest first, and neither row carries a version.

        PRD 2.3: "Two operations invert that default because recency is what the reader
        wants: the seller's quota periods are returned newest first, and a listing's
        velocity forecasts are returned newest first."
        PRD 3.3: "Under `TRAILING_30`, `daily_velocity` is `trailing_30_units_sold` divided
        by the 30-day trailing window, rounded half up to four decimal places; the
        prior-year figure and the `seasonal_index` are ignored even when supplied."

        Design: Corner/entities/storage_fee_assessment_and_velocity_forecast_are_immutable_records
        """
        ctx = self._thirty_stored_units()
        first = create_forecast(
            ctx["listing_id"], ctx["seller_id"], forecast_variant="TRAILING_30",
            trailing_30_units_sold=300, prior_year_same_period_units_sold=0,
            seasonal_index=1.00, coverage_target_days=10, lead_time_days=0,
        )
        second = create_forecast(
            ctx["listing_id"], ctx["seller_id"], forecast_variant="TRAILING_30",
            trailing_30_units_sold=600, prior_year_same_period_units_sold=0,
            seasonal_index=1.00, coverage_target_days=10, lead_time_days=0,
        )
        assert float(first["daily_velocity"]) == pytest.approx(10.0)
        assert float(second["daily_velocity"]) == pytest.approx(20.0)

        rows, meta = validate_paginated(
            api_client.list_velocity_forecasts(
                ctx["listing_id"], ctx["seller_headers"],
                params={"forecast_variant": "TRAILING_30", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2
        assert float(rows[0]["daily_velocity"]) == pytest.approx(20.0)
        assert float(rows[1]["daily_velocity"]) == pytest.approx(10.0)
        for row in rows:
            assert_append_only_fields(row)
