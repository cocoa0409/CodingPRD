"""Order lifecycle transitions, terminal lockdown, and the practice credit ledger."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_practice,
    create_product,
    create_order_payload,
    create_and_submit_order,
    create_and_deliver_order,
    make_practice_manager_headers,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _credit_available(api, practice_id):
    return validate_success(api.get_practice(practice_id, ADMIN), 200)["credit_available_cents"]


def test_order_deliver_from_draft_rejected(api):
    """PRD §3.3: "Delivery is the warehouse's confirmation, performed by a
    `DistributionAdmin`, and moves `SUBMITTED` → `DELIVERED`."
    PRD §2.8: "State legality comes fifth on all action endpoints: the requested
    transition must exist from the resource's current state, terminal states reject every
    transition, and violations yield `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/order_deliver_from_draft_rejected
    """
    practice = create_practice(name="P D", credit_limit_cents=1000000)
    product = create_product(sku="C-8", name="Cups", unit_price_cents=500)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    res = api.deliver_order(order["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"
    assert after.get("delivered_at") is None


def test_order_cancel_from_delivered_rejected_terminal(api):
    """PRD §3.3: "`CANCELLED` is terminal, and no order may be cancelled once delivered."
    and "Cancelling a `SUBMITTED` order additionally compensates the reservation: the
    order's `total_cents` is added back to the practice's `credit_available_cents`" — the
    compensation must therefore NOT fire when the cancel itself is rejected.

    Design: Corner/state_machines/order_cancel_from_delivered_rejected_terminal
    """
    practice = create_practice(name="P T", credit_limit_cents=100000)
    product = create_product(sku="C-10", name="Cups", unit_price_cents=1000)
    order = create_and_deliver_order(
        practice["id"], [{"product_id": product["id"], "quantity": 1}]
    )
    assert order["status"] == "DELIVERED"
    assert _credit_available(api, practice["id"]) == 99000

    res = api.cancel_order(order["id"], SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert _credit_available(api, practice["id"]) == 99000, (
        "Rejected cancel must not touch the credit reservation"
    )


def test_credit_submit_cancel_conservation(api):
    """PRD §3.3: "A successful submission reserves credit by reducing
    `credit_available_cents` by the order's `total_cents`, stamps `submitted_at` with the
    logical now, and increments the practice's `version` by one." and "Cancelling a
    `SUBMITTED` order additionally compensates the reservation: the order's `total_cents`
    is added back to the practice's `credit_available_cents`, and the practice's `version`
    increments by one."

    Design: Difficulty/compensating_invariant/credit_submit_cancel_conservation
    """
    practice = create_practice(name="P Inv", credit_limit_cents=100000)
    product = create_product(sku="C-5", name="Kit", unit_price_cents=60000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    assert _credit_available(api, practice["id"]) == 100000

    submitted = validate_success(api.submit_order(order["id"], SALES), 200)
    assert submitted["status"] == "SUBMITTED"
    assert _credit_available(api, practice["id"]) == 40000, "Submit reserves total_cents"

    cancelled = validate_success(api.cancel_order(order["id"], SALES), 200)
    assert cancelled["status"] == "CANCELLED"
    assert _credit_available(api, practice["id"]) == 100000, (
        "Cancel restores the reservation exactly — zero drift"
    )


def test_credit_untouched_by_draft_cancel(api):
    """PRD §3.3: "Cancelling a `DRAFT` order simply moves it to `CANCELLED` and refreshes
    `updated_at`."

    Design: Difficulty/compensating_invariant/credit_submit_cancel_conservation
    """
    practice = create_practice(name="P DC", credit_limit_cents=100000)
    product = create_product(sku="C-5D", name="Kit", unit_price_cents=60000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    cancelled = validate_success(api.cancel_order(order["id"], SALES), 200)
    assert cancelled["status"] == "CANCELLED"
    assert _credit_available(api, practice["id"]) == 100000, (
        "A DRAFT order holds no reservation, so cancel changes nothing"
    )


def test_credit_limit_exact_equality_passes(api):
    """PRD §3.3: "the order's `total_cents` must not exceed the practice's
    `credit_available_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`." — equality does not
    exceed, so a total exactly equal to available credit submits.

    Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_passes
    """
    practice = create_practice(name="PA", credit_limit_cents=150000)
    product = create_product(sku="CA-1", name="CA", unit_price_cents=150000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    assert order["total_cents"] == 150000
    submitted = validate_success(api.submit_order(order["id"], SALES), 200)
    assert submitted["status"] == "SUBMITTED"
    assert _credit_available(api, practice["id"]) == 0


def test_credit_limit_one_cent_over_fails(api):
    """PRD §3.3: "the order's `total_cents` must not exceed the practice's
    `credit_available_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_passes
    """
    practice = create_practice(name="PB", credit_limit_cents=150000)
    product = create_product(sku="CB-1", name="CB", unit_price_cents=150001)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    assert order["total_cents"] == 150001
    res = api.submit_order(order["id"], SALES)
    validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"
    assert _credit_available(api, practice["id"]) == 150000


def test_submit_cancelled_order_state_error_precedes_credit(api):
    """PRD §2.8: "State legality comes fifth on all action endpoints: the requested
    transition must exist from the resource's current state, terminal states reject every
    transition, and violations yield `ERR_INVALID_STATE` (409)." and "Only after all six
    generic rungs pass do the domain rules run — safety gates, business constraints,
    temporal windows, referential checks, and fiscal limits".

    Design: Difficulty/priority_pair_validation_conflict/submit_state_error_precedes_credit_fiscal_error
    """
    practice = create_practice(name="P Prio", credit_limit_cents=100000)
    product = create_product(sku="C-7", name="Kit", unit_price_cents=75000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 2}]),
            SALES,
        ),
        201,
    )
    assert order["total_cents"] == 150000, "Total exceeds the 100000 credit line"
    validate_success(api.cancel_order(order["id"], SALES), 200)

    res = api.submit_order(order["id"], SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_submit_draft_order_credit_error_when_state_ok(api):
    """PRD §3.3: "the order's `total_cents` must not exceed the practice's
    `credit_available_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`." — with the state rung
    passing (order still DRAFT), the fiscal limit is the check that fires.

    Design: Difficulty/priority_pair_validation_conflict/submit_state_error_precedes_credit_fiscal_error
    """
    practice = create_practice(name="P Fisc", credit_limit_cents=100000)
    product = create_product(sku="C-7F", name="Kit", unit_price_cents=75000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 2}]),
            SALES,
        ),
        201,
    )
    res = api.submit_order(order["id"], SALES)
    validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_orders_list_filter_and_pagination_defaults(api):
    """PRD §3.3: "The order listing may be filtered by `practice_id`, `promotion_id`, and
    `kind`". PRD §2.3: "The `limit` parameter sets the maximum number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100.
    The `offset` parameter sets how many items to skip and defaults to 0."

    Design: Corner/endpoints/orders_list_filter_and_pagination_defaults
    """
    pa = create_practice(name="PA", credit_limit_cents=1000000)
    pb = create_practice(name="PB", credit_limit_cents=1000000)
    product = create_product(sku="C-21", name="Cups", unit_price_cents=500)
    for qty in (1, 2):
        validate_success(
            api.create_order(
                create_order_payload(pa["id"], [{"product_id": product["id"], "quantity": qty}]),
                SALES,
            ),
            201,
        )
    validate_success(
        api.create_order(
            create_order_payload(pb["id"], [{"product_id": product["id"], "quantity": 3}]),
            SALES,
        ),
        201,
    )

    res = api.list_orders(ADMIN, params={"practice_id": pa["id"]})
    data, meta = validate_paginated(res)
    assert res.json()["response_type"] == "array"
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2
    assert all(o["practice_id"] == pa["id"] for o in data), "PB's order must be excluded"


def test_practice_manager_cannot_touch_other_practice_order(api):
    """PRD §2.1: "ownership checks on any resource that references a Practice compare the
    resource's `practice_id` field to `X-User-ID`, so a practice manager may only touch
    resources belonging to their own practice".

    Design: Corner/validations/practice_manager_cannot_touch_other_practice_order
    """
    pa = create_practice(name="PA", credit_limit_cents=1000000)
    pb = create_practice(name="PB", credit_limit_cents=1000000)
    product = create_product(sku="C-14", name="Cups", unit_price_cents=500)
    order = validate_success(
        api.create_order(
            create_order_payload(pa["id"], [{"product_id": product["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    res = api.submit_order(order["id"], make_practice_manager_headers(pb["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"
