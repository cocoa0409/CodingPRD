"""Corner tests — §entities (creation, listing, not-found, required fields,
computed fields, FK relationships)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_line,
    api_client,
    create_customer_order_payload,
    create_dealer,
    create_model,
    create_order,
    create_spec,
    get_success_data,
    set_clock,
    setup_order_with_line,
    validate_error,
    validate_paginated,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_create_customer_order_success_and_defaults(api):
    """PRD §3.2: "A new order sits in `DRAFT` with `quality_result` `NONE` and
    all monetary totals at zero."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/create_customer_order_success_and_defaults
    """
    dealer = create_dealer()
    res = api.create_customer_order(create_customer_order_payload(
        order_number="ORD-2001", dealer_id=dealer["id"],
    ), SALES)
    order = validate_success(res, 201)
    assert order["status"] == "DRAFT"
    assert order["quality_result"] == "NONE"
    assert order["subtotal_cents"] == 0
    assert order["total_cents"] == 0
    assert order["com_credit_cents"] == 0
    assert order["version"] == 1
    body = res.json()
    assert body["response_type"] == "object"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]


def test_list_orders_pagination_fields(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §4: "orders by `dealer_id`."

    Design: Corner/entities/list_orders_pagination_fields
    """
    dealer = create_dealer()
    create_order("ORD-P1", dealer["id"], ship_to_state="NC")
    create_order("ORD-P2", dealer["id"], ship_to_state="SC",
                 delivery_method="WHITE_GLOVE")

    data1, meta1 = validate_paginated(api.list_customer_orders(
        SALES, params={"limit": 1, "offset": 0}))
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert len(data1) == 1

    data2, meta2 = validate_paginated(api.list_customer_orders(
        SALES, params={"limit": 1, "offset": 1}))
    assert meta2["has_more"] is False
    assert len(data2) == 1

    # Filter by dealer returns both
    data_f, meta_f = validate_paginated(api.list_customer_orders(
        SALES, params={"dealer_id": dealer["id"]}))
    assert meta_f["total_count"] == 2


def test_get_order_not_found_returns_404(api):
    """PRD §2.8: "Existence and uniqueness — ids referenced in the path and
    body are resolved left to right, and the first missing reference produces
    that resource's 404."
    PRD §2.2: All error API responses carry `response_type` of `error` per the
    standard envelope.

    Design: Corner/entities/get_order_not_found_returns_404
    """
    res = api.get_customer_order(NON_EXISTENT_UUID, SALES)
    validate_error(res, "ERR_ORDER_NOT_FOUND", expected_status=404)
    assert res.json()["response_type"] == "error"


def test_create_order_missing_required_dealer_id_returns_invalid_request(api):
    """PRD §2.8: "3. **Request well-formedness** — required fields present,
    enum values legal, numeric ranges sane... failures yield
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "a `SalesRep` opens a **CustomerOrder** with a unique
    `order_number`, the `dealer_id` of the ordering dealer, the two-letter
    `ship_to_state`..."

    Design: Corner/entities/create_order_missing_required_dealer_id_returns_invalid_request
    """
    res = api.create_customer_order({
        "order_number": "ORD-X",
        "ship_to_state": "NC",
        "delivery_method": "LTL_FREIGHT",
    }, SALES)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_line_create_unit_price_input_ignored(api):
    """PRD §3.2: "As the line is created, the system resolves its option-matrix
    row and computes the read-only `matched_surcharge_pct`, `unit_price_cents`,
    and `line_total_cents` described in §3.3."

    Design: Corner/entities/line_create_unit_price_input_ignored
    """
    model = create_model(
        model_code="M-PRICE", category="CHAIR", base_fabric_yards=2.0,
        base_price_cents=10002, requires_pattern_match=False,
        flammability_standard="TB133",
        option_rules=[{
            "fabric_grade": "C", "finish_code": "WALNUT",
            "allowed": True, "surcharge_pct": 0.13, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-C", origin="PLANT", grade="C",
                       nominal_width_inches=54.0, price_per_yard_cents=4000)
    dealer = create_dealer()
    order = create_order("ORD-CI", dealer["id"])

    # Client tries to inject unit_price_cents — server computes it instead
    res = api.create_order_line({
        "order_id": order["id"], "model_id": model["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "WALNUT", "quantity": 2, "unit_price_cents": 1,
    }, SALES)
    line = validate_success(res, 201)
    assert line["unit_price_cents"] == 11302
    assert line["matched_surcharge_pct"] == pytest.approx(0.13, abs=0.0001)
    assert line["line_total_cents"] == 22604


def test_fk_line_create_with_unknown_order_returns_not_found(api):
    """PRD §2.8: "Existence and uniqueness — ids referenced in the path and
    body are resolved left to right, and the first missing reference produces
    that resource's 404."

    Design: Corner/entities/fk_line_create_with_unknown_order_returns_not_found
    """
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    # Unknown order_id — left-to-right means order checked before model
    res1 = api.create_order_line({
        "order_id": NON_EXISTENT_UUID, "model_id": model["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "ESPRESSO", "quantity": 1,
    }, SALES)
    validate_error(res1, "ERR_ORDER_NOT_FOUND", expected_status=404)

    # Both unknown — order still reported first
    res2 = api.create_order_line({
        "order_id": NON_EXISTENT_UUID, "model_id": NON_EXISTENT_UUID,
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "ESPRESSO", "quantity": 1,
    }, SALES)
    validate_error(res2, "ERR_ORDER_NOT_FOUND", expected_status=404)
