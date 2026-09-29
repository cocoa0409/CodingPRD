"""Domain assertion helpers and reference implementations of the PRD's arithmetic.

The reference calculators below exist so a test can state an expected figure once
and have it checked against the PRD's stated rounding order rather than against a
hand-computed literal. They mirror the prose exactly: half-up rounding, once per
component in the settlement, once per rate sum in the buyer premium, and the
remainder assigned to the platform bucket in the forfeiture split.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    DEPOSIT_FLOOR_CENTS,
    DEPOSIT_PCT,
    DOC_FEE_BASE_CENTS,
    DOC_FEE_TIER_1_DISCOUNT,
    DOC_FEE_TIER_1_FLOOR_CENTS,
    DOC_FEE_TIER_2_DISCOUNT,
    DOC_FEE_TIER_2_FLOOR_CENTS,
    ELIGIBILITY_MAX_SCORE,
    FORFEIT_SELLER_BPS,
    MARKETING_RECOVERY_BPS,
    OCCUPANCY_DEPOSIT_MULTIPLIER,
    OCCUPANCY_SURCHARGE_BPS,
    POSTPONE_CARRY_BPS,
    PREMIUM_CEILING_CENTS,
    PREMIUM_FLOOR_CENTS,
    PREMIUM_TIER_1_CEILING_CENTS,
    PREMIUM_TIER_1_RATE,
    PREMIUM_TIER_2_CEILING_CENTS,
    PREMIUM_TIER_2_RATE,
    PREMIUM_TIER_3_RATE,
    TITLE_SERVICE_FEE_CENTS,
    TITLE_SURCHARGE_BPS,
)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def round_half_up(value) -> int:
    """Convert a fractional cent figure to whole cents, rounding half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Reference calculators
# ---------------------------------------------------------------------------


def expected_required_deposit(opening_bid_cents: int, occupancy_status: str) -> int:
    """Larger of the floor and five percent of the opening bid, then multiplied by
    the occupancy multiplier, each step rounded half up."""
    pct_base = round_half_up(Decimal(str(opening_bid_cents)) * Decimal(str(DEPOSIT_PCT)))
    base = max(DEPOSIT_FLOOR_CENTS, pct_base)
    multiplier = Decimal(str(OCCUPANCY_DEPOSIT_MULTIPLIER[occupancy_status]))
    return round_half_up(Decimal(base) * multiplier)


def premium_tier_rate(price_cents: int):
    if price_cents < PREMIUM_TIER_1_CEILING_CENTS:
        return Decimal(str(PREMIUM_TIER_1_RATE))
    if price_cents < PREMIUM_TIER_2_CEILING_CENTS:
        return Decimal(str(PREMIUM_TIER_2_RATE))
    return Decimal(str(PREMIUM_TIER_3_RATE))


def expected_buyer_premium(
    price_cents: int, occupancy_status: str, title_condition: str
) -> int:
    """The shared premium rule: three influences summed into one rate, a single
    half-up rounding of price times that rate, then the floor and ceiling clamps."""
    rate = premium_tier_rate(price_cents)
    rate += Decimal(OCCUPANCY_SURCHARGE_BPS[occupancy_status]) / Decimal(10000)
    rate += Decimal(TITLE_SURCHARGE_BPS[title_condition]) / Decimal(10000)
    premium = round_half_up(Decimal(price_cents) * rate)
    return max(PREMIUM_FLOOR_CENTS, min(PREMIUM_CEILING_CENTS, premium))


def expected_contract_price(hammer_price_cents: int, postponement_count: int) -> int:
    """Hammer price plus the postponement carry, the carry rounded half up once
    over the whole expression."""
    carry = round_half_up(
        Decimal(hammer_price_cents)
        * Decimal(POSTPONE_CARRY_BPS)
        * Decimal(postponement_count)
        / Decimal(10000)
    )
    return hammer_price_cents + carry


def expected_doc_fee(contract_price_cents: int, final_premium_cents: int) -> int:
    """Step one's provisional total keys the discount; step two rounds the
    discounted base fee half up."""
    provisional_total = contract_price_cents + final_premium_cents + DOC_FEE_BASE_CENTS
    if provisional_total >= DOC_FEE_TIER_2_FLOOR_CENTS:
        discount = Decimal(str(DOC_FEE_TIER_2_DISCOUNT))
    elif provisional_total >= DOC_FEE_TIER_1_FLOOR_CENTS:
        discount = Decimal(str(DOC_FEE_TIER_1_DISCOUNT))
    else:
        discount = Decimal(0)
    return round_half_up(Decimal(DOC_FEE_BASE_CENTS) * (Decimal(1) - discount))


