"""Contract award, performance bond tiering, and bond amount gate (PRD §3.5)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_buyer_payload,
    make_buyer_headers,
    setup_sale_awarded,
)

ADMIN = TEST_USERS["admin_headers"]


def test_performance_bond_tier1_clean_buyer(api):
    """PRD §3.5: "The base rate is tiered on the awarded value: 10 percent
    when `awarded_value_cents` is at most 10,000,000 cents, 7 percent when it
    is at most 50,000,000 cents, and 5 percent above that. ... the multiplier
    is one plus 0.25 times the buyer's `prior_defaults` ... rounded half up to
    whole cents. Finally the amount is clamped: never less than 500,000 cents,
    never more than 10,000,000 cents."

    Design: Difficulty/combinatorial_formula/performance_bond_tiered_with_default_surcharge
    """
    base = setup_sale_awarded(
        sale_overrides={"sale_type": "LUMP_SUM", "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
    )
    contract = base["contract"]
    assert contract["required_bond_amount_cents"] == 800_000, (
        f"8M award at 10% = 800000, got {contract['required_bond_amount_cents']}"
    )


def test_performance_bond_default_surcharge_applies(api):
    """PRD §3.5: "the multiplier is one plus 0.25 times the buyer's
    `prior_defaults` — and the result is rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/performance_bond_tiered_with_default_surcharge
    """
    # Second sale awarded to a buyer with prior_defaults=2; same 8M award.
    base = setup_sale_awarded(
        sale_overrides={"sale_type": "LUMP_SUM", "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
        buyer_overrides={"prior_defaults": 2},
    )
    contract = base["contract"]
    # 8000000 * 0.10 * (1 + 0.25*2) = 800000 * 1.5 = 1200000.
    assert contract["required_bond_amount_cents"] == 1_200_000, (
        f"8M award at 10% x 1.5 surcharge = 1200000, got {contract['required_bond_amount_cents']}"
    )


def test_bond_amount_mismatch_rejected(api):
    """PRD §3.5: "the posted `amount_cents` must equal
    `required_bond_amount_cents` exactly, neither over nor under, or the
    posting is refused with `ERR_BOND_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/bond_amount_mismatch_rejected
    """
    base = setup_sale_awarded(
        sale_overrides={"sale_type": "PER_UNIT", "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    contract = base["contract"]
    bh = base["buyer_headers"]
    # required bond = round_half_up(13505625 * 0.10 * 1) = 1350563 (bid_total = 45000*300125/1000 = 13505625)
    required = contract["required_bond_amount_cents"]
    resp = api.post_bond(contract["id"], {"amount_cents": required - 1}, bh)
    validate_error(resp, ApiErrorId.ERR_BOND_AMOUNT_MISMATCH)
    # unchanged state
    contract_now = get_success_data(api.get_contract(contract["id"], base["forester_headers"]))
    assert contract_now["status"] == "PENDING_BOND"
