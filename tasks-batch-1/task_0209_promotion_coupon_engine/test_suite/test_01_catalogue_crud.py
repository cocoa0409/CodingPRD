"""Catalogue CRUD, input validation, uniqueness, and RBAC.

Translates queue B (Corner) instances from sections: entities, validations,
errors, and rbac.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_customer,
    assert_promotion,
    assert_blackout_window,
    create_customer_payload,
    create_promotion_payload,
    create_segment_payload,
    create_coupon_payload,
    create_blackout_payload,
    TEST_USERS,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import create_promotion, create_segment

ADMIN = TEST_USERS["merchant_admin_headers"]
SHOPPER = TEST_USERS["shopper_headers"]


# ─────────────────────────────────────────── entities ──────────────────────
def test_create_customer_returns_201_with_defaults(api):
    """PRD §3.1: "A new customer starts with an `order_count` of zero and a
    `lifetime_discount_cents` of zero, both of which the engine maintains
    thereafter from the customer's checkout history."
    PRD §2.4: "the `version` field is an integer that begins at its initial value
    and increments by one on every mutation"

    Design: Corner/entities/create_customer_returns_201_with_fields
    """
    res = api.create_customer(create_customer_payload(email="new-cust@example.com",
                                                      display_name="New"), SHOPPER)
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["order_count"] == 0
    assert cust["lifetime_discount_cents"] == 0
    assert cust["version"] == 1


def test_get_promotion_not_found(api):
    """PRD §2.9: "the existence of every resource named in the path is verified
    left to right, with the first missing identifier producing `ERR_NOT_FOUND`."

    Design: Corner/entities/get_promotion_not_found_returns_404
    """
    res = api.get_promotion(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_promotion_missing_promo_type(api):
    """PRD §2.9: "required fields and their shapes are validated, yielding
    `ERR_INVALID_REQUEST`."
    PRD §3.2: "Every promotion is created with a `name`, a `promo_type`, a
    `stacking_class`, and an active window bounded by `active_from` (inclusive)
    and `active_until` (exclusive)"

    Design: Corner/entities/create_promotion_missing_required_returns_invalid_request
    """
    payload = {
        "name": "NoType",
        "stacking_class": "STACKABLE",
        "active_from": "2026-06-01T00:00:00Z",
        "active_until": "2026-07-01T00:00:00Z",
    }
    res = api.create_promotion(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_promotion_invalid_enum(api):
    """PRD §3.2: "The `promo_type` is one of `PERCENT_OFF`, `BOGO`, or
    `THRESHOLD`, and each type demands its own configuration."
    PRD §2.9: "required fields and their shapes are validated, yielding
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_promotion_invalid_enum_returns_invalid_request
    """
    payload = {
        "name": "BadEnum",
        "promo_type": "WEEKLY",
        "stacking_class": "STACKABLE",
        "active_from": "2026-06-01T00:00:00Z",
        "active_until": "2026-07-01T00:00:00Z",
    }
    res = api.create_promotion(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_eligibility_mode_defaults_to_all(api):
    """PRD §3.2: "Who may use the promotion is governed by `eligibility_mode`,
    which defaults to `ALL` and may instead be `SEGMENT` or `FIRST_ORDER`."

    Design: Corner/entities/eligibility_mode_defaults_to_all
    """
    payload = create_promotion_payload("PERCENT_OFF", name="DefElig", percent_off=0.10)
    res = api.create_promotion(payload, ADMIN)
    promo = validate_success(res, 201)
    assert promo["eligibility_mode"] == "ALL"


def test_blackout_window_immutable_no_version(api):
    """PRD §2.4: "Two record types are immutable configuration and therefore
    carry only `id` and `created_at` — they have no `updated_at` and no
    `version`. A `BlackoutWindow` is one such record"

    Design: Corner/entities/blackout_window_immutable_no_version
    """
    promo = create_promotion("PERCENT_OFF", name="BWImm", percent_off=0.10)
    res = api.create_blackout(promo["id"],
                              create_blackout_payload("2026-06-10T00:00:00Z",
                                                      "2026-06-20T00:00:00Z", reason="freeze"),
                              ADMIN)
    bw = validate_success(res, 201)
    assert_blackout_window(bw)
    assert "version" not in bw, "BlackoutWindow must not carry a version field"
    assert "updated_at" not in bw, "BlackoutWindow must not carry an updated_at field"


def test_coupon_requires_existing_parent_promotion(api):
    """PRD §2.10: "When a path names more than one resource, the engine validates
    each identifier from left to right and returns `ERR_NOT_FOUND` for the first
    one that does not resolve, before considering any deeper identifier or any
    body rule."

    Design: Corner/entities/coupon_requires_existing_parent_promotion
    """
    res = api.create_coupon(NON_EXISTENT_UUID,
                            create_coupon_payload(code="ORPHAN", use_mode="SINGLE_USE"), ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_promotions_paginated_envelope(api):
    """PRD §2.3: "The `meta` object of every list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_promotions_paginated_envelope
    """
    create_promotion("PERCENT_OFF", name="ListP", percent_off=0.10)
    res = api.list_promotions(ADMIN)
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_duplicate_coupon_code(api):
    """PRD §3.4: "A coupon is created with a `code` — unique on a case-insensitive
    basis across all coupons, with collisions rejected as `ERR_DUPLICATE`"

    Design: Corner/entities/duplicate_coupon_code_returns_duplicate
    """
    promo = create_promotion("PERCENT_OFF", name="DupP", percent_off=0.10)
    get_success_data(api.create_coupon(promo["id"],
                     create_coupon_payload(code="DUP", use_mode="SINGLE_USE"), ADMIN))
    res = api.create_coupon(promo["id"],
                            create_coupon_payload(code="dup", use_mode="SINGLE_USE"), ADMIN)
    validate_error(res, "ERR_DUPLICATE", expected_status=409)


# ───────────────────────────────────────── validations ─────────────────────
def test_invalid_window_active_until_before_from(api):
    """PRD §3.2: "the window is rejected with `ERR_INVALID_WINDOW` unless
    `active_until` is strictly later than `active_from`."

    Design: Corner/validations/invalid_window_active_until_before_from
    """
    payload = create_promotion_payload("PERCENT_OFF", name="BadWin", percent_off=0.10,
                                       active_from="2026-07-01T00:00:00Z",
                                       active_until="2026-06-01T00:00:00Z")
    res = api.create_promotion(payload, ADMIN)
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=422)


def test_activate_percent_off_without_percent(api):
    """PRD §3.2: "Activation enforces three preconditions in turn: the
    type-specific configuration must be present for the declared `promo_type`
    (a `PERCENT_OFF` promotion needs `percent_off`, a `BOGO` promotion needs
    `bogo_sku`, a `THRESHOLD` promotion needs `threshold_tiers`) and, when the
    mode is `SEGMENT`, `eligible_segment_id` must reference an existing segment —
    any failure here yields `ERR_PROMO_CONFIG_INVALID`"

    Design: Corner/validations/activate_percent_off_without_percent_returns_config_invalid
    """
    payload = {
        "name": "NoPct",
        "promo_type": "PERCENT_OFF",
        "stacking_class": "STACKABLE",
        "active_from": "2026-06-01T00:00:00Z",
        "active_until": "2026-07-01T00:00:00Z",
    }
    promo = validate_success(api.create_promotion(payload, ADMIN), 201)
    res = api.activate_promotion(promo["id"], ADMIN)
    validate_error(res, "ERR_PROMO_CONFIG_INVALID", expected_status=422)


# ─────────────────────────────────────────── errors ────────────────────────
def test_blackout_invalid_window(api):
    """PRD §3.3: "Each window names the promotion it suppresses, an inclusive
    `starts_at`, an exclusive `ends_at` that must be strictly later than
    `starts_at` (else `ERR_INVALID_WINDOW`)"

    Design: Corner/errors/error_invalid_window_blackout
    """
    promo = create_promotion("PERCENT_OFF", name="BWbad", percent_off=0.10)
    res = api.create_blackout(promo["id"],
                              create_blackout_payload("2026-06-20T00:00:00Z",
                                                      "2026-06-10T00:00:00Z", reason="bad"),
                              ADMIN)
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=422)


def test_duplicate_segment_code(api):
    """PRD §3.1: "A `MerchantAdmin` groups customers using a `Segment`, created
    with a unique case-insensitive `code` and a human-readable `name`; a
    duplicate code is rejected with `ERR_DUPLICATE`."

    Design: Corner/errors/error_duplicate_segment_code
    """
    create_segment(code="VIP", name="VIPs")
    res = api.create_segment(create_segment_payload(code="VIP", name="VIPs again"), ADMIN)
    validate_error(res, "ERR_DUPLICATE", expected_status=409)


# ──────────────────────────────────────────── rbac ─────────────────────────
def test_shopper_cannot_create_promotion(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the
    requested operation is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4 endpoint table: POST `/promotions` is authorized for MerchantAdmin only.

    Design: Corner/rbac/shopper_cannot_create_promotion
    """
    payload = create_promotion_payload("PERCENT_OFF", name="Sneaky", percent_off=0.10)
    res = api.create_promotion(payload, SHOPPER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_shopper_cannot_set_clock(api):
    """PRD §2.8: "The `PlatformOperator` is the only role that may move this
    clock."
    PRD §2.1: "A request whose role is valid but not permitted for the requested
    operation is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/shopper_cannot_set_clock
    """
    res = api.set_clock({"now_utc": "2026-06-15T00:00:00Z"}, SHOPPER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_unauthenticated_missing_role_header(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role`
    that is not one of these three, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_missing_role_header
    """
    res = api.list_promotions(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
