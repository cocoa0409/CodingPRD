"""Controlled-product compliance gates and startup-package rules on order creation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_practice,
    create_product,
    create_order_payload,
    set_clock,
    TEST_USERS,
    ApiErrorId,
)

SALES = TEST_USERS["sales_rep_headers"]


def test_regulated_license_safety_precedes_qty_constraint(api):
    """PRD §3.3: "creation applies its domain gates in a fixed order after the generic
    ladder of §2.8: first the regulated-license gate — any `REGULATED` line requires the
    practice's `regulated_license_expiry` to be present and not earlier than the logical
    now, else `ERR_REGULATED_LICENSE_MISSING`" and "then the regulated quantity cap — a
    `REGULATED` line's quantity may not exceed the product's `max_qty_per_order` when one
    is set, else `ERR_REGULATED_QTY_LIMIT`".

    Design: Difficulty/priority_pair_validation_conflict/regulated_license_safety_precedes_qty_constraint
    """
    practice = create_practice(name="P NoLic", credit_limit_cents=10000000)
    product = create_product(
        sku="RG-1", name="Amalgam", kind="REGULATED", unit_price_cents=1000, max_qty_per_order=2
    )
    res = api.create_order(
        create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 5}]),
        SALES,
    )
    # Quantity 5 > cap 2 also violates the quantity gate, but the license gate runs first.
    validate_error(res, ApiErrorId.ERR_REGULATED_LICENSE_MISSING)


def test_regulated_license_expired_also_blocked(api):
    """PRD §2.10: "A practice's `regulated_license_expiry` records the expiry of its
    regulated-items handling license; when it is null, or earlier than the logical now,
    the practice may not receive order lines whose product `kind` is `REGULATED`."

    Design: Difficulty/priority_pair_validation_conflict/regulated_license_safety_precedes_qty_constraint
    """
    practice = create_practice(
        name="P ExpLic",
        credit_limit_cents=10000000,
        regulated_license_expiry="2020-01-01T00:00:00Z",
    )
    product = create_product(
        sku="RG-4", name="Amalgam", kind="REGULATED", unit_price_cents=1000, max_qty_per_order=10
    )
    # Quantity within the cap: only the expired-license gate can fire.
    res = api.create_order(
        create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 5}]),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_REGULATED_LICENSE_MISSING)


def test_regulated_qty_limit_with_valid_license(api):
    """PRD §3.3: "then the regulated quantity cap — a `REGULATED` line's quantity may not
    exceed the product's `max_qty_per_order` when one is set, else
    `ERR_REGULATED_QTY_LIMIT`".

    Design: Corner/validations/regulated_qty_limit_with_valid_license
    """
    practice = create_practice(
        name="P Lic",
        credit_limit_cents=10000000,
        regulated_license_expiry="2030-01-01T00:00:00Z",
    )
    product = create_product(
        sku="RG-2", name="Amalgam", kind="REGULATED", unit_price_cents=1000, max_qty_per_order=2
    )
    res = api.create_order(
        create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 5}]),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_REGULATED_QTY_LIMIT)


def test_sterilization_gate_on_uncertified_practice(api):
    """PRD §3.3: "then sterilization certification — any line whose product requires a
    sterilization cycle demands a `sterilization_compliant` practice, else
    `ERR_STERILIZATION_NOT_CERTIFIED`".

    Design: Corner/validations/sterilization_gate_on_uncertified_practice
    """
    practice = create_practice(name="P Ster", credit_limit_cents=10000000)
    product = create_product(
        sku="ST-1", name="Surgical tips", unit_price_cents=2000, sterilization_cycle_required=True
    )
    res = api.create_order(
        create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_STERILIZATION_NOT_CERTIFIED)


def test_equipment_line_rejected_on_manual_order(api):
    """PRD §3.3: "then equipment orderability — `EQUIPMENT` lines are permitted only on
    `STARTUP` orders, else `ERR_EQUIPMENT_NOT_ORDERABLE`".

    Design: Corner/validations/equipment_line_rejected_on_manual_order
    """
    practice = create_practice(name="P EqL", credit_limit_cents=10000000)
    product = create_product(
        sku="EQ-16", name="Chair", kind="EQUIPMENT", unit_price_cents=500000, warranty_months=12
    )
    res = api.create_order(
        create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_EQUIPMENT_NOT_ORDERABLE)


def test_startup_window_expired_after_90_days(api):
    """PRD §3.3: "then the startup window — a `STARTUP` order is accepted only while the
    logical now is within ninety days of the practice's `created_at`, else
    `ERR_STARTUP_WINDOW_EXPIRED`".

    Design: Corner/validations/startup_window_expired_after_90_days
    """
    practice = create_practice(name="P St", credit_limit_cents=10000000)
    product = create_product(sku="C-15", name="Kit", unit_price_cents=1000)
    # Practice created at the default logical clock 2026-08-01; +91 days is outside.
    set_clock("2026-10-31T00:00:00Z")
    res = api.create_order(
        create_order_payload(
            practice["id"], [{"product_id": product["id"], "quantity": 1}], kind="STARTUP"
        ),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_STARTUP_WINDOW_EXPIRED)


def test_startup_package_one_per_practice(api):
    """PRD §3.3: "then the startup package limit — at most one non-`CANCELLED` `STARTUP`
    order may exist per practice, else `ERR_STARTUP_PACKAGE_LIMIT`".

    Design: Corner/validations/startup_package_one_per_practice
    """
    practice = create_practice(name="P S1", credit_limit_cents=10000000)
    product = create_product(sku="C-16", name="Kit", unit_price_cents=1000)
    first = api.create_order(
        create_order_payload(
            practice["id"], [{"product_id": product["id"], "quantity": 1}], kind="STARTUP"
        ),
        SALES,
    )
    validate_success(first, 201)
    res = api.create_order(
        create_order_payload(
            practice["id"], [{"product_id": product["id"], "quantity": 1}], kind="STARTUP"
        ),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_STARTUP_PACKAGE_LIMIT)
