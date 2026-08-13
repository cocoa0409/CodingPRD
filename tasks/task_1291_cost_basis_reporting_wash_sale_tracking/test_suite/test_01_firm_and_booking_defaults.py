"""Firm/customer/account booking defaults, computed fields, envelope shape.

Covers queue-B `entities` section claims.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_tax_ops_headers, make_firm_admin_headers,
    make_firm, make_customer, make_account, make_security,
    create_firm_payload, create_customer_payload, create_account_payload,
    create_tax_lot_payload, assert_brokerage_firm, assert_customer, assert_account,
)

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
TAX_OPS = TEST_USERS["tax_ops_headers"]


def test_firm_creation_applies_system_defaults(api):
    """PRD §3.1: "The server stamps the firm with three regulatory defaults:
    `tax_year_open` starts at 2025, the earliest tax year whose books still
    accept new transactions; `wash_sale_window_days` starts at 30, the
    regulatory half-window, so the full inclusive wash-sale window spans
    sixty-one days; and `correction_deadline_days` starts at 1095".

    Design: Corner/entities/firm_creation_applies_system_defaults
    """
    resp = api.create_firm(create_firm_payload(legal_name="Default Firm"), FIRM_ADMIN)
    firm = validate_success(resp, 201)
    assert_brokerage_firm(firm)
    assert firm["tax_year_open"] == 2025
    assert firm["wash_sale_window_days"] == 30
    assert firm["correction_deadline_days"] == 1095


def test_account_creation_defaults_disposal_method_fifo(api):
    """PRD §3.1: "an optional `default_disposal_method` of `FIFO`, `LIFO`,
    `HIFO`, or `SPECIFIC_ID` that defaults to `FIFO`."
    PRD §3.1: "A new account starts `OPEN`."

    Design: Corner/entities/account_creation_defaults_disposal_method_fifo
    """
    firm = make_firm("Firm D1")
    cust = make_customer(firm["id"], tin="TIN-ENT-1", display_name="Defaults")
    payload = {"account_number": "A1", "account_type": "TAXABLE"}
    resp = api.create_account(firm["id"], cust["id"], payload, TAX_OPS)
    acct = validate_success(resp, 201)
    assert_account(acct)
    assert acct["default_disposal_method"] == "FIFO"
    assert acct["status"] == "OPEN"


def test_tax_lot_computed_fields_initialized_on_create(api):
    """PRD §3.2: "Booking initializes the lot's computed face:
    `quantity_remaining` starts equal to `quantity`, `adjusted_cost_basis_cents`
    starts equal to `original_cost_basis_cents`, `wash_sale_taint_basis_cents`
    starts at zero, `lot_status` opens at `OPEN`, and `covered_status` is
    computed immediately."

    Design: Corner/entities/tax_lot_computed_fields_initialized_on_create
    """
    firm = make_firm("Firm D2")
    cust = make_customer(firm["id"], tin="TIN-ENT-2", display_name="Computed")
    acct = make_account(firm["id"], cust["id"])
    sec = make_security(firm["id"], cusip="121212121", ticker="CMP")
    resp = api.create_tax_lot(
        firm["id"], acct["id"],
        create_tax_lot_payload(security_id=sec["id"], acquisition_date="2025-01-05T00:00:00Z",
                               quantity=25, original_cost_basis_cents=25000),
        TAX_OPS,
    )
    lot = validate_success(resp, 201)
    assert lot["quantity_remaining"] == 25
    assert lot["adjusted_cost_basis_cents"] == 25000
    assert lot["covered_status"] == "COVERED"
    assert lot["lot_status"] == "OPEN"


def test_get_nonexistent_lot_returns_not_found(api):
    """PRD §2.6: "Every path-template identifier must resolve within the firm
    scope, validated left to right as described in §2.5, or the request fails
    with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_lot_returns_not_found
    """
    firm = make_firm("Firm D3")
    resp = api.get_tax_lot(firm["id"], NON_EXISTENT_UUID, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_customer_wash_sale_scope_key_equals_tin(api):
    """PRD §3.1: "the server derives its `wash_sale_scope_key` as the
    customer's own `taxpayer_tin`".

    Design: Corner/entities/customer_wash_sale_scope_key_equals_tin
    """
    firm = make_firm("Firm D4")
    resp = api.create_customer(
        firm["id"], create_customer_payload(taxpayer_tin="TIN-SCOPE-9", display_name="Scope"), FIRM_ADMIN
    )
    cust = validate_success(resp, 201)
    assert_customer(cust)
    assert cust["wash_sale_scope_key"] == "TIN-SCOPE-9"


def test_gift_lot_missing_basis_detail_rejected(api):
    """PRD §3.2: "A gift or inheritance lot booked without its required detail
    is rejected with `ERR_INCOMPLETE_LOT_BASIS_DETAIL` (HTTP 422)."

    Design: Corner/entities/gift_lot_missing_basis_detail_rejected
    """
    firm = make_firm("Firm D5")
    cust = make_customer(firm["id"], tin="TIN-ENT-5", display_name="Gift")
    acct = make_account(firm["id"], cust["id"])
    sec = make_security(firm["id"], cusip="131313131", ticker="GFT")
    payload = create_tax_lot_payload(security_id=sec["id"], quantity=10,
                                     original_cost_basis_cents=10000, acquisition_kind="GIFT")
    resp = api.create_tax_lot(firm["id"], acct["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INCOMPLETE_LOT_BASIS_DETAIL)


def test_inheritance_lot_missing_fmv_rejected(api):
    """PRD §3.2: "Booking an `INHERITANCE` lot requires
    `inherited_fmv_cents_at_death`, the fair market value at the date of
    death. A gift or inheritance lot booked without its required detail is
    rejected with `ERR_INCOMPLETE_LOT_BASIS_DETAIL` (HTTP 422)."

    Design: Corner/entities/inheritance_lot_missing_fmv_rejected
    """
    firm = make_firm("Firm D6")
    cust = make_customer(firm["id"], tin="TIN-ENT-6", display_name="Inherit")
    acct = make_account(firm["id"], cust["id"])
    sec = make_security(firm["id"], cusip="141414141", ticker="INH")
    payload = create_tax_lot_payload(security_id=sec["id"], quantity=10,
                                     original_cost_basis_cents=10000, acquisition_kind="INHERITANCE")
    resp = api.create_tax_lot(firm["id"], acct["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INCOMPLETE_LOT_BASIS_DETAIL)


def test_list_pagination_envelope_fields_present(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope."

    Design: Corner/entities/list_pagination_envelope_fields_present
    """
    firm = make_firm("Firm D7")
    make_customer(firm["id"], tin="TIN-ENT-7", display_name="Page")
    resp = api.list_customers(firm["id"], TAX_OPS, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(data) == 1
