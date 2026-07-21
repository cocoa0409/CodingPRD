"""Product creation, order-line validation, and blend/production business rules (corners)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_product, new_account, new_order, new_production_line, new_batch,
    new_blend_component, setup_blend_ready_to_produce,
    create_product_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
CATALOG = TEST_USERS["catalog_headers"]
PROD = TEST_USERS["production_headers"]
SALES = TEST_USERS["sales_headers"]


# ---- Corner / entities ----

def test_create_product_returns_active_out_of_stock(api):
    """PRD §3.1: "Newly created products begin with `status` of `ACTIVE` and, because no
    lots exist yet, an initial `stock_state` of `OUT_OF_STOCK`."

    Design: Corner/entities/corner_product_create_returns_full_entity
    """
    payload = create_product_payload(name="Ceylon Cinnamon", category="SPICE",
                                     kind="SIMPLE", unit_price_cents_per_gram=3.5,
                                     tare_default_grams=10)
    product = validate_success(api.create_product(payload, CATALOG), expected_status=201)
    assert product["status"] == "ACTIVE", product["status"]
    assert product["stock_state"] == "OUT_OF_STOCK", product["stock_state"]


def test_product_with_no_lots_reads_out_of_stock(api):
    """PRD §2.9: "a product is `IN_STOCK` when it has at least one `AVAILABLE`, non-expired
    lot whose `grams_on_hand` is greater than zero, and `OUT_OF_STOCK` otherwise. This
    value is never set directly by a client."

    Design: Corner/entities/corner_product_stock_state_out_of_stock_on_create
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    read = validate_success(api.get_product(cham["id"], CATALOG))
    assert read["stock_state"] == "OUT_OF_STOCK", read["stock_state"]


def test_add_order_line_without_requested_grams_rejected(api):
    """PRD §3.6: "each **order line** names the `product_id` being purchased and the
    `requested_grams` the buyer wants, which must be greater than zero."

    Design: Corner/entities/corner_add_line_missing_required_grams
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api)
    order = new_order(api, account["id"])
    resp = api.add_order_line(order["id"], {"product_id": cham["id"]}, SALES)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---- Corner / validations ----

def test_produce_simple_product_batch_rejected_not_blend(api):
    """PRD §3.3: "Production first requires that `blend_product_id` resolve to a product
    whose `kind` is `BLEND`; a non-blend target is rejected with `ERR_PRODUCT_NOT_BLEND`."

    Design: Corner/validations/corner_produce_non_blend_returns_not_blend
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    line = new_production_line(api)
    batch = new_batch(api, cham["id"], line["id"], target_output_grams=100)
    resp = api.produce_batch(batch["id"], PROD)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_BLEND.value)


def test_produce_blend_with_bad_ratio_sum_rejected(api):
    """PRD §3.1: "Across all components of a single blend, the shares are required to sum to
    exactly 10000 basis points; a blend whose ratios do not sum to ten thousand is rejected
    at production time with `ERR_INVALID_RATIO`."

    Design: Corner/validations/corner_produce_invalid_ratio
    """
    ctx = setup_blend_ready_to_produce(api, bt_ratio=7000, sa_ratio=2000,  # sum 9000
                                       bt_lot_grams=500, sa_lot_grams=500,
                                       target_output_grams=100)
    resp = api.produce_batch(ctx["batch"]["id"], PROD)
    validate_error(resp, ApiErrorId.ERR_INVALID_RATIO.value)


def test_attach_duplicate_component_rejected(api):
    """PRD §3.1: "Attaching the same ingredient to a blend twice is rejected with
    `ERR_DUPLICATE_COMPONENT`."

    Design: Corner/validations/corner_blend_component_duplicate
    """
    bt = new_product(api, name="Black Tea Base", category="TEA", unit_price_cents_per_gram=4.0,
                     tare_default_grams=5)
    chai = new_product(api, name="Almond Chai Blend", category="TEA", kind="BLEND",
                       unit_price_cents_per_gram=7.2, tare_default_grams=5)
    new_blend_component(api, chai["id"], bt["id"], 5000)
    resp = api.create_blend_component(
        {"blend_product_id": chai["id"], "component_product_id": bt["id"],
         "weight_ratio_bps": 5000}, CATALOG)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMPONENT.value)
