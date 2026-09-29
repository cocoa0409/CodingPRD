"""Domain assertions and rounding helpers.

The rounding helpers reproduce the exact arithmetic the contract mandates:
percentages are applied by multiplying, dividing by 100 and rounding half up,
never with banker's rounding and never with binary floating point.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing.assertions import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    COMMON_FIELDS,
    CREDIT_CARD_FEE_PCT,
    PAGINATION_META_FIELDS,
)

# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def round_half_up(value: Any, places: int = 0) -> float:
    """Round ``value`` half away from zero to ``places`` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(rounded) if places > 0 else int(rounded)


def apply_pct_to_cents(cents: int, pct: Any) -> int:
    """Multiply by a percentage, divide by 100 and round half up to whole cents."""
    product = Decimal(str(cents)) * Decimal(str(pct)) / Decimal(100)
    return int(product.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct_of(numerator: int, denominator: int, places: int = 2) -> float:
    """``numerator * 100 / denominator`` rounded half up to ``places`` places."""
    if denominator == 0:
        return 0.0
    ratio = Decimal(str(numerator)) * Decimal(100) / Decimal(str(denominator))
    quantum = Decimal(1).scaleb(-places)
    return float(ratio.quantize(quantum, rounding=ROUND_HALF_UP))


def whole_percent_of(numerator: int, denominator: int) -> int:
    """``numerator * 100 / denominator`` rounded half up to a whole percent."""
    if denominator <= 0:
        return 0
    ratio = Decimal(str(numerator)) * Decimal(100) / Decimal(str(denominator))
    return int(ratio.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def card_fee_on(post_tax_cents: int) -> int:
    """The 2.5 percent card charge on a post-tax, pre-facility-fee base."""
    return apply_pct_to_cents(post_tax_cents, CREDIT_CARD_FEE_PCT)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def canonical_timestamp(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"timestamp must end with Z: {value!r}"
    core = text[:-1]
    if "." in core:
        head, frac = core.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = core, "000"
    return f"{head}.{frac}Z"


def assert_timestamp_equals(actual: str, expected: str) -> None:
    """Compare two instants irrespective of how many fractional digits appear."""
    assert canonical_timestamp(actual) == canonical_timestamp(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


def assert_iso_timestamp(value: str) -> None:
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC instant: {value!r}"


def assert_millisecond_precision(value: str) -> None:
    """The contract renders instants with exactly three fractional digits."""
    assert_iso_timestamp(value)
    assert "." in value and len(value.split(".")[1]) == 4, (
        f"expected exactly three fractional digits, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common resource shape
# ---------------------------------------------------------------------------


def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries a server-minted id, both stamps and a version."""
    for field in COMMON_FIELDS:
        assert field in resource, f"missing common field {field!r}"
    assert is_valid_uuid(resource["id"]), (
        f"id must be a bare UUID with no type prefix, got {resource['id']!r}"
    )
    assert_iso_timestamp(resource["created_at"])
    assert_iso_timestamp(resource["updated_at"])
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_no_pagination_meta(response: Dict[str, Any]) -> None:
    """A single-resource read omits the four pagination fields."""
    assert response.get("response_type") == "object", (
        f"expected response_type 'object', got {response.get('response_type')!r}"
    )
    meta = response.get("meta") or {}
    for field in PAGINATION_META_FIELDS:
        assert field not in meta, f"single-resource read must omit meta.{field}"


def assert_list_response(response: Dict[str, Any]) -> None:
    assert response.get("response_type") == "array", (
        f"expected response_type 'array', got {response.get('response_type')!r}"
    )


def assert_empty_data_object(response: Dict[str, Any]) -> None:
    """The two test-driving endpoints return an empty data object."""
    assert response.get("response_type") == "object", (
        f"expected response_type 'object', got {response.get('response_type')!r}"
    )
    assert response.get("data") == {}, (
        f"expected an empty data object, got {response.get('data')!r}"
    )


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    stamps = [canonical_timestamp(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at: {stamps}"


def assert_version_bumped_by(newer: Dict[str, Any], older: Dict[str, Any], amount: int = 1) -> None:
    assert newer["version"] == older["version"] + amount, (
        f"expected version {older['version'] + amount}, got {newer['version']}"
    )


def assert_unchanged(newer: Dict[str, Any], older: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert newer[field] == older[field], (
            f"{field} should not have moved: was {older[field]!r}, now {newer[field]!r}"
        )


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert [row["id"] for row in rows] == expected_ids, (
        f"expected ids {expected_ids}, got {[row['id'] for row in rows]}"
    )


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def assert_integer_cents(resource: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        value = resource[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be integer cents, got {value!r}"
        )


def assert_two_decimal_percent(value: Any) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"expected a numeric percentage, got {value!r}"
    )
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == quantised, (
        f"percentage carries more than two decimals: {value!r}"
    )


# ---------------------------------------------------------------------------
# Waterfall and settlement identities
# ---------------------------------------------------------------------------


def expected_adjusted_gross(
    gross_receipts_cents: int,
    ticket_tax_pct: Any,
    paid_tickets: int,
    facility_fee_cents_per_ticket: int,
) -> Dict[str, int]:
    """Walk the three deductions in the declared order and return each bucket."""
    ticket_tax = apply_pct_to_cents(gross_receipts_cents, ticket_tax_pct)
    facility_fee = paid_tickets * facility_fee_cents_per_ticket
    card_fee = card_fee_on(gross_receipts_cents - ticket_tax)
    adjusted = gross_receipts_cents - ticket_tax - facility_fee - card_fee
    return {
        "gross_receipts_cents": gross_receipts_cents,
        "ticket_tax_cents": ticket_tax,
        "facility_fee_cents": facility_fee,
        "credit_card_fee_cents": card_fee,
        "adjusted_gross_cents": adjusted,
    }


def assert_waterfall_buckets(settlement: Dict[str, Any], expected: Dict[str, int]) -> None:
    for field, value in expected.items():
        assert settlement[field] == value, (
            f"{field}: expected {value}, got {settlement[field]}"
        )


def assert_tier_inventory_conserved(tier: Dict[str, Any]) -> None:
    """allocation = sold + comp + held + available, at every observation."""
    total = tier["sold_qty"] + tier["comp_qty"] + tier["held_qty"] + tier["available_qty"]
    assert total == tier["allocation_qty"], (
        "tier inventory drifted: "
        f"allocation {tier['allocation_qty']} != sold {tier['sold_qty']} + "
        f"comp {tier['comp_qty']} + held {tier['held_qty']} + "
        f"available {tier['available_qty']}"
    )


def assert_coop_is_lesser_leg(
    coop_contribution_cents: int,
    recognised_marketing_cents: int,
    base_earnings_cents: int,
) -> None:
    """Each leg rounds independently before the comparison, never after."""
    share_leg = apply_pct_to_cents(recognised_marketing_cents, 50)
    cap_leg = apply_pct_to_cents(base_earnings_cents, 5)
    assert coop_contribution_cents == min(share_leg, cap_leg), (
        f"co-op contribution {coop_contribution_cents} is neither the share leg "
        f"{share_leg} nor the cap leg {cap_leg}, whichever is lesser"
    )


def expected_posture(utilization_pct: Any) -> str:
    """Band the ROUNDED utilisation percentage exactly as the contract states."""
    pct = Decimal(str(utilization_pct))
    if pct <= Decimal("70"):
        return "OPEN"
    if pct <= Decimal("90"):
        return "WATCH"
    if pct < Decimal("100"):
        return "RESTRICTED"
    return "FROZEN"


def assert_market_exposure(
    market: Dict[str, Any],
    expected_committed_cents: int,
    expected_utilization_pct: Any,
    expected_risk_posture: str,
) -> None:
    assert market["committed_guarantee_cents"] == expected_committed_cents, (
        f"committed_guarantee_cents: expected {expected_committed_cents}, "
        f"got {market['committed_guarantee_cents']}"
    )
    assert float(market["exposure_utilization_pct"]) == float(expected_utilization_pct), (
        f"exposure_utilization_pct: expected {expected_utilization_pct}, "
        f"got {market['exposure_utilization_pct']}"
    )
    assert market["risk_posture"] == expected_risk_posture, (
        f"risk_posture: expected {expected_risk_posture}, got {market['risk_posture']}"
    )


def expected_insurance_recovery(
    claim_amount_cents: int,
    unrecovered_cost_cents: int,
    policy_cap_cents: int = 25_000_000,
    deductible_cents: int = 500_000,
) -> Dict[str, int]:
    covered = min(claim_amount_cents, unrecovered_cost_cents, policy_cap_cents)
    recovery = max(0, min(covered - deductible_cents, policy_cap_cents))
    return {"covered_loss_cents": covered, "insurance_recovery_cents": recovery}


def comp_allowance_for(total_allocation_qty: int) -> int:
    """3 percent of total allocation across every tier, rounded half up."""
    return int(
        (Decimal(str(total_allocation_qty)) * Decimal("3") / Decimal(100)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )
