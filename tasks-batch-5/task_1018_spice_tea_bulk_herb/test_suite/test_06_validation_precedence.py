"""Error-precedence conflicts (state>fiscal, safety>temporal) and cross-entity state gates."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_product, new_account, new_order, new_line, do_price,
    setup_confirmed_order, setup_priced_order, clock_set, account_version,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PROD = TEST_USERS["production_headers"]
SALES = TEST_USERS["sales_headers"]
CATALOG = TEST_USERS["catalog_headers"]


# ---- priority_pair_validation_conflict / state_beats_fiscal_on_confirm ----

def _draft_over_limit(api):
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=100)  # tiny limit
    order = new_order(api, account["id"])
    new_line(api, order["id"], cham["id"], 100)  # provisional would be 250 > 100
    return account, order


def test_confirm_draft_order_reports_state_over_fiscal(api):
    """PRD §2.10: "then whether the target resource is in a state that permits the requested
    transition (`ERR_INVALID_STATE`, 409). After state comes the optimistic-concurrency
    check on order confirmation (`ERR_STALE_VERSION`, 412), then the allergen-acknowledgement
    gate at packing (`ERR_ALLERGEN_LABEL_REQUIRED`, 409), then temporal and window checks
    (`ERR_LOT_EXPIRED`, `ERR_LINE_WINDOW_CONFLICT`, `ERR_STATION_BUFFER_CONFLICT`,
    `ERR_WINDOW_INVALID`, all 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    account, order = _draft_over_limit(api)
    resp = api.confirm_order(order["id"],
                             {"expected_wholesale_account_version": account["version"]}, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_rejected_draft_confirm_leaves_order_in_draft(api):
    """PRD §3.6: "Confirming a priced order advances it `PRICED → CONFIRMED` and is the
    point at which credit is committed."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    account, order = _draft_over_limit(api)
    api.confirm_order(order["id"],
                      {"expected_wholesale_account_version": account["version"]}, SALES)
    after = validate_success(api.get_order(order["id"], SALES))
    assert after["fulfillment_status"] == "DRAFT", after["fulfillment_status"]


# ---- priority_pair_validation_conflict / safety_beats_temporal_on_pack ----

def _allergen_expired_confirmed(api):
    ctx = setup_confirmed_order(
        api, name="Sweet Almond Bits", category="HERB", unit_price_cents_per_gram=5.0,
        allergen_tags=["TREE_NUTS"], requested_grams=30, allergen_ack=False,
        lot_grams=100, lot_best_by="2026-08-01T00:00:00Z", clock="2026-06-15T00:00:00Z",
    )
    clock_set(api, "2026-08-01T00:00:00Z")  # lot now EXPIRED at pack time
    return ctx


def test_pack_reports_allergen_over_expiry(api):
    """PRD §3.7: "Before allocating, the allergen gate applies: if any line being packed
    carries a non-empty effective allergen set, the order's `allergen_ack` must be true, or
    packing is rejected with `ERR_ALLERGEN_LABEL_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_pack
    """
    ctx = _allergen_expired_confirmed(api)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 40, "tare_grams": 5}]
    resp = api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, PROD)
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_LABEL_REQUIRED.value)


def test_rejected_pack_leaves_order_confirmed(api):
    """PRD §2.10: "then the allergen-acknowledgement gate at packing
    (`ERR_ALLERGEN_LABEL_REQUIRED`, 409), then temporal and window checks (`ERR_LOT_EXPIRED`,
    `ERR_LINE_WINDOW_CONFLICT`, `ERR_STATION_BUFFER_CONFLICT`, `ERR_WINDOW_INVALID`, all 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_pack
    """
    ctx = _allergen_expired_confirmed(api)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 40, "tare_grams": 5}]
    api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, PROD)
    after = validate_success(api.get_order(ctx["order"]["id"], SALES))
    assert after["fulfillment_status"] == "CONFIRMED", after["fulfillment_status"]


# ---- cross_entity_state_dependency / price_requires_product_active ----

def _draft_with_discontinued_product(api):
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api)
    order = new_order(api, account["id"])
    new_line(api, order["id"], cham["id"], 100)
    validate_success(api.discontinue_product(cham["id"], CATALOG))
    return order


def test_price_order_with_discontinued_product_rejected(api):
    """PRD §3.6: "Pricing an order advances it `DRAFT → PRICED` and requires at least one
    line, with every line's product still `ACTIVE`; a line referencing a discontinued
    product blocks pricing with `ERR_PRODUCT_DISCONTINUED`."

    Design: Difficulty/cross_entity_state_dependency/price_requires_product_active
    """
    order = _draft_with_discontinued_product(api)
    resp = api.price_order(order["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


def test_rejected_price_leaves_order_in_draft(api):
    """PRD §3.1: "A discontinued product can no longer be added to a draft order line, but
    any existing lines that already reference it are unaffected."

    Design: Difficulty/cross_entity_state_dependency/price_requires_product_active
    """
    order = _draft_with_discontinued_product(api)
    api.price_order(order["id"], SALES)
    after = validate_success(api.get_order(order["id"], SALES))
    assert after["fulfillment_status"] == "DRAFT", after["fulfillment_status"]


# ---- cross_entity_state_dependency / confirm_requires_account_active ----

def _priced_then_suspended(api):
    ctx = setup_priced_order(api)
    validate_success(api.suspend_account(ctx["account"]["id"], SALES))  # version advances
    return ctx


def test_confirm_against_suspended_account_rejected(api):
    """PRD §3.6: "Confirmation requires that the account be `ACTIVE` (else
    `ERR_ACCOUNT_SUSPENDED`), that the supplied `expected_wholesale_account_version` match
    the account's current `version` (else `ERR_STALE_VERSION`, per §2.8), and that the
    order's `provisional_total_cents` not exceed the account's `available_credit_cents`
    (else `ERR_CREDIT_LIMIT_EXCEEDED` at HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_account_active
    """
    ctx = _priced_then_suspended(api)
    v = account_version(api, ctx["account"]["id"])  # re-read so OCC passes; suspended-check fires
    resp = api.confirm_order(ctx["order"]["id"],
                             {"expected_wholesale_account_version": v}, SALES)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)


def test_rejected_confirm_leaves_order_priced(api):
    """PRD §3.5: "A `SalesAgent` suspending an account moves it `ACTIVE → SUSPENDED`, after
    which any attempt to confirm a new order against it is blocked with
    `ERR_ACCOUNT_SUSPENDED`; reinstating it moves it `SUSPENDED → ACTIVE` with no further
    effect."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_account_active
    """
    ctx = _priced_then_suspended(api)
    v = account_version(api, ctx["account"]["id"])
    api.confirm_order(ctx["order"]["id"], {"expected_wholesale_account_version": v}, SALES)
    after = validate_success(api.get_order(ctx["order"]["id"], SALES))
    assert after["fulfillment_status"] == "PRICED", after["fulfillment_status"]
