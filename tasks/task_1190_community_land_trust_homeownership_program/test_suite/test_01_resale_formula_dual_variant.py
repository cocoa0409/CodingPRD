"""Resale formula — APPRAISAL_BASED vs INDEXED divergence."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_program_payload,
    create_resale_listing_payload,
    get_success_data,
    setup_active_lease,
)


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _pa():
    return TEST_USERS["platform_admin_headers"]


# Lease start pinned to 2016-04-01 so that, with the logical clock at its
# 2026-05-01 startup instant, the elapsed span is 3682 days and
# Y = floor(3682 / 365.25) = 10 (PRD §3.5).
LEASE_START = "2016-04-01T00:00:00Z"


def test_resale_formula_appraisal_vs_indexed_produces_different_asking_prices():
    """PRD §3.5: "Under the `APPRAISAL_BASED` variant, the appreciation is the
    greater of 0 and the difference A1 minus A0. The seller's share of the
    appreciation is the appreciation multiplied by the program's
    `appraisal_seller_share_pct`, rounded half-up to integer cents. The
    listing's `asking_price_cents` is then the seller's original purchase price
    P0 plus the seller share."
    PRD §3.5: "Under the `INDEXED` variant, an indexed value is computed first
    as P0 multiplied by one plus the product of the program's
    `indexed_annual_appreciation_pct` and the year count Y, rounded half-up to
    integer cents. The listing's `asking_price_cents` is then the smaller of
    this indexed value and A1 — the asking price is capped by the current
    market appraisal."

    Design: Difficulty/dual_variant_calc/resale_formula_appraisal_vs_indexed_diverge
    """
    pa = _pa()
    # Program A: APPRAISAL_BASED
    prog_a = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-APPR",
                resale_formula_kind="APPRAISAL_BASED",
                appraisal_seller_share_pct=0.25,
                indexed_annual_appreciation_pct=0.015,
            ),
            pa,
        )
    )
    # Program I: INDEXED
    prog_i = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-INDX",
                resale_formula_kind="INDEXED",
                appraisal_seller_share_pct=0.25,
                indexed_annual_appreciation_pct=0.015,
            ),
            pa,
        )
    )

    # PRD §3.5/§3.9: opening a listing requires the seller ELIGIBLE and the
    # unit OCCUPIED by the seller's ACTIVE lease.
    _, unit_a, _, lease_a = setup_active_lease(prog_a["id"], start_date=LEASE_START)
    _, unit_i, _, lease_i = setup_active_lease(prog_i["id"], start_date=LEASE_START)

    listing_a = get_success_data(
        api_client.create_resale_listing(
            prog_a["id"],
            unit_a["id"],
            create_resale_listing_payload(
                seller_lease_id=lease_a["id"], appraisal_at_listing_cents=35_000_000
            ),
            _lm(),
        )
    )
    listing_i = get_success_data(
        api_client.create_resale_listing(
            prog_i["id"],
            unit_i["id"],
            create_resale_listing_payload(
                seller_lease_id=lease_i["id"], appraisal_at_listing_cents=35_000_000
            ),
            _lm(),
        )
    )

    # APPRAISAL_BASED: A0 = unit.appraisal_value_cents at purchase = 0 (PRD
    # §3.3 initializes it to 0). appreciation = 35_000_000 - 0 = 35_000_000;
    # seller_share = 8_750_000; asking = 20_000_000 + 8_750_000 = 28_750_000.
    assert listing_a["asking_price_cents"] != listing_i["asking_price_cents"], (
        "APPRAISAL_BASED and INDEXED must produce different asking prices for "
        "identical inputs (P0=20_000_000, A1=35_000_000, Y=10)"
    )

    # INDEXED: indexed_value = round_half_up(20_000_000 * (1 + 0.015 * 10))
    #                       = 23_000_000; asking = min(23_000_000, 35_000_000)
    #                       = 23_000_000.
    assert listing_i["asking_price_cents"] == 23_000_000


def test_resale_formula_appraisal_vs_indexed_produces_different_subsidy_retained():
    """PRD §3.5: "The listing's `subsidy_retained_cents` is the original
    subsidy S0 plus the portion of appreciation not paid to the seller (that
    is, the appreciation minus the seller share)." (APPRAISAL_BASED)
    PRD §3.5: "The listing's `subsidy_retained_cents` is S0 plus the greater
    of 0 and the difference A1 minus the asking price." (INDEXED)

    Design: Difficulty/dual_variant_calc/resale_formula_appraisal_vs_indexed_diverge
    """
    pa = _pa()
    prog_a = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-APPR-2",
                resale_formula_kind="APPRAISAL_BASED",
                appraisal_seller_share_pct=0.25,
                indexed_annual_appreciation_pct=0.015,
            ),
            pa,
        )
    )
    prog_i = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-INDX-2",
                resale_formula_kind="INDEXED",
                appraisal_seller_share_pct=0.25,
                indexed_annual_appreciation_pct=0.015,
            ),
            pa,
        )
    )

    _, unit_a, _, lease_a = setup_active_lease(prog_a["id"], start_date=LEASE_START)
    _, unit_i, _, lease_i = setup_active_lease(prog_i["id"], start_date=LEASE_START)

    listing_a = get_success_data(
        api_client.create_resale_listing(
            prog_a["id"],
            unit_a["id"],
            create_resale_listing_payload(
                seller_lease_id=lease_a["id"], appraisal_at_listing_cents=35_000_000
            ),
            _lm(),
        )
    )
    listing_i = get_success_data(
        api_client.create_resale_listing(
            prog_i["id"],
            unit_i["id"],
            create_resale_listing_payload(
                seller_lease_id=lease_i["id"], appraisal_at_listing_cents=35_000_000
            ),
            _lm(),
        )
    )

    # INDEXED with A1=35_000_000, asking=23_000_000, S0=5_000_000:
    # subsidy_retained = 5_000_000 + max(0, 35_000_000 - 23_000_000) = 17_000_000.
    assert listing_i["subsidy_retained_cents"] == 17_000_000
    # APPRAISAL_BASED: subsidy_retained = 5_000_000 + (35_000_000 - 8_750_000)
    # = 31_250_000 — differs from INDEXED's 17_000_000.
    assert listing_a["subsidy_retained_cents"] != listing_i["subsidy_retained_cents"], (
        "APPRAISAL_BASED and INDEXED must produce different subsidy_retained_cents "
        "on identical inputs"
    )
