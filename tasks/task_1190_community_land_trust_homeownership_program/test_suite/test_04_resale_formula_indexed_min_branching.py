"""INDEXED resale formula — nested min() branching on appraisal cap."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_program_payload,
    create_resale_listing_payload,
    get_success_data,
    setup_active_lease,
)


def _pa():
    return TEST_USERS["platform_admin_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _setup_indexed_program_with_long_lease(
    *, lease_start: str = "1996-04-01T00:00:00Z"
):
    """Program (INDEXED, r=0.015) + seller household on an ACTIVE lease.

    The lease start is pinned to 1996-04-01 so that, with the logical clock at
    its 2026-05-01 startup instant, the elapsed span is 10987 days and
    Y = floor(10987 / 365.25) = 30 (PRD §3.5).
    """
    prog = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-IDX",
                resale_formula_kind="INDEXED",
                indexed_annual_appreciation_pct=0.015,
            ),
            _pa(),
        )
    )
    # PRD §3.5/§3.9: opening a listing requires the seller ELIGIBLE and the
    # unit OCCUPIED by the seller's ACTIVE lease.
    _, unit, hh, lease = setup_active_lease(prog["id"], start_date=lease_start)
    return prog, unit, hh, lease


def test_indexed_value_below_appraisal_indexed_wins():
    """PRD §3.5: "Under the `INDEXED` variant, an indexed value is computed
    first as P0 multiplied by one plus the product of the program's
    `indexed_annual_appreciation_pct` and the year count Y, rounded half-up
    to integer cents. The listing's `asking_price_cents` is then the smaller
    of this indexed value and A1 — the asking price is capped by the current
    market appraisal."

    When indexed_value < A1 the indexed value wins.

    Design: Difficulty/combinatorial_formula/resale_formula_nested_min_max_branching
    """
    prog, unit, _, lease = _setup_indexed_program_with_long_lease()
    # Y = floor((2026-05-01 - 1996-04-01)/365.25) = floor(10987/365.25) = 30
    # indexed_value = 20_000_000 * (1 + 0.015 * 30) = 20_000_000 * 1.45 = 29_000_000
    # A1 = 35_000_000 (above indexed) → asking = 29_000_000 (indexed wins)
    listing = get_success_data(
        api_client.create_resale_listing(
            prog["id"],
            unit["id"],
            create_resale_listing_payload(
                seller_lease_id=lease["id"], appraisal_at_listing_cents=35_000_000
            ),
            _lm(),
        )
    )
    assert listing["asking_price_cents"] == 29_000_000


def test_indexed_value_above_appraisal_min_caps():
    """PRD §3.5: "Under the `INDEXED` variant, an indexed value is computed
    first as P0 multiplied by one plus the product of the program's
    `indexed_annual_appreciation_pct` and the year count Y, rounded half-up
    to integer cents. The listing's `asking_price_cents` is then the smaller
    of this indexed value and A1 — the asking price is capped by the current
    market appraisal."

    When indexed_value > A1 the min() caps the asking price to A1.

    Design: Difficulty/combinatorial_formula/resale_formula_nested_min_max_branching
    """
    prog, unit, _, lease = _setup_indexed_program_with_long_lease()
    # indexed_value = 29_000_000; A1 = 25_000_000 (below cap) → asking = 25_000_000
    listing = get_success_data(
        api_client.create_resale_listing(
            prog["id"],
            unit["id"],
            create_resale_listing_payload(
                seller_lease_id=lease["id"], appraisal_at_listing_cents=25_000_000
            ),
            _lm(),
        )
    )
    assert listing["asking_price_cents"] == 25_000_000
    # Subsidy retained = S0 + max(0, A1 - asking) = 5_000_000 + 0 = 5_000_000
    assert listing["subsidy_retained_cents"] == 5_000_000