def expected_total_due(
    contract_price_cents: int, final_premium_cents: int, doc_fee_cents: int
) -> int:
    return contract_price_cents + final_premium_cents + doc_fee_cents


def expected_platform_fee(
    contract_price_cents: int, commission_bps: int, title_condition: str
) -> int:
    """Three components, each rounded to whole cents on its own, then summed."""
    commission = round_half_up(
        Decimal(contract_price_cents) * Decimal(commission_bps) / Decimal(10000)
    )
    marketing = round_half_up(
        Decimal(contract_price_cents) * Decimal(MARKETING_RECOVERY_BPS) / Decimal(10000)
    )
    title_service = 0 if title_condition == "CLEAR" else TITLE_SERVICE_FEE_CENTS
    return commission + marketing + title_service


def expected_forfeiture_split(forfeited_deposit_cents: int):
    """Sixty percent to the seller, rounded half up; the remainder to the platform."""
    seller = round_half_up(
        Decimal(forfeited_deposit_cents) * Decimal(FORFEIT_SELLER_BPS) / Decimal(10000)
    )
    return seller, forfeited_deposit_cents - seller


def expected_risk_score(
    identity_penalty: int,
    exclusion_count: int,
    fallout_count: int,
    deposit_penalty: int,
) -> int:
    """The four components are summed and only then capped at 100."""
    total = identity_penalty + 20 * exclusion_count + 15 * fallout_count + deposit_penalty
    return min(100, total)


def expected_eligible(risk_score: int) -> bool:
    """Eligible strictly below 40: a score of 39 is eligible, a score of 40 is not."""
    return risk_score < ELIGIBILITY_MAX_SCORE


# ---------------------------------------------------------------------------
# Structural assertions
# ---------------------------------------------------------------------------


def assert_common_fields(record: dict, expected_version: Optional[int] = None) -> None:
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record["id"]), f"id must be a UUID with no type prefix: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int) and record["version"] >= 1
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_timestamp_equals(actual: str, expected_instant: str) -> None:
    """Compare a returned timestamp against a plain `...Z` instant, tolerating the
    three fractional digits the PRD specifies for serialization."""
    assert actual is not None, f"expected {expected_instant}, got None"
    normalized = actual.replace(".000Z", "Z")
    normalized_expected = expected_instant.replace(".000Z", "Z")
    assert normalized == normalized_expected, f"expected {expected_instant}, got {actual}"


def assert_deposit_pool_conserved(bidder: dict, held_total_cents: int) -> None:
    """Available plus held plus forfeited equals funded, with released holds
    contributing to none of the three terms."""
    assert (
        bidder["deposit_available_cents"]
        + held_total_cents
        + bidder["deposit_forfeited_cents"]
        == bidder["deposit_funded_cents"]
    ), (
        f"deposit pool drift: available={bidder['deposit_available_cents']} "
        f"held={held_total_cents} forfeited={bidder['deposit_forfeited_cents']} "
        f"funded={bidder['deposit_funded_cents']}"
    )


def assert_settlement_conserved(contract: dict) -> None:
    """Seller net plus platform fee plus buyer premium equals the settlement gross."""
    assert (
        contract["seller_net_cents"]
        + contract["platform_fee_cents"]
        + contract["buyer_premium_cents"]
        == contract["settlement_gross_cents"]
    ), (
        f"settlement drift: {contract['seller_net_cents']} + "
        f"{contract['platform_fee_cents']} + {contract['buyer_premium_cents']} != "
        f"{contract['settlement_gross_cents']}"
    )


def assert_forfeiture_conserved(contract: dict) -> None:
    """The seller's share and the platform's share add back to the forfeited amount."""
    assert (
        contract["forfeiture_seller_net_cents"] + contract["forfeiture_platform_fee_cents"]
        == contract["forfeited_deposit_cents"]
    ), (
        f"forfeiture drift: {contract['forfeiture_seller_net_cents']} + "
        f"{contract['forfeiture_platform_fee_cents']} != "
        f"{contract['forfeited_deposit_cents']}"
    )


def held_total_for(holds: list) -> int:
    """Sum the amounts of the holds that are HELD or EXTENDED."""
    return sum(h["amount_cents"] for h in holds if h["status"] in ("HELD", "EXTENDED"))
