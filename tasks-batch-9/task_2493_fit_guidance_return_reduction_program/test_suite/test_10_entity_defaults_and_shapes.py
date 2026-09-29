"""What each stored row looks like the moment it is first written.

Every resource in the program opens with a declared set of computed defaults, and
several of them are refused outright when the body they arrive in is malformed or
names a row that does not exist.  These tests read the freshly created
representation back and check the opening values, the two absent keys of the
append-only ledger line, and the four rejections the creation ladder issues before
any business rule is consulted.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    assert_catalog_item_shape,
    assert_customer_profile_shape,
    assert_gross_line_consistent,
    assert_optional_field_is_null,
    assert_order_line_shape,
    assert_postings_in_declared_order,
    assert_return_cost_posting_shape,
    assert_vendor_shape,
    create_catalog_item_payload,
    create_measurement_spec_payload,
    create_order_line_payload,
    create_vendor_payload,
    ids_of,
    is_iso8601_timestamp,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_vendor_user_headers,
    size_point,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

# A two-point chest run that is structurally sound on its own, so the only thing
# wrong with the specification bodies below is the field each one omits or misnames.
TWO_POINT_RUN = [
    size_point("S", 0, 840, 760, 880, 710),
    size_point("M", 1, 880, 800, 920, 720),
]


def _register_brand(api: ApiClient) -> dict:
    """One brand on a clock pinned to the first of June, which every scenario in
    this module starts from."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    return fx.create_vendor(
        api,
        name="Northwind Apparel",
        brand_code="NRTH",
        correction_budget_cents=250000,
    )


