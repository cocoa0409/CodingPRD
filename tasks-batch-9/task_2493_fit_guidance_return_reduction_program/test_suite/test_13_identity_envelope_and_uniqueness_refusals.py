"""Refusals decided from the request itself or from a key that is already taken.

None of these requests get far enough to touch business state: one carries a role
the system never declared, three collide with a uniqueness rule, and two ask a
list endpoint for a page it is not allowed to serve.  Each test also checks that
the refused write left the resource it aimed at exactly as it was.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiErrorId,
    create_fit_feedback_payload,
    create_measurement_spec_payload,
    create_return_case_payload,
    create_vendor_payload,
    make_customer_headers,
    make_headers,
    make_merch_ops_admin_headers,
    make_vendor_user_headers,
    size_point,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

SCENARIO_START = "2026-06-01T00:00:00Z"

TOPS_THIRTY_DAY_POLICY = {
    "window_days": 30,
    "restocking_applies": True,
    "non_refundable_shipping": False,
    "effective_from": "2026-01-01T00:00:00Z",
}


def test_a_role_the_system_never_declared_is_rejected_as_unauthenticated(api):
    """PRD §2.9: "**Authentication.** `X-User-ID` and `X-User-Role` are present and the
    role is one of the five declared names, otherwise `ERR_UNAUTHENTICATED` (401).
    Applies to every endpoint."  A plausible-sounding but undeclared role is an
    authentication failure rather than a permission failure, so the answer is 401 and
    not 403, and the brand code the refused request carried is still free afterwards.

    Design: Corner/validations/undeclared_role_header_returns_unauthenticated
    """
    fx.set_clock(api, SCENARIO_START)

    payload = create_vendor_payload(
        name="Rogue Apparel", brand_code="ROGE", correction_budget_cents=1000
    )
    response = api.create_vendor(payload, make_headers("intern-1", "SizingIntern"))
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    vendor = validate_success(
        api.create_vendor(payload, make_merch_ops_admin_headers()), 201
    )
    assert vendor["brand_code"] == "ROGE"
    assert vendor["name"] == "Rogue Apparel"


def test_a_second_brand_reusing_a_registered_code_is_refused(api):
    """PRD §2.9: "**Unique keys.** `Vendor.brand_code`, `CatalogItem.sku`,
    `SizeChart.chart_code`, and `CustomerProfile.email` are still free, otherwise
    `ERR_DUPLICATE_RESOURCE_KEY` (409). Applies to vendor creation, catalog-item
    creation, size-chart creation, and customer-profile creation."  A different trading
    name does not buy a second claim on the same code, and the registration that got
    there first keeps its own name and its own funded allowance.

    Design: Corner/validations/duplicate_brand_code_returns_duplicate_resource_key
    """
    fx.set_clock(api, SCENARIO_START)
    first = fx.create_vendor(api)

    response = api.create_vendor(
        create_vendor_payload(
            name="Northwind Studio", brand_code="NRTH", correction_budget_cents=5000
        ),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE_KEY.value, 409)

    survivor = fx.read_vendor(api, first["id"])
    assert survivor["brand_code"] == "NRTH"
    assert survivor["name"] == "Northwind Apparel"
    assert survivor["correction_budget_cents"] == 250000


def test_a_page_size_outside_the_declared_range_is_refused_not_clamped(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, a non-integer
    value for either parameter, or an `offset` below 0, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."  Both out-of-range parameters are refusals
    rather than silent corrections, so a caller asking for 101 rows gets an error
    instead of 100, and a caller asking to skip minus one row gets an error instead of
    zero.

    Design: Corner/validations/pagination_limit_above_maximum_returns_invalid_pagination
    """
    fx.setup_vendor_and_item(api, SCENARIO_START)

    over_limit = api.list_catalog_items(
        make_merch_ops_admin_headers(), {"limit": 101, "offset": 0}
    )
    validate_error(over_limit, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    negative_offset = api.list_catalog_items(
        make_merch_ops_admin_headers(), {"limit": 10, "offset": -1}
    )
    validate_error(negative_offset, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_the_maximum_page_size_itself_is_served_and_echoed_back(api):
    """PRD §2.3: "`limit` caps the number of rows returned; when omitted it defaults to
    10, its minimum accepted value is 1 and its maximum accepted value is 100."  One
    hundred is the largest accepted value rather than the first rejected one, so the
    same collection that refused 101 serves 100 and reports the page it applied
    alongside the single row that matches.

    Design: Corner/validations/pagination_limit_above_maximum_returns_invalid_pagination
    """
    built = fx.setup_vendor_and_item(api, SCENARIO_START)

    rows, meta = validate_paginated(
        api.list_catalog_items(
            make_merch_ops_admin_headers(), {"limit": 100, "offset": 0}
        )
    )

    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [built["item"]["id"]]


def test_a_fresh_specification_cannot_bypass_an_unfinished_one(api):
    """PRD §2.9: "**No revision in flight.** The item has no measurement specification
    in `DRAFT`, `SUBMITTED`, or `CORRECTION_REQUESTED`, otherwise
    `ERR_SPEC_REVISION_IN_FLIGHT` (409). Applies to measurement-specification
    creation."  Filing a second specification is how a brand would sidestep the
    correction loop, so while the first one is still awaiting verification the item
    keeps exactly one specification and it is the one that was filed first.

    Design: Corner/validations/second_specification_while_revision_in_flight_returns_conflict
    """
    built = fx.setup_submitted_spec(api, SCENARIO_START)
    assert built["spec"]["status"] == "SUBMITTED"

    response = api.create_measurement_spec(
        create_measurement_spec_payload(
            built["item"]["id"],
            size_system="US_NUMERIC",
            base_size_label="2",
            fabric_stretch_class="STRETCH",
            size_points=[
                size_point("2", 0, 840, 760, 880, 710),
                size_point("4", 1, 880, 800, 920, 720),
            ],
        ),
        make_vendor_user_headers(built["vendor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SPEC_REVISION_IN_FLIGHT.value, 409)

    rows, meta = validate_paginated(
        api.list_measurement_specs(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [built["spec"]["id"]]

    spec = fx.read_spec(api, built["spec"]["id"])
    assert spec["size_system"] == "US_ALPHA"
    assert spec["status"] == "SUBMITTED"


def test_a_second_return_on_one_purchased_line_is_refused(api):
    """PRD §2.9: "**No duplicate case.** The order line carries no return case in
    `TRIAGE`, `FIT_REVIEW`, `QUALITY_REVIEW`, `EXPECTATION_REVIEW`, `COOLING_OFF`,
    `RESOLVED_REFUNDED`, or `RESOLVED_DENIED`, otherwise `ERR_DUPLICATE_RETURN_CASE`
    (409). Applies to return-case creation."  A case still sitting in triage occupies
    the line, so the second request is refused with a different reason code than the
    first and the shopper's return count does not grow — a rejected attempt cannot
    inflate the abuse arithmetic.

    Design: Corner/validations/second_case_on_the_same_order_line_returns_duplicate_return_case
    """
    built = fx.setup_triage_case(
        api,
        SCENARIO_START,
        case_overrides={"requested_reason_code": "FIT_TOO_SMALL"},
        policy_overrides=dict(TOPS_THIRTY_DAY_POLICY),
        customer_overrides={"email": "shopper-v4@example.com"},
        line_overrides={
            "size_label": "M",
            "quantity": 1,
            "unit_price_cents": 2295,
            "shipping_allocated_cents": 0,
            "delivered_at": "2026-05-20T00:00:00Z",
        },
    )

    response = api.create_return_case(
        create_return_case_payload(
            built["order_line"]["id"], requested_reason_code="CHANGE_OF_MIND"
        ),
        make_customer_headers(built["customer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RETURN_CASE.value, 409)

    rows, meta = validate_paginated(
        api.list_return_cases(
            make_merch_ops_admin_headers(),
            {"order_line_id": built["order_line"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [built["case"]["id"]]

    case = fx.read_case(api, built["case"]["id"])
    assert case["status"] == "TRIAGE"
    assert case["reason_code"] == "FIT_TOO_SMALL"

    shopper = fx.read_customer(api, built["customer"]["id"])
    assert shopper["return_case_count"] == 1
    assert shopper["return_rate_bp"] == 10000


def test_a_shoppers_second_review_of_one_item_is_refused(api):
    """PRD §3.5: "The submitted `customer_profile_id` must equal the acting
    `X-User-ID`, and a shopper may hold only one `ACTIVE` feedback row per item — a
    second attempt is refused with `ERR_DUPLICATE_FIT_FEEDBACK`."  The first review
    stands with the verdict it was written with and the weight of a reviewer who never
    bought the garment, and the item's signal pool is unchanged by the refusal.

    Design: Corner/validations/second_active_fit_feedback_for_one_shopper_returns_conflict
    """
    built = fx.setup_listed_item(api, SCENARIO_START)
    customer = fx.create_customer(api, email="shopper-v10@example.com")

    first = fx.post_feedback(
        api,
        built["item"]["id"],
        customer["id"],
        purchased_size_label="M",
        fit_verdict="SLIGHTLY_SMALL",
    )
    assert first["status"] == "ACTIVE"
    assert first["signal_weight"] == 100

    response = api.create_fit_feedback(
        create_fit_feedback_payload(
            built["item"]["id"],
            customer["id"],
            purchased_size_label="M",
            fit_verdict="TOO_SMALL",
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_FIT_FEEDBACK.value, 409)

    rows, meta = validate_paginated(
        api.list_fit_feedback(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["fit_verdict"] == "SLIGHTLY_SMALL"

    item = fx.read_item(api, built["item"]["id"])
    assert item["active_fit_feedback_count"] == 1
    assert item["fit_signal_weight_total"] == 100
