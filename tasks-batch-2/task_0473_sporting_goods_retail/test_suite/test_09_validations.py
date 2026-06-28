"""Business validations: fitment, embroidery gating, markdown window, price-match
genuineness, pagination bounds, license-required.

Corner queue: validations section. The instance
validations/insufficient_inventory_violation_on_place is an excluded_because stub
whose assertion is owned by the difficulty instance
resource_temporal_overlap/inventory_aggregate_capacity_overlap_two_reservations
(translated in test_05) — no separate test is emitted for the stub.
"""
import pytest
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    create_draft_order,
    add_order_line,
    setup_placed_order,
    submit_price_match_claim,
    make_customer_headers,
    create_sku_payload,
    create_markdown_payload,
    create_order_line_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PRICE_ADMIN = TEST_USERS["price_admin_headers"]


def test_footwear_line_without_fitment_rejected(api):
    """PRD §3.3: "a footwear line (a line whose SKU has `is_footwear` true) requires
    that the SKU carry a real, non-`NA` `size_label`, failing which the add is
    rejected with `ERR_FITMENT_REQUIRED`."

    Design: Corner/validations/footwear_line_without_fitment_rejected
    """
    store = create_store(state_code="CA")
    # FOOTWEAR SKU with default size_label NA (omitted) -> fitment unspecified.
    sku = get_success_data(api.create_sku(
        {"sport": "FOOTWEAR", "name": "Mystery Shoe", "base_price_cents": 9000}, ADMIN
    ))
    customer = create_customer(home_state_code="CA")

    order = create_draft_order(customer["id"], store["id"])
    res = api.create_order_line(
        order["id"], create_order_line_payload(sku["id"], 1),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_FITMENT_REQUIRED", expected_status=422)


def test_embroidery_on_non_embroiderable_sku_rejected(api):
    """PRD §3.3: "`embroidery_text` may only be supplied when the SKU is
    `embroiderable`, and a line whose SKU is not embroiderable but carries embroidery
    text is rejected with `ERR_EMBROIDERY_NOT_ALLOWED`".

    Design: Corner/validations/embroidery_on_non_embroiderable_sku_rejected
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="APPAREL", name="Plain Tee", base_price_cents=2000, size_label="M")
    customer = create_customer(home_state_code="CA")

    order = create_draft_order(customer["id"], store["id"])
    res = api.create_order_line(
        order["id"], create_order_line_payload(sku["id"], 1, embroidery_text="NO"),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_EMBROIDERY_NOT_ALLOWED", expected_status=422)


def test_markdown_invalid_window_rejected(api):
    """PRD §3.2: "The window must be non-empty — `effective_from` strictly before
    `effective_until` — and `percent_off` must lie within 1 to 90 inclusive; a
    violation of either is rejected with `ERR_INVALID_MARKDOWN_WINDOW`."

    Design: Corner/validations/markdown_invalid_window_from_after_until_rejected
    """
    sku = create_sku(sport="APPAREL", name="Vest", base_price_cents=4000, size_label="L")
    res = api.create_markdown(
        create_markdown_payload(sku["id"], "SEASONAL", 20,
                                "2026-05-01T00:00:00Z", "2026-04-01T00:00:00Z"),
        PRICE_ADMIN,
    )
    validate_error(res, "ERR_INVALID_MARKDOWN_WINDOW", expected_status=422)


def test_price_match_competitor_not_lower_rejected(api):
    """PRD §3.7: "a `competitor_price_cents` that is not strictly below the line's
    `unit_price_cents` is rejected with `ERR_PRICE_MATCH_NOT_LOWER`."

    A competitor price equal to the line's 5000 unit price is rejected.

    Design: Corner/validations/price_match_competitor_not_lower_rejected
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Bat4", base_price_cents=5000, size_label="30in")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, lines = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    claim = submit_price_match_claim(placed["id"], lines[0]["id"], customer["id"], 5000)
    res = api.approve_price_match_claim(claim["id"], PRICE_ADMIN)
    validate_error(res, "ERR_PRICE_MATCH_NOT_LOWER", expected_status=422)


def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "The `limit` parameter bounds how many items are returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected
    with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/validations/pagination_limit_out_of_bounds_rejected
    """
    res = api.list_skus(ADMIN, params={"limit": 500})
    validate_error(res, "ERR_VALIDATION_PAGINATION", expected_status=422)


def test_license_required_on_place_without_license(api):
    """PRD §3.4: "If such a line is present at placement and no qualifying active
    license exists for that store, the placement is rejected with
    `ERR_LICENSE_REQUIRED`."

    Inventory is sufficient (qty 5) so this isolates the license check from the
    inventory check.

    Design: Corner/validations/license_required_violation_on_place
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FISHING", name="Reel Combo", base_price_cents=4000,
                     size_label="NA", requires_license_permit=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    order = create_draft_order(customer["id"], store["id"])
    add_order_line(order["id"], customer["id"], sku["id"], 1)
    res = api.place_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_LICENSE_REQUIRED", expected_status=422)
