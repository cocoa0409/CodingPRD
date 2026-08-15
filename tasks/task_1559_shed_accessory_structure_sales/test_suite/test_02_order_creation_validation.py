"""Order creation validation, initial state, not-found, and the ordered configuration
rules (PRD §2.8, §3.2)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId,
    setup_book, create_draft_order, create_order_payload,
    create_jurisdiction_payload, create_customer_payload,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]


def test_get_order_not_found(api):
    """PRD §2.8: "**Existence** — path identifiers are validated left to right, then body
    foreign keys (`customer_id`, `model_id`, `jurisdiction_id`, `order_id`) must resolve
    to existing records (`ERR_NOT_FOUND`)."

    Design: Corner/entities/order_get_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, SALES)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_order_missing_model_id(api):
    """PRD §2.8: "**Request shape** — required fields present, value types correct, enum
    members valid, and conditional requirements satisfied (`ERR_INVALID_REQUEST`)."
    PRD §3.2: "A `SalesRep` opens a sale by creating an order that references a
    `customer_id`, a `model_id`, and the governing `jurisdiction_id`"

    Design: Corner/entities/order_create_missing_required_model_id
    """
    jur = get_success_data(api.create_jurisdiction(create_jurisdiction_payload(), PERMIT))
    cust = get_success_data(api.create_customer(create_customer_payload(), SALES))
    payload = create_order_payload(cust["id"], "unused", jur["id"])
    del payload["model_id"]
    res = api.create_order(payload, SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_create_order_invalid_enum(api):
    """PRD §2.8: "**Request shape** — required fields present, value types correct, enum
    members valid, and conditional requirements satisfied (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/order_create_invalid_enum_returns_invalid_request
    """
    jur, model, cust = setup_book()
    payload = create_order_payload(
        cust["id"], model["id"], jur["id"], delivery_mode="HELICOPTER",
    )
    res = api.create_order(payload, SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_order_initial_state_draft(api):
    """PRD §3.2: "A new order starts in `DRAFT` with `structure_state` set to
    `NOT_INSTALLED`."
    PRD §2.4: "`version`, an integer starting at 1 that increments by exactly one on
    every mutation, including system-driven state transitions."

    Design: Corner/state_machines/order_initial_state_draft
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    assert order["status"] == "DRAFT"
    assert order["version"] == 1


def test_anchor_required_rejected(api):
    """PRD §3.2: "first, when the governing jurisdiction's `anchoring_required` is true,
    an `anchor_type` of `NONE` is rejected with `ERR_ANCHOR_REQUIRED`"

    Design: Corner/validations/anchor_required_direct_rejected
    """
    jur, model, cust = setup_book()
    payload = create_order_payload(
        cust["id"], model["id"], jur["id"], anchor_type="NONE",
    )
    res = api.create_order(payload, SALES)
    validate_error(res, ApiErrorId.ERR_ANCHOR_REQUIRED, expected_status=422)
    # Rejected creation persists nothing for this customer.
    data, meta = validate_paginated(
        api.list_orders(SALES, params={"customer_id": cust["id"]})
    )
    assert meta["total_count"] == 0


def test_config_out_of_bounds_rejected(api):
    """PRD §3.2: "second, dimensions outside the model's bounds are rejected with
    `ERR_CONFIG_OUT_OF_BOUNDS`"

    Design: Corner/validations/config_out_of_bounds_rejected
    """
    jur, model, cust = setup_book()
    payload = create_order_payload(
        cust["id"], model["id"], jur["id"], width_ft=20,
    )
    res = api.create_order(payload, SALES)
    validate_error(res, ApiErrorId.ERR_CONFIG_OUT_OF_BOUNDS, expected_status=422)


def test_delivery_mode_unsupported_rejected(api):
    """PRD §3.2: "third, a `delivery_mode` absent from the model's supported list is
    rejected with `ERR_DELIVERY_MODE_UNSUPPORTED`."

    Design: Corner/validations/delivery_mode_unsupported_rejected
    """
    jur, model, cust = setup_book(
        model_overrides={
            "name": "LoftBarn XL",
            "sku": "LB-99",
            "min_width_ft": 12,
            "max_width_ft": 16,
            "min_depth_ft": 12,
            "max_depth_ft": 24,
            "wall_height_ft": 10,
            "supported_delivery_modes": ["ON_SITE_BUILD"],
            "base_price_cents": 500000,
            "overage_rate_tier1_cents": 1800,
            "overage_rate_tier2_cents": 2200,
        }
    )
    payload = create_order_payload(
        cust["id"], model["id"], jur["id"],
        width_ft=12, depth_ft=12, delivery_mode="PRE_BUILT",
    )
    res = api.create_order(payload, SALES)
    validate_error(res, ApiErrorId.ERR_DELIVERY_MODE_UNSUPPORTED, expected_status=422)


class TestAmendRuleOrdering:
    def test_anchor_safety_reported_over_bounds(self, api):
        """PRD §3.2: "Three configuration rules are enforced on both creation and
        amendment, evaluated in this order: first, when the governing jurisdiction's
        `anchoring_required` is true, an `anchor_type` of `NONE` is rejected with
        `ERR_ANCHOR_REQUIRED`; second, dimensions outside the model's bounds are rejected
        with `ERR_CONFIG_OUT_OF_BOUNDS`; third, a `delivery_mode` absent from the model's
        supported list is rejected with `ERR_DELIVERY_MODE_UNSUPPORTED`."

        Design: Difficulty/priority_pair_validation_conflict/amend_anchor_safety_beats_config_bounds
        """
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"])
        res = api.amend_order(
            order["id"],
            {"expected_order_version": order["version"], "anchor_type": "NONE",
             "width_ft": 20},
            SALES,
        )
        validate_error(res, ApiErrorId.ERR_ANCHOR_REQUIRED, expected_status=422)

    def test_rejected_amend_applies_nothing(self, api):
        """PRD §3.2: "Three configuration rules are enforced on both creation and
        amendment, evaluated in this order: first, when the governing jurisdiction's
        `anchoring_required` is true, an `anchor_type` of `NONE` is rejected with
        `ERR_ANCHOR_REQUIRED`; second, dimensions outside the model's bounds are rejected
        with `ERR_CONFIG_OUT_OF_BOUNDS`; third, a `delivery_mode` absent from the model's
        supported list is rejected with `ERR_DELIVERY_MODE_UNSUPPORTED`."

        Design: Difficulty/priority_pair_validation_conflict/amend_anchor_safety_beats_config_bounds
        """
        jur, model, cust = setup_book()
        order = create_draft_order(cust["id"], model["id"], jur["id"])
        res = api.amend_order(
            order["id"],
            {"expected_order_version": order["version"], "anchor_type": "NONE",
             "width_ft": 20},
            SALES,
        )
        validate_error(res, ApiErrorId.ERR_ANCHOR_REQUIRED)
        refreshed = validate_success(api.get_order(order["id"], SALES), 200)
        assert refreshed["width_ft"] == 10
        assert refreshed["anchor_type"] == "AUGER_STRAP"
        assert refreshed["version"] == order["version"], "rejected amend must not bump version"
        assert refreshed["quoted_total_cents"] == order["quoted_total_cents"]
