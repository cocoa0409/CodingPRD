"""Lot selection methods (FIFO/LIFO/HIFO/SPECIFIC_ID), per-share rounding,
gain preview semantics, and disposition-create validation ordering.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    setup_book, make_lot, make_disposition, settle, make_firm, make_customer,
    make_account, make_security, create_disposition_payload,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]


def _two_lot_book(tin, cusip, method):
    """One account holding lot1 10sh/10000 (2025-01-05) and lot2 10sh/12000
    (2025-02-05), plus a PENDING 15-share disposition for 22500."""
    s = setup_book(tin=tin, cusip=cusip, ticker="LS", method=method)
    lot1 = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                    acquisition_date="2025-01-05T00:00:00Z", quantity=10, basis=10000)
    lot2 = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                    acquisition_date="2025-02-05T00:00:00Z", quantity=10, basis=12000)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=15, proceeds=22500, method=method)
    return s, lot1, lot2, disp


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / lot_selection_preview_vs_settled_quantity_mutation
# ---------------------------------------------------------------------------

def test_preview_gain_is_read_only_provisional_estimate(api):
    """PRD §3.3: "The gain preview runs the same selection and pricing walk
    against current lot state but decrements nothing and persists nothing; it
    returns the would-be `realized_gain_cents` together with the `allocations`
    list."

    Design: Difficulty/dual_variant_calc/lot_selection_preview_vs_settled_quantity_mutation
    """
    s, lot1, lot2, disp = _two_lot_book("TIN-LS-1", "222222222", "FIFO")
    preview = validate_success(api.preview_gain(s["firm"]["id"], disp["id"], TAX_OPS))
    # FIFO: 10 sh x 1000 + 5 sh x 1200 = 16000 basis; 22500 - 16000 = 6500
    assert preview["realized_gain_cents"] == 6500
    lot1_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot1["id"], TAX_OPS))
    assert lot1_after["quantity_remaining"] == 10, "preview must not mutate quantity_remaining"
    assert lot1_after["lot_status"] == "OPEN"


def test_settled_variant_persists_allocations(api):
    """PRD §3.3: "The lot's `quantity_remaining` and `adjusted_cost_basis_cents`
    are both reduced by the allocated amounts. A lot that still has shares left
    moves from `OPEN` to `PARTIALLY_DISPOSED`, its `updated_at` refreshed; a lot
    whose remaining shares are fully consumed becomes `FULLY_DISPOSED` with
    `quantity_remaining` zero."
    PRD §3.3: "The disposition's `realized_gain_cents` is then its
    `proceeds_cents` minus the total basis consumed across all allocations."

    Design: Difficulty/dual_variant_calc/lot_selection_preview_vs_settled_quantity_mutation
    """
    s, lot1, lot2, disp = _two_lot_book("TIN-LS-1", "222222222", "FIFO")
    settled = settle(s["firm"]["id"], disp["id"])
    assert settled["status"] == "SETTLED"
    assert settled["realized_gain_cents"] == 6500
    lot1_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot1["id"], TAX_OPS))
    assert lot1_after["quantity_remaining"] == 0
    assert lot1_after["lot_status"] == "FULLY_DISPOSED"
    lot2_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot2["id"], TAX_OPS))
    assert lot2_after["quantity_remaining"] == 5
    assert lot2_after["lot_status"] == "PARTIALLY_DISPOSED"


# ---------------------------------------------------------------------------
# Corner: calculations / FIFO, LIFO, HIFO
# ---------------------------------------------------------------------------

def test_fifo_chronological_order_consumption(api):
    """PRD §3.3: "Under `FIFO`, lots are taken earliest `acquisition_date`
    first, ties broken by the lot's `created_at` ascending."

    Design: Corner/calculations/fifo_chronological_order_consumption
    """
    s, lot1, lot2, disp = _two_lot_book("TIN-CALC-1", "282828282", "FIFO")
    settled = settle(s["firm"]["id"], disp["id"])
    assert settled["realized_gain_cents"] == 6500
    lot1_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot1["id"], TAX_OPS))
    lot2_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot2["id"], TAX_OPS))
    assert lot1_after["quantity_remaining"] == 0
    assert lot2_after["quantity_remaining"] == 5


def test_lifo_consumes_latest_first(api):
    """PRD §3.3: "Under `LIFO`, the most recently acquired lots go first, ties
    broken by `created_at` descending."

    Design: Corner/calculations/lifo_consumes_latest_first
    """
    s, lot1, lot2, disp = _two_lot_book("TIN-CALC-2", "292929292", "LIFO")
    settled = settle(s["firm"]["id"], disp["id"])
    # LIFO: 10 sh x 1200 + 5 sh x 1000 = 17000 basis; 22500 - 17000 = 5500
    assert settled["realized_gain_cents"] == 5500
    lot1_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot1["id"], TAX_OPS))
    lot2_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot2["id"], TAX_OPS))
    assert lot2_after["quantity_remaining"] == 0, "latest lot must be consumed first"
    assert lot1_after["quantity_remaining"] == 5


def test_hifo_consumes_highest_basis_first(api):
    """PRD §3.3: "Under `HIFO`, lots are ordered by per-share adjusted basis —
    the lot's `adjusted_cost_basis_cents` divided by its `quantity` — from
    highest to lowest, ties broken by `created_at` ascending."

    Design: Corner/calculations/hifo_consumes_highest_basis_first
    """
    s, lot1, lot2, disp = _two_lot_book("TIN-CALC-3", "303030303", "HIFO")
    settled = settle(s["firm"]["id"], disp["id"])
    # HIFO: lot2 (1200/sh) first, then lot1 (1000/sh): 17000 basis consumed
    assert settled["realized_gain_cents"] == 5500
    lot2_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot2["id"], TAX_OPS))
    assert lot2_after["quantity_remaining"] == 0, "highest-basis lot must be consumed first"


# ---------------------------------------------------------------------------
# Corner: calculations / per-share rounding walk
# ---------------------------------------------------------------------------

def test_per_share_rounding_walks_lot_to_zero_exactly(api):
    """PRD §3.3: "Each allocation is priced in whole cents: the lot's per-share
    basis is its `adjusted_cost_basis_cents` divided by its `quantity`, rounded
    half up to the nearest whole cent, and the basis an allocation consumes is
    that per-share figure multiplied by the allocated quantity."
    PRD §3.3: "The lot's `quantity_remaining` and `adjusted_cost_basis_cents`
    are both reduced by the allocated amounts."

    Design: Corner/calculations/per_share_rounding_walks_lot_to_zero_exactly
    """
    s = setup_book(tin="TIN-CALC-14", cusip="434343434", ticker="RND")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=3, basis=101)
    gains = []
    for trade, settle_d in (("2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z"),
                            ("2025-06-03T00:00:00Z", "2025-06-04T00:00:00Z"),
                            ("2025-06-05T00:00:00Z", "2025-06-06T00:00:00Z")):
        disp = make_disposition(
            s["firm"]["id"], s["account"]["id"], s["security"]["id"],
            quantity=1, proceeds=50, method="SPECIFIC_ID", trade_date=trade,
            settlement_date=settle_d,
            lot_allocations=[{"lot_id": lot["id"], "quantity": 1}],
        )
        gains.append(settle(s["firm"]["id"], disp["id"])["realized_gain_cents"])
    # PRD divides by the lot's `quantity` (original 3) each time:
    # round_half_up(101/3)=34, round_half_up(67/3)=22, round_half_up(45/3)=15
    assert gains == [16, 28, 35]
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["quantity_remaining"] == 0
    assert lot_after["adjusted_cost_basis_cents"] == 30, "101 - (34+22+15) = 30 consumed per the PRD formula"
    assert lot_after["lot_status"] == "FULLY_DISPOSED"


# ---------------------------------------------------------------------------
# Corner: endpoints / preview_gain read-only idempotence
# ---------------------------------------------------------------------------

def test_preview_gain_read_only_no_lot_mutation(api):
    """PRD §3.3: "The gain preview runs the same selection and pricing walk
    against current lot state but decrements nothing and persists nothing."

    Design: Corner/endpoints/preview_gain_read_only_no_lot_mutation
    """
    s = setup_book(tin="TIN-E-1", cusip="555555556", ticker="PVW")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=15000)
    gain1 = validate_success(api.preview_gain(s["firm"]["id"], disp["id"], TAX_OPS))["realized_gain_cents"]
    gain2 = validate_success(api.preview_gain(s["firm"]["id"], disp["id"], TAX_OPS))["realized_gain_cents"]
    assert gain1 == 5000
    assert gain2 == 5000, "preview must be an idempotent read"
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["quantity_remaining"] == 10
    assert lot_after["lot_status"] == "OPEN"


# ---------------------------------------------------------------------------
# Corner: calculations / SPECIFIC_ID validations
# ---------------------------------------------------------------------------

def test_specific_id_allocation_mismatch_rejected(api):
    """PRD §3.3: "and finally the allocation sum — under `SPECIFIC_ID`, the
    quantities across `lot_allocations` must add up to the disposition's
    `quantity` exactly, or `ERR_LOT_ALLOCATION_MISMATCH` (HTTP 422)."

    Design: Corner/calculations/specific_id_allocation_mismatch_rejected
    """
    s = setup_book(tin="TIN-CALC-4", cusip="313131313", ticker="SID")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    payload = create_disposition_payload(
        security_id=s["security"]["id"], quantity=10, proceeds_cents=15000, method="SPECIFIC_ID",
    )
    payload["lot_allocations"] = [{"lot_id": lot["id"], "quantity": 7}]
    resp = api.create_disposition(s["firm"]["id"], s["account"]["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_LOT_ALLOCATION_MISMATCH)


def test_specific_id_lot_scope_mismatch_rejected(api):
    """PRD §3.3: "then lot scope — under `SPECIFIC_ID`, every referenced lot
    must live on the same account and the same security as the disposition, or
    `ERR_LOT_SCOPE_MISMATCH` (HTTP 422)."

    Design: Corner/calculations/specific_id_lot_scope_mismatch_rejected
    """
    s = setup_book(tin="TIN-CALC-5", cusip="323232323", ticker="SC1")
    sec2 = make_security(s["firm"]["id"], cusip="333333334", ticker="SC2")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    payload = create_disposition_payload(
        security_id=sec2["id"], quantity=10, proceeds_cents=15000, method="SPECIFIC_ID",
    )
    payload["lot_allocations"] = [{"lot_id": lot["id"], "quantity": 10}]
    resp = api.create_disposition(s["firm"]["id"], s["account"]["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_LOT_SCOPE_MISMATCH)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
# disposition_create_temporal_vs_fiscal_priority
# ---------------------------------------------------------------------------

def _book_for_priority(tin, cusip):
    firm = make_firm()
    cust = make_customer(firm["id"], tin=tin, display_name="Priority Two")
    acct = make_account(firm["id"], cust["id"])
    sec = make_security(firm["id"], cusip=cusip, ticker="PR2")
    return firm, cust, acct, sec


def test_closed_tax_year_beats_zero_quantity_violation(api):
    """PRD §3.3: "then the books-window check — a `trade_date` earlier than
    January 1 of the firm's `tax_year_open` rejects with `ERR_TAX_YEAR_CLOSED`
    (HTTP 422), because prior years' books are closed; ... then fiscal sanity —
    the `quantity` must be positive, `proceeds_cents` must not be negative, and
    every per-allocation quantity inside `lot_allocations` must be positive, or
    `ERR_INVALID_REQUEST`."
    PRD §3.3: "Because the order is pinned, a suspended customer always surfaces
    before a restricted account, and a closed tax year always surfaces before an
    allocation mismatch."

    Design: Difficulty/priority_pair_validation_conflict/disposition_create_temporal_vs_fiscal_priority
    """
    firm, cust, acct, sec = _book_for_priority("TIN-PR-2", "111111115")
    payload = create_disposition_payload(
        security_id=sec["id"], trade_date="2024-06-10T00:00:00Z",
        settlement_date="2024-06-11T00:00:00Z", quantity=0, proceeds_cents=9000,
    )
    resp = api.create_disposition(firm["id"], acct["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_TAX_YEAR_CLOSED)


def test_closed_tax_year_fires_even_with_valid_quantity(api):
    """PRD §3.3: "then the books-window check — a `trade_date` earlier than
    January 1 of the firm's `tax_year_open` rejects with `ERR_TAX_YEAR_CLOSED`
    (HTTP 422), because prior years' books are closed."

    Design: Difficulty/priority_pair_validation_conflict/disposition_create_temporal_vs_fiscal_priority
    """
    firm, cust, acct, sec = _book_for_priority("TIN-PR-2B", "111111115")
    payload = create_disposition_payload(
        security_id=sec["id"], trade_date="2024-06-10T00:00:00Z",
        settlement_date="2024-06-11T00:00:00Z", quantity=5, proceeds_cents=9000,
    )
    resp = api.create_disposition(firm["id"], acct["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_TAX_YEAR_CLOSED)


# ---------------------------------------------------------------------------
# Corner: validations / zero quantity, unresolvable FK
# ---------------------------------------------------------------------------

def test_disposition_zero_quantity_rejected(api):
    """PRD §3.3: "then fiscal sanity — the `quantity` must be positive,
    `proceeds_cents` must not be negative, and every per-allocation quantity
    inside `lot_allocations` must be positive, or `ERR_INVALID_REQUEST`."

    Design: Corner/validations/disposition_zero_quantity_rejected
    """
    s = setup_book(tin="TIN-V-3", cusip="474747474", ticker="ZQ")
    payload = create_disposition_payload(security_id=s["security"]["id"], quantity=0, proceeds_cents=7000)
    resp = api.create_disposition(s["firm"]["id"], s["account"]["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_disposition_body_fk_unresolvable_rejected(api):
    """PRD §3.3: "then foreign-key resolution — the `security_id` must name a
    security inside the same firm, or `ERR_FOREIGN_KEY_UNRESOLVABLE`."

    Design: Corner/validations/disposition_body_fk_unresolvable_rejected
    """
    s = setup_book(tin="TIN-V-4", cusip="123456780", ticker="BFK")
    payload = create_disposition_payload(security_id=NON_EXISTENT_UUID, quantity=5, proceeds_cents=7000)
    resp = api.create_disposition(s["firm"]["id"], s["account"]["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_FOREIGN_KEY_UNRESOLVABLE)
