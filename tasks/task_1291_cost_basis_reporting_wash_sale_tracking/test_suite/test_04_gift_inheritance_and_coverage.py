"""Gift dual-basis rule, inheritance stepped-up basis, and covered-status
classification boundary.
"""
import pytest

from test_helpers import (
    validate_success, TEST_USERS,
    setup_book, make_lot, make_disposition, settle,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]


def _gift_lot_book(tin, cusip, ticker):
    """GIFT lot: 10 sh, donor basis 10000 (1000/sh), FMV at gift 8000 (800/sh)."""
    s = setup_book(tin=tin, cusip=cusip, ticker=ticker)
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                   quantity=10, basis=10000, kind="GIFT",
                   gift_donor_basis_cents=10000, gift_fmv_cents_at_gift=8000)
    return s, lot


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / covered_status_effective_date_boundary
# ---------------------------------------------------------------------------

def test_acquisition_on_effective_date_is_covered(api):
    """PRD §3.2: "For every other kind, the lot is `COVERED` when its
    `acquisition_date` falls on or after the security's
    `covered_security_effective_date` — the boundary is inclusive, so an
    acquisition exactly on the effective date is covered."

    Design: Difficulty/boundary_precision_check/covered_status_effective_date_boundary
    """
    s = setup_book(tin="TIN-BD-2", cusip="111111117", ticker="COV")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                   acquisition_date="2011-01-01T00:00:00Z", quantity=10, basis=10000)
    assert lot["covered_status"] == "COVERED", "acquisition_date == effective date satisfies on-or-after"


def test_acquisition_one_day_before_effective_date_is_noncovered(api):
    """PRD §3.2: "and `NONCOVERED` when earlier."

    Design: Difficulty/boundary_precision_check/covered_status_effective_date_boundary
    """
    s = setup_book(tin="TIN-BD-2", cusip="111111117", ticker="COV")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                   acquisition_date="2010-12-31T00:00:00Z", quantity=10, basis=10000)
    assert lot["covered_status"] == "NONCOVERED", "one day earlier fails the on-or-after test"


# ---------------------------------------------------------------------------
# Corner: calculations / gift dual-basis rule
# ---------------------------------------------------------------------------

def test_gift_basis_no_mans_land_zero_gain_zero_loss(api):
    """PRD §3.2: "When the sale price per share falls between the two — at or
    above the fair market value per share and at or below the donor basis per
    share — the allocation recognizes neither gain nor loss."

    Design: Corner/calculations/gift_basis_no_mans_land_zero_gain_zero_loss
    """
    s, _lot = _gift_lot_book("TIN-CALC-6", "343434343", "GNL")
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=9000)
    settled = settle(s["firm"]["id"], disp["id"])
    # 900/sh sits between FMV 800/sh and donor basis 1000/sh
    assert settled["realized_gain_cents"] == 0, "no-man's-land: neither gain nor loss recognized"
    assert settled["is_wash_sale_flag"] is False, "no loss to defer"


def test_gift_basis_loss_uses_fmv_basis(api):
    """PRD §3.2: "When the sale price per share sits below the gift-date fair
    market value per share and that fair market value is itself below the donor
    basis per share, the loss is measured using the fair market value as basis,
    and the holding period starts at the gift date."

    Design: Corner/calculations/gift_basis_loss_uses_fmv_basis
    """
    s, _lot = _gift_lot_book("TIN-CALC-7", "353535353", "GLS")
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=5000)
    settled = settle(s["firm"]["id"], disp["id"])
    # loss measured against FMV 8000, not donor basis 10000: 5000 - 8000 = -3000
    assert settled["realized_gain_cents"] == -3000


def test_gift_basis_gain_uses_donor_basis(api):
    """PRD §3.2: "When the sale price per share exceeds the donor basis per
    share, the gain is measured using the donor's basis, and the donor's
    holding period tacks onto the lot's `holding_period_start`."
    PRD §3.2: "Lots whose `acquisition_kind` is `INHERITANCE` are always
    `NONCOVERED`, and `GIFT` lots are `NONCOVERED` as well, since gifted
    property was not acquired through the broker."

    Design: Corner/calculations/gift_basis_gain_uses_donor_basis
    """
    s, lot = _gift_lot_book("TIN-CALC-8", "363636363", "GGN")
    assert lot["covered_status"] == "NONCOVERED", "gifts are always noncovered"
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=15000)
    settled = settle(s["firm"]["id"], disp["id"])
    # gain measured against donor basis 10000: 15000 - 10000 = 5000
    assert settled["realized_gain_cents"] == 5000


# ---------------------------------------------------------------------------
# Corner: calculations / inheritance stepped-up basis
# ---------------------------------------------------------------------------

def test_inheritance_lot_stepped_up_basis_and_noncovered(api):
    """PRD §3.2: "An `INHERITANCE` lot ignores any supplied
    `original_cost_basis_cents` and sets `adjusted_cost_basis_cents` to
    `inherited_fmv_cents_at_death` — the stepped-up basis. Such lots are always
    classified `NONCOVERED`, their `holding_period_start` is the
    `acquisition_date` (the date of death), and every allocation from an
    inherited lot is treated as long-term regardless of how briefly it was
    held."

    Design: Corner/calculations/inheritance_lot_stepped_up_basis_and_noncovered
    """
    s = setup_book(tin="TIN-CALC-9", cusip="373737373", ticker="HEIR")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                   quantity=10, basis=5000, kind="INHERITANCE",
                   inherited_fmv_cents_at_death=20000)
    assert lot["adjusted_cost_basis_cents"] == 20000, "stepped up to FMV at death; original 5000 ignored"
    assert lot["covered_status"] == "NONCOVERED"
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=25000,
                            trade_date="2025-02-10T00:00:00Z", settlement_date="2025-02-11T00:00:00Z")
    settled = settle(s["firm"]["id"], disp["id"])
    assert settled["realized_gain_cents"] == 5000, "25000 - 20000"
