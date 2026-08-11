"""Every declared not-found error, addressed through a syntactically valid unknown id."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    make_account_holder_headers,
    make_gift_purchaser_headers,
    make_registry_owner_headers,
    set_clock,
    validate_error,
)

OPS = TEST_USERS["ops_admin_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]

def test_an_unknown_account_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_account_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_account(UNKNOWN_UUID, make_account_holder_headers(UNKNOWN_UUID)), ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)

def test_an_unknown_child_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_child_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_child(UNKNOWN_UUID, make_account_holder_headers(UNKNOWN_UUID)), ApiErrorId.ERR_CHILD_NOT_FOUND.value, 404)

def test_an_unknown_allergen_flag_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_allergen_flag_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.delete_allergen_flag(UNKNOWN_UUID, SUPPORT), ApiErrorId.ERR_ALLERGEN_FLAG_NOT_FOUND.value, 404)

def test_an_unknown_plan_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_plan_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_plan(UNKNOWN_UUID, OPS), ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)

def test_an_unknown_sku_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_sku_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_sku(UNKNOWN_UUID, OPS), ApiErrorId.ERR_SKU_NOT_FOUND.value, 404)

def test_an_unknown_subscription_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_subscription_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_subscription(UNKNOWN_UUID, OPS), ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value, 404)

def test_an_unknown_cycle_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_cycle_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.allocate_cycle(UNKNOWN_UUID, OPS), ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)

def test_an_unknown_cycle_line_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_cycle_line_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.rescreen_cycle_line(UNKNOWN_UUID, OPS), ApiErrorId.ERR_CYCLE_LINE_NOT_FOUND.value, 404)

def test_an_unknown_resize_event_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_resize_event_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_resize_event(UNKNOWN_UUID, OPS), ApiErrorId.ERR_RESIZE_EVENT_NOT_FOUND.value, 404)

def test_an_unknown_skip_record_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_skip_record_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_skip_record(UNKNOWN_UUID, OPS), ApiErrorId.ERR_SKIP_RECORD_NOT_FOUND.value, 404)

def test_an_unknown_pause_record_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_pause_record_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.cancel_pause_record(UNKNOWN_UUID, make_account_holder_headers(UNKNOWN_UUID)), ApiErrorId.ERR_PAUSE_RECORD_NOT_FOUND.value, 404)

def test_an_unknown_registry_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_registry_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.open_registry(UNKNOWN_UUID, make_registry_owner_headers(UNKNOWN_UUID)), ApiErrorId.ERR_REGISTRY_NOT_FOUND.value, 404)

def test_an_unknown_registry_item_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_registry_item_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_registry_item(UNKNOWN_UUID, make_registry_owner_headers(UNKNOWN_UUID)), ApiErrorId.ERR_REGISTRY_ITEM_NOT_FOUND.value, 404)

def test_an_unknown_gift_order_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_gift_order_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.pay_gift_order(UNKNOWN_UUID, make_gift_purchaser_headers(UNKNOWN_UUID)), ApiErrorId.ERR_GIFT_ORDER_NOT_FOUND.value, 404)

def test_an_unknown_credit_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_credit_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.revoke_credit(UNKNOWN_UUID, SUPPORT), ApiErrorId.ERR_CREDIT_NOT_FOUND.value, 404)

def test_an_unknown_shipment_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_shipment_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.pick_shipment(UNKNOWN_UUID, OPS), ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value, 404)

def test_an_unknown_loyalty_account_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_loyalty_account_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.reevaluate_tier(UNKNOWN_UUID, OPS), ApiErrorId.ERR_LOYALTY_ACCOUNT_NOT_FOUND.value, 404)

def test_an_unknown_referral_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_referral_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.expire_referral(UNKNOWN_UUID, OPS), ApiErrorId.ERR_REFERRAL_NOT_FOUND.value, 404)

def test_an_unknown_refund_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_refund_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.approve_refund(UNKNOWN_UUID, SUPPORT), ApiErrorId.ERR_REFUND_NOT_FOUND.value, 404)

def test_an_unknown_substitution_event_is_not_found(api):
    """PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."
    PRD §2.10: "Path parameters are resolved strictly left to right, and the leftmost segment
    that fails to resolve decides the error."

    Design: Corner/errors/corner_substitution_event_not_found_returns_404
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    validate_error(api.get_substitution_event(UNKNOWN_UUID, OPS), ApiErrorId.ERR_SUBSTITUTION_EVENT_NOT_FOUND.value, 404)
