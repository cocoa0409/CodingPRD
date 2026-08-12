"""Affordability preservation — threshold boundary inclusive."""
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


def test_affordability_preserved_true_when_asking_below_ceiling():
    """PRD §3.5: "`affordability_preserved` is true exactly when the
    listing's `asking_price_cents` is at most this ceiling — boundary
    inclusive, an asking price exactly equal to the ceiling passes."

    For AMI=10_000_000 and max_eligibility_ami_pct=0.80:
      monthly budget = round_half_up(10_000_000 * 0.80 * 0.30 / 12) = 200_000
      price ceiling = 200_000 * 12 * 30 = 72_000_000
    An INDEXED listing at asking 23_000_000 is below the ceiling → True.

    Design: Corner/calculations/affordability_preservation_threshold_boundary
    """
    prog = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-AFF",
                area_median_income_cents=10_000_000,
                max_eligibility_ami_pct=0.80,
                resale_formula_kind="INDEXED",
                indexed_annual_appreciation_pct=0.015,
            ),
            _pa(),
        )
    )
    # PRD §3.5/§3.9: opening a listing requires the seller ELIGIBLE and the
    # unit OCCUPIED by the seller's ACTIVE lease. Lease start 2016-04-01 pins
    # Y = floor(3682 / 365.25) = 10 at the 2026-05-01 startup clock.
    _, unit, _, lease = setup_active_lease(
        prog["id"], start_date="2016-04-01T00:00:00Z"
    )
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
    # INDEXED: indexed = round(20_000_000 * 1.15) = 23_000_000; asking = min(23M, 25M) = 23M
    assert listing["asking_price_cents"] == 23_000_000
    # ceiling = 72_000_000 → affordability_preserved True.
    assert listing["affordability_preserved"] is True