def test_a_freshly_registered_brand_opens_with_a_perfect_record(api):
    """PRD §3.1: "A freshly registered vendor opens with `status` `ACTIVE`,
    `reliability_score_bp` at 10,000, `correction_spend_cents` at 0,
    `correction_round_count` at 0, and `quality_chargeback_count` at 0."  No
    correction round and no chargeback exist yet, so nothing has been deducted from
    the opening score, the three declared inputs come back exactly as supplied, and
    the row is on its first version.

    Design: Corner/entities/vendor_creation_returns_declared_fields_with_computed_defaults
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")

    vendor = validate_success(
        api.create_vendor(
            create_vendor_payload(
                name="Northwind Apparel",
                brand_code="NRTH",
                correction_budget_cents=250000,
            ),
            make_merch_ops_admin_headers(),
        ),
        201,
    )

    assert_vendor_shape(vendor)
    assert vendor["name"] == "Northwind Apparel"
    assert vendor["brand_code"] == "NRTH"
    assert vendor["correction_budget_cents"] == 250000
    assert vendor["correction_spend_cents"] == 0
    assert vendor["correction_round_count"] == 0
    assert vendor["quality_chargeback_count"] == 0
    assert vendor["reliability_score_bp"] == 10000
    assert vendor["status"] == "ACTIVE"
    assert vendor["version"] == 1
    assert is_iso8601_timestamp(vendor["created_at"])
    assert vendor["created_at"].startswith("2026-06-01T00:00:00")

    assert fx.read_vendor(api, vendor["id"])["brand_code"] == "NRTH"


def test_a_new_item_opens_at_the_foot_of_both_state_axes(api):
    """PRD §3.1: "A new item opens at `DRAFT` on its storefront axis, `UNVERIFIED`
    on its readiness axis, and `NORMAL` on its chronic-return classification, and
    every one of its derived return metrics — `units_sold_count`, `fit_return_count`,
    `expectation_return_count`, `total_return_count`, `fit_return_rate_bp`,
    `expectation_return_rate_bp`, `chronic_return_score_bp`,
    `return_cost_accrued_cents`, `fit_signal_weight_total`, and
    `active_fit_feedback_count` — opens at 0."  The two axes take their defaults
    independently of one another, and PRD §3.1 adds that "Its `pdp_review_required`
    flag opens false, its `delist_reason_code` is null, and `model_height_cm` and
    `model_worn_size_label` are null until the product page is enhanced."

    Design: Corner/entities/catalog_item_creation_defaults_both_state_axes_and_pdp_fields
    """
    vendor = _register_brand(api)

    item = validate_success(
        api.create_catalog_item(
            create_catalog_item_payload(
                vendor["id"],
                sku="NRTH-TEE-01",
                category_code="TOPS",
                brand_size_system="US_ALPHA",
                unit_price_cents=2295,
            ),
            make_merch_ops_admin_headers(),
        ),
        201,
    )

    assert_catalog_item_shape(item)
    assert item["listing_status"] == "DRAFT"
    assert item["fit_readiness"] == "UNVERIFIED"
    assert item["fit_watch_state"] == "NORMAL"
    assert item["units_sold_count"] == 0
    assert item["fit_return_count"] == 0
    assert item["expectation_return_count"] == 0
    assert item["total_return_count"] == 0
    assert item["fit_return_rate_bp"] == 0
    assert item["expectation_return_rate_bp"] == 0
    assert item["chronic_return_score_bp"] == 0
    assert item["return_cost_accrued_cents"] == 0
    assert item["fit_signal_weight_total"] == 0
    assert item["active_fit_feedback_count"] == 0
    assert item["pdp_review_required"] is False
    assert_optional_field_is_null(item, "delist_reason_code")
    assert_optional_field_is_null(item, "model_height_cm")
    assert_optional_field_is_null(item, "model_worn_size_label")
    assert item["version"] == 1


def test_the_storefront_filter_pages_two_of_the_brands_three_items(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the number of rows matching
    the filters before the limit and offset are applied."  Two of the brand's three
    items are on the storefront, so a one-row page of the listed filter reports a
    total of 2 with more to come, the second page reports the same total with nothing
    left, and the draft item appears in neither page while still counting toward the
    readiness filter that matches all three.

    Design: Corner/entities/catalog_item_list_filters_by_vendor_and_listing_axis_with_pagination
    """
    vendor = _register_brand(api)
    listed = [
        fx.list_item(
            api,
            fx.create_item(
                api,
                vendor["id"],
                sku=sku,
                category_code="TOPS",
                brand_size_system="US_ALPHA",
                unit_price_cents=price,
            )["id"],
        )
        for sku, price in (("NRTH-TEE-01", 2295), ("NRTH-TEE-02", 2495))
    ]
    draft = fx.create_item(
        api,
        vendor["id"],
        sku="NRTH-TEE-03",
        category_code="TOPS",
        brand_size_system="US_ALPHA",
        unit_price_cents=2695,
    )

    first_rows, first_meta = validate_paginated(
        api.list_catalog_items(
            make_merch_ops_admin_headers(),
            {
                "vendor_id": vendor["id"],
                "listing_status": "LISTED",
                "limit": 1,
                "offset": 0,
            },
        )
    )
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert len(first_rows) == 1

    second_rows, second_meta = validate_paginated(
        api.list_catalog_items(
            make_merch_ops_admin_headers(),
            {
                "vendor_id": vendor["id"],
                "listing_status": "LISTED",
                "limit": 1,
                "offset": 1,
            },
        )
    )
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert len(second_rows) == 1

    paged = ids_of(first_rows) + ids_of(second_rows)
    assert sorted(paged) == sorted(ids_of(listed))
    assert draft["id"] not in paged

    readiness_rows, readiness_meta = validate_paginated(
        api.list_catalog_items(
            make_merch_ops_admin_headers(),
            {
                "vendor_id": vendor["id"],
                "fit_readiness": "UNVERIFIED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert readiness_meta["total_count"] == 3
    assert readiness_meta["has_more"] is False
    assert draft["id"] in ids_of(readiness_rows)


def test_reading_a_specification_that_was_never_written(api):
    """PRD §2.9: "Every identifier in the URL resolves, validated left to right, so
    the leftmost unresolvable identifier decides the error: `ERR_VENDOR_NOT_FOUND`,
    `ERR_ITEM_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`, `ERR_CHART_NOT_FOUND`,
    `ERR_MAPPING_NOT_FOUND`, `ERR_CUSTOMER_PROFILE_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
    `ERR_RETURN_CASE_NOT_FOUND`, `ERR_FEEDBACK_NOT_FOUND`,
    `ERR_INTERVENTION_NOT_FOUND`, or `ERR_DEPLOYMENT_NOT_FOUND`, each HTTP 404."
    The identifier in the path is a specification identifier, so the specification
    code is the one that comes back with HTTP 404 even though the database is not
    empty and the brand behind it does resolve.

    Design: Corner/entities/measurement_spec_read_with_unknown_id_returns_spec_not_found
    """
    vendor = _register_brand(api)

    response = api.get_measurement_spec(NON_EXISTENT_UUID, make_fit_analyst_headers())
    validate_error(response, ApiErrorId.ERR_SPEC_NOT_FOUND.value, 404)

    assert fx.read_vendor(api, vendor["id"])["brand_code"] == "NRTH"


def test_a_specification_without_a_base_size_label_is_malformed(api):
    """PRD §2.9: "Required body fields are present and correctly typed, numbers lie
    within their declared bounds, enum-valued fields carry declared members,
    `size_points` has at least 2 entries with unique `size_label` values and unique
    non-negative `sort_index` values, `grade_rules` entries have distinct
    `measurement_point` values, and `base_size_label` appears among the
    `size_points`."  The size run and the grade rule are both well formed, so the
    only defect is the missing required field, and the refusal leaves the item with
    no specification at all.

    Design: Corner/entities/measurement_spec_without_base_size_label_returns_invalid_request
    """
    vendor = _register_brand(api)
    item = fx.create_item(
        api,
        vendor["id"],
        sku="NRTH-TEE-01",
        category_code="TOPS",
        brand_size_system="US_ALPHA",
        unit_price_cents=2295,
    )

    payload = create_measurement_spec_payload(
        item["id"],
        size_system="US_ALPHA",
        base_size_label=None,
        fabric_stretch_class="RIGID",
        size_points=TWO_POINT_RUN,
    )
    assert "base_size_label" not in payload

    response = api.create_measurement_spec(
        payload, make_vendor_user_headers(vendor["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_measurement_specs(
            make_fit_analyst_headers(),
            {"item_id": item["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_category_outside_the_five_declared_members_is_refused(api):
    """PRD §3.1: "Catalog items are created by a `MerchOpsAdmin` with a payload
    naming the `vendor_id` that supplies them, a merchant `sku` unique across the
    catalog, a `category_code` of `TOPS`, `BOTTOMS`, `DRESSES`, `OUTERWEAR`, or
    `FOOTWEAR`, the `brand_size_system` the brand labels the item in — one of
    `US_ALPHA`, `US_NUMERIC`, `EU`, or `UK` — and a `unit_price_cents` list price of
    at least 1."  Swimwear is not among those five, so the creation is rejected with
    HTTP 400 rather than coerced into a neighbouring category, and the brand still
    owns no items.

    Design: Corner/entities/catalog_item_with_undeclared_category_code_returns_invalid_request
    """
    vendor = _register_brand(api)

    response = api.create_catalog_item(
        create_catalog_item_payload(
            vendor["id"],
            sku="NRTH-SWM-01",
            category_code="SWIMWEAR",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        ),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_catalog_items(
            make_merch_ops_admin_headers(),
            {"vendor_id": vendor["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_gross_line_is_the_unit_price_times_the_quantity(api):
    """PRD §3.7: "The line's `gross_line_cents` is computed as `unit_price_cents`
    multiplied by `quantity`, and the line opens with `status` `DELIVERED`."  Three
    units at 2,295 cents give 6,885, and the allocated shipping rides alongside that
    figure rather than inside it.  PRD §3.7 also makes the ingest a cascade: "Ingest
    is itself a small cascade: the item's `units_sold_count`, its two return rates,
    its `chronic_return_score_bp`, and its `fit_watch_state` are all recomputed, and
    so are the shopper's `purchase_line_count`, `return_rate_bp`, `abuse_status`, and
    `policy_class`."  The units counter therefore reads 3 while every rate stays at 0,
    because no return exists to divide by it.

    Design: Corner/entities/order_line_gross_line_cents_computed_from_price_times_quantity
    """
    vendor = _register_brand(api)
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="NRTH-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    customer = fx.create_customer(api, email="shopper-c6@example.com")

    line = validate_success(
        api.create_order_line(
            create_order_line_payload(
                customer["id"],
                item["id"],
                size_label="M",
                quantity=3,
                unit_price_cents=2295,
                shipping_allocated_cents=495,
                delivered_at="2026-05-20T00:00:00Z",
            ),
            make_merch_ops_admin_headers(),
        ),
        201,
    )

    assert_order_line_shape(line)
    assert line["gross_line_cents"] == 6885
    assert_gross_line_consistent(line)
    assert line["status"] == "DELIVERED"
    assert line["shipping_allocated_cents"] == 495

    stored = fx.read_item(api, item["id"])
    assert stored["units_sold_count"] == 3
    assert stored["fit_return_rate_bp"] == 0
    assert stored["expectation_return_rate_bp"] == 0
    assert stored["chronic_return_score_bp"] == 0
    assert stored["fit_watch_state"] == "NORMAL"

    shopper = fx.read_customer(api, customer["id"])
    assert shopper["purchase_line_count"] == 1
    assert shopper["return_case_count"] == 0
    assert shopper["return_rate_bp"] == 0


def test_an_omitted_tier_opens_a_shorter_window_than_a_declared_one(api):
    """PRD §3.7: "Shopper records are created by a `MerchOpsAdmin` with a unique
    `email` and an optional `tier` of `STANDARD` or `PLUS`; when `tier` is omitted it
    defaults to `STANDARD`."  PRD §3.7 then turns that stored tier into a policy
    class: "Its `policy_class` opens at `STANDARD_WINDOW`, except that a `PLUS`
    shopper with `CLEAR` standing opens at `EXTENDED_WINDOW`."  Both shoppers open
    with identical clear standing and no purchase history, so the tier is the only
    thing that separates their two policy classes.

    Design: Corner/entities/customer_profile_tier_default_drives_standard_policy_class
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")

    standard = fx.create_customer(api, email="std-c7@example.com")
    plus = fx.create_customer(api, email="plus-c7@example.com", tier="PLUS")

    assert_customer_profile_shape(standard)
    assert standard["tier"] == "STANDARD"
    assert standard["policy_class"] == "STANDARD_WINDOW"
    assert standard["abuse_status"] == "CLEAR"
    assert standard["abuse_strike_count"] == 0
    assert standard["refunded_total_cents"] == 0

    assert plus["tier"] == "PLUS"
    assert plus["policy_class"] == "EXTENDED_WINDOW"
    assert plus["abuse_status"] == "CLEAR"


def test_the_cost_ledger_exposes_no_version_and_no_update_stamp(api):
    """PRD §2.4: "A `ReturnCostPosting` is an immutable ledger line: it carries only
    `id` and `created_at`. It has no `updated_at` and no `version`, and those keys
    must be absent from its representation rather than present and null."  Closing a
    fit return on a single 2,295-cent unit writes five original rows in the declared
    component order — 795 of inbound freight, 558 of handling, 34 of refurbishment,
    nothing to markdown and 67 of unrecovered payment fee, 1,454 in all — and every
    one of them is readable but unwritable, with `reversed_component` null because
    nothing has been reversed.

    Design: Corner/entities/return_cost_postings_are_append_only_rows_without_a_version_field
    """
    vendor = _register_brand(api)
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="NRTH-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    fx.create_policy(
        api,
        category_code="TOPS",
        window_days=30,
        restocking_applies=True,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    customer = fx.create_customer(api, email="shopper-c9@example.com")
    line = fx.create_order_line(
        api,
        customer["id"],
        item["id"],
        size_label="M",
        quantity=1,
        unit_price_cents=2295,
        shipping_allocated_cents=0,
        delivered_at="2026-05-20T00:00:00Z",
    )
    case = fx.open_case(
        api, line["id"], customer["id"], requested_reason_code="FIT_TOO_SMALL"
    )
    fx.classify_case(api, case["id"], "FIT_TOO_SMALL")
    resolved = fx.resolve_case(api, case["id"], "RESELLABLE_A")

    assert resolved["refund_amount_cents"] == 2295
    assert resolved["total_cost_cents"] == 1454

    postings = fx.read_cost_postings(api, case["id"])
    assert len(postings) == 5
    for row in postings:
        assert_return_cost_posting_shape(row)
        assert row["posting_kind"] == "ORIGINAL"
        assert row["return_case_id"] == case["id"]
        assert_optional_field_is_null(row, "reversed_component")

    assert_postings_in_declared_order(postings)
    assert [row["component"] for row in postings] == [
        "FREIGHT_INBOUND",
        "PROCESSING_LABOR",
        "REFURB_REPACK",
        "MARKDOWN_LOSS",
        "PAYMENT_FEE_UNRECOVERED",
    ]
    assert [row["amount_cents"] for row in postings] == [795, 558, 34, 0, 67]

    assert fx.read_item(api, item["id"])["return_cost_accrued_cents"] == 1454


def test_a_specification_naming_an_item_that_does_not_exist(api):
    """PRD §2.9: "Every foreign key supplied in the body resolves, validated in the
    order the fields are declared in the request body, yielding
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CHART_NOT_FOUND`,
    `ERR_CUSTOMER_PROFILE_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, or
    `ERR_INTERVENTION_NOT_FOUND` (404)."  The specification body carries a single
    foreign key, so an unallocated item identifier is answered with the item code and
    HTTP 404 before ownership or any grade rule is looked at, and the brand's real
    item is left without a specification.

    Design: Corner/entities/specification_creation_for_unknown_item_returns_item_not_found
    """
    vendor = _register_brand(api)
    item = fx.create_item(
        api,
        vendor["id"],
        sku="NRTH-TEE-01",
        category_code="TOPS",
        brand_size_system="US_ALPHA",
        unit_price_cents=2295,
    )

    response = api.create_measurement_spec(
        create_measurement_spec_payload(
            NON_EXISTENT_UUID,
            size_system="US_ALPHA",
            base_size_label="S",
            fabric_stretch_class="RIGID",
            size_points=TWO_POINT_RUN,
        ),
        make_vendor_user_headers(vendor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 404)

    _, meta = validate_paginated(
        api.list_measurement_specs(
            make_fit_analyst_headers(),
            {"item_id": item["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0


def test_the_second_foreign_key_of_an_order_line_is_resolved_too(api):
    """PRD §2.9: "Every foreign key supplied in the body resolves, validated in the
    order the fields are declared in the request body, yielding
    `ERR_VENDOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_CHART_NOT_FOUND`,
    `ERR_CUSTOMER_PROFILE_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, or
    `ERR_INTERVENTION_NOT_FOUND` (404)."  An order line declares two of them: the
    shopper resolves, so the check moves on to the purchased item, which does not,
    and the item code comes back with HTTP 404 while the shopper's purchase count
    stays where it opened.

    Design: Corner/entities/order_line_creation_validates_second_body_foreign_key_reference
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    customer = fx.create_customer(api, email="shopper-c11@example.com")

    response = api.create_order_line(
        create_order_line_payload(
            customer["id"],
            NON_EXISTENT_UUID,
            size_label="M",
            quantity=1,
            unit_price_cents=2295,
            shipping_allocated_cents=0,
            delivered_at="2026-05-20T00:00:00Z",
        ),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 404)

    shopper = fx.read_customer(api, customer["id"])
    assert shopper["purchase_line_count"] == 0
    assert shopper["version"] == customer["version"]
