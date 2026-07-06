"""Shop onboarding, the ACTIVE<->VACATION cycle, vacation-window overlap, and versioning."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    make_seller_headers,
    create_shop, get_shop,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ==========================================================================
# Difficulty / non_linear_state_machine / shop_vacation_cycle
# ==========================================================================
def test_shop_enters_and_returns_from_vacation(api):
    """PRD §3.1: "Enabling vacation is defined only from `ACTIVE`; it moves the shop to
    `VACATION`, sets `vacation_auto_reply` from the request when one is supplied, and
    increments the shop's `version`."
    PRD §3.1: "Returning from vacation is defined only from `VACATION`; it moves the shop
    back to `ACTIVE` and increments `version`."

    Design: Difficulty/non_linear_state_machine/shop_vacation_cycle
    """
    shop = create_shop()
    after_enable = validate_success(api.enable_vacation(shop["id"], make_seller_headers(shop["id"])))
    assert after_enable["status"] == "VACATION"
    after_return = validate_success(api.return_from_vacation(shop["id"], make_seller_headers(shop["id"])))
    assert after_return["status"] == "ACTIVE"


def test_shop_re_enters_vacation_after_returning(api):
    """PRD §3.1: "Enabling vacation is defined only from `ACTIVE`; it moves the shop to
    `VACATION`, sets `vacation_auto_reply` from the request when one is supplied, and
    increments the shop's `version`."
    PRD §3.1: "Returning from vacation is defined only from `VACATION`; it moves the shop
    back to `ACTIVE` and increments `version`."

    Design: Difficulty/non_linear_state_machine/shop_vacation_cycle
    """
    shop = create_shop()
    seller = make_seller_headers(shop["id"])
    validate_success(api.enable_vacation(shop["id"], seller))
    validate_success(api.return_from_vacation(shop["id"], seller))
    third = validate_success(api.enable_vacation(shop["id"], seller))
    assert third["status"] == "VACATION", "shop must cycle ACTIVE->VACATION->ACTIVE->VACATION"


# ==========================================================================
# Difficulty / resource_temporal_overlap / vacation_period_half_open_overlap
# ==========================================================================
def test_overlapping_vacation_period_rejected(api):
    """PRD §3.1: "Overlap is judged on half-open intervals running from the start
    inclusive to the end exclusive, so two windows that merely touch — where one's
    `ends_at` equals the next one's `starts_at` — are allowed, whereas any genuine
    overlap is rejected with `ERR_VACATION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vacation_period_half_open_overlap
    """
    shop = create_shop()
    seller = make_seller_headers(shop["id"])
    get_success_data(api.create_vacation_period(
        {"shop_id": shop["id"], "starts_at": "2026-04-01T00:00:00Z",
         "ends_at": "2026-04-10T00:00:00Z"}, seller))
    resp = api.create_vacation_period(
        {"shop_id": shop["id"], "starts_at": "2026-04-05T00:00:00Z",
         "ends_at": "2026-04-15T00:00:00Z"}, seller)
    validate_error(resp, ApiErrorId.ERR_VACATION_OVERLAP)


def test_adjacent_vacation_period_accepted(api):
    """PRD §3.1: "Overlap is judged on half-open intervals running from the start
    inclusive to the end exclusive, so two windows that merely touch — where one's
    `ends_at` equals the next one's `starts_at` — are allowed, whereas any genuine
    overlap is rejected with `ERR_VACATION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vacation_period_half_open_overlap
    """
    shop = create_shop()
    seller = make_seller_headers(shop["id"])
    get_success_data(api.create_vacation_period(
        {"shop_id": shop["id"], "starts_at": "2026-04-01T00:00:00Z",
         "ends_at": "2026-04-10T00:00:00Z"}, seller))
    accepted = validate_success(api.create_vacation_period(
        {"shop_id": shop["id"], "starts_at": "2026-04-10T00:00:00Z",
         "ends_at": "2026-04-20T00:00:00Z"}, seller), 201)
    assert accepted["status"] == "SCHEDULED"


# ==========================================================================
# Corner / entities / shop_creation_returns_all_fields
# ==========================================================================
def test_shop_creation_returns_defaults_and_active_status(api):
    """PRD §3.1: "A new shop begins life in `ACTIVE` status with `version` 1, and the
    returned `id` becomes the identity a `Seller` uses to act on that shop thereafter."
    PRD §3.1: "the `max_concurrent_production` capacity (defaulting to 3), an optional
    `announcement` banner, and an optional `vacation_auto_reply` message."

    Design: Corner/entities/shop_creation_returns_all_fields
    """
    resp = api.create_shop({"owner_seller_id": "seller_1", "name": "Handmade Co"}, ADMIN)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["currency"] == "USD"
    assert data["max_concurrent_production"] == 3


# ==========================================================================
# Corner / entities / shop_get_not_found
# ==========================================================================
def test_get_missing_shop_returns_not_found(api):
    """PRD §2.5: "a missing shop yields `ERR_SHOP_NOT_FOUND`, a missing shipping profile
    `ERR_SHIPPING_PROFILE_NOT_FOUND`, a missing material `ERR_MATERIAL_NOT_FOUND`, a
    missing listing `ERR_LISTING_NOT_FOUND`, a missing vacation period
    `ERR_VACATION_PERIOD_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing
    review `ERR_REVIEW_NOT_FOUND`, a missing case `ERR_CASE_NOT_FOUND`, and a missing
    payout `ERR_PAYOUT_NOT_FOUND` — each HTTP 404."

    Design: Corner/entities/shop_get_not_found
    """
    resp = api.get_shop(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SHOP_NOT_FOUND)


# ==========================================================================
# Corner / state_machines / return_from_vacation_when_active_returns_invalid_state
# ==========================================================================
def test_return_from_vacation_on_active_shop_returns_invalid_state(api):
    """PRD §3.1: "Either action attempted from a state where the transition is not
    defined is rejected with `ERR_INVALID_STATE` (HTTP 409), and either action is
    permitted only to the seller that owns the shop."

    Design: Corner/state_machines/return_from_vacation_when_active_returns_invalid_state
    """
    shop = create_shop()
    resp = api.return_from_vacation(shop["id"], make_seller_headers(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Corner / cross_cutting_complexity_layers / version_increments_on_shop_mutation
# ==========================================================================
def test_enable_vacation_increments_shop_version(api):
    """PRD §2.4: "The `version` field is an integer that starts at 1 on creation and
    increments by one on every mutation; it is the basis for optimistic concurrency
    control (§2.9)."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_shop_mutation
    """
    shop = create_shop()
    assert shop["version"] == 1
    after = validate_success(api.enable_vacation(shop["id"], make_seller_headers(shop["id"])))
    assert after["version"] == 2
