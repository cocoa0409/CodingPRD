"""Domain assertions and expectation arithmetic for the Fair Trade API.

Two kinds of helper live here. The ``assert_*`` functions check invariants the
PRD states directly - the fund conservation identity, the node credit identity,
the common property set, the narrower append-only event shape, and the three
numeric precisions. The ``expected_*`` functions re-derive figures the PRD
specifies as formulas, in the rounding order the PRD pins, so tests can compare
a response against an independently computed number.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    APPROVAL_THRESHOLD_PCT,
    CAP_BASE_ALLOWANCE_DAYS,
    FLOOR_BASE_CENTS_PER_KG,
    LICENSE_BASE_FEE_CENTS,
    LICENSE_SURCHARGE_PCT,
    LICENSE_TIER_1_CAP_KG,
    LICENSE_TIER_1_RATE_CENTS_PER_KG,
    LICENSE_TIER_2_CAP_KG,
    LICENSE_TIER_2_RATE_CENTS_PER_KG,
    LICENSE_TIER_3_RATE_CENTS_PER_KG,
    MASS_BALANCE_ATTRIBUTION_FACTOR,
    MASS_BALANCE_LOT_KG,
    ORGANIC_FLOOR_DIFFERENTIAL_CENTS_PER_KG,
    ORGANIC_PREMIUM_MULTIPLIER,
    PCT_ABS_TOLERANCE,
    PERFECT_COMPLIANCE_SCORE,
    PREMIUM_BASE_CENTS_PER_KG,
    QUALITY_FLOOR_DIFFERENTIAL_CENTS_PER_KG,
    SCORE_WEIGHTS,
    VOLUME_ABS_TOLERANCE,
)

# ---------------------------------------------------------------------------
# Numeric plumbing
# ---------------------------------------------------------------------------


def dec(value: Any) -> Decimal:
    """Coerce a JSON scalar to Decimal without introducing binary float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise AssertionError(f"expected a number, got boolean {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise AssertionError(f"expected a number, got {type(value).__name__}: {value!r}")


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    """Round half up, applied to the absolute value with the sign reapplied.

    PRD 2.6: "When the quantity being rounded may be negative, rounding half up
    is applied to the absolute value and the sign is reapplied afterwards."
    """
    quantum = Decimal(1).scaleb(-places)
    magnitude = abs(value).quantize(quantum, rounding=ROUND_HALF_UP)
    return -magnitude if value < 0 else magnitude


# ---------------------------------------------------------------------------
# Precision assertions (PRD 2.6)
# ---------------------------------------------------------------------------


def assert_money(actual: Any, expected: int, label: str = "amount") -> None:
    """Money is always an integer number of cents; there are no fractional cents."""
    value = dec(actual)
    assert value == value.to_integral_value(), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert int(value) == int(expected), f"{label}: expected {expected} cents, got {actual!r}"


def assert_volume(actual: Any, expected: Any, label: str = "volume_kg") -> None:
    """Volume is kilograms carried to exactly 3 decimal places."""
    value = dec(actual)
    target = dec(expected)
    assert abs(value - target) <= Decimal(str(VOLUME_ABS_TOLERANCE)), (
        f"{label}: expected {target} kg, got {actual!r}"
    )
    assert -value.as_tuple().exponent <= 3, (
        f"{label} must carry at most 3 decimal places, got {actual!r}"
    )


def assert_pct(actual: Any, expected: Any, label: str = "percentage") -> None:
    """Percentages are carried to exactly 2 decimal places."""
    value = dec(actual)
    target = dec(expected)
    assert abs(value - target) <= Decimal(str(PCT_ABS_TOLERANCE)), (
        f"{label}: expected {target}, got {actual!r}"
    )
    assert -value.as_tuple().exponent <= 2, (
        f"{label} must carry at most 2 decimal places, got {actual!r}"
    )


def assert_score(actual: Any, expected: int, label: str = "compliance_score") -> None:
    """compliance_score is a plain integer constrained to the closed range 0..100."""
    assert isinstance(actual, int), f"{label} must be a plain integer, got {actual!r}"
    assert 0 <= actual <= 100, f"{label} must lie in 0..100, got {actual}"
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Common resource properties (PRD 2.5)
# ---------------------------------------------------------------------------


def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A first-class resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource.get("id")), f"id must be a UUID with no prefix: {resource.get('id')!r}"
    assert is_iso8601_timestamp(resource.get("created_at")), (
        f"created_at must be an ISO 8601 UTC timestamp: {resource.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(resource.get("updated_at")), (
        f"updated_at must be an ISO 8601 UTC timestamp: {resource.get('updated_at')!r}"
    )
    assert isinstance(resource.get("version"), int), (
        f"version must be an integer, got {resource.get('version')!r}"
    )
    assert resource["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_append_only_event(record: Dict[str, Any]) -> None:
    """A ledger entry and a ballot carry only id and created_at, no updated_at, no version."""
    assert is_valid_uuid(record.get("id")), f"id must be a UUID: {record.get('id')!r}"
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"created_at must be an ISO 8601 UTC timestamp: {record.get('created_at')!r}"
    )
    assert "updated_at" not in record, "an append-only record has no updated_at field"
    assert "version" not in record, "an append-only record has no version field"


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int = 1) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']} + {delta}, got {after['version']}"
    )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], fields: Sequence[str]) -> None:
    for field in fields:
        assert after.get(field) == before.get(field), (
            f"{field} should be untouched: was {before.get(field)!r}, now {after.get(field)!r}"
        )


# ---------------------------------------------------------------------------
# Timestamps and dates
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants regardless of how many fractional digits each carries."""
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_clock_stamp(actual: Any, clock_iso: str, label: str = "timestamp") -> None:
    assert_instant(actual, clock_iso, label)


def instant_plus_days(clock_iso: str, days: int) -> str:
    moment = parse_instant(clock_iso) + timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_plus_days(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def add_months(day: str, months: int) -> str:
    """Add months calendar-wise, clamping the day of month to the target month's last day."""
    base = date.fromisoformat(day)
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year + (month // 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(base.day, last_day)).isoformat()


# ---------------------------------------------------------------------------
# The two conservation principles (PRD 2.11, 2.12)
# ---------------------------------------------------------------------------


def assert_fund_conservation(
    fund: Dict[str, Any], entries: Optional[Iterable[Dict[str, Any]]] = None
) -> None:
    """The three fund invariants that hold after every fund mutation."""
    total = int(dec(fund["total_accrued_cents"]))
    balance = int(dec(fund["balance_cents"]))
    committed = int(dec(fund["committed_cents"]))
    disbursed = int(dec(fund["disbursed_cents"]))
    assert total == balance + committed + disbursed, (
        f"total_accrued_cents {total} must equal balance {balance} + committed {committed} "
        f"+ disbursed {disbursed}"
    )
    assert balance >= 0, "balance_cents is never negative"
    assert committed >= 0, "committed_cents is never negative"
    assert disbursed >= 0, "disbursed_cents is never negative"
    if entries is not None:
        signed_sum = sum(int(dec(e["signed_amount_cents"])) for e in entries)
        assert total == signed_sum, (
            f"total_accrued_cents {total} must equal the sum of signed_amount_cents {signed_sum}"
        )


def expected_signed_amount(entry_type: str, amount_cents: int) -> int:
    """signed_amount_cents by entry_type (PRD 2.11)."""
    if entry_type == "ACCRUAL":
        return amount_cents
    if entry_type == "REVERSAL":
        return -amount_cents
    return 0


def assert_ledger_entry(
    entry: Dict[str, Any],
    entry_type: str,
    amount_cents: int,
    balance_after_cents: Optional[int] = None,
    trade_transaction_id: Optional[str] = None,
    proposal_id: Optional[str] = None,
) -> None:
    """Check one immutable ledger entry: shape, sign, magnitude and provenance."""
    assert_append_only_event(entry)
    assert entry["entry_type"] == entry_type, (
        f"expected entry_type {entry_type}, got {entry['entry_type']}"
    )
    assert_money(entry["amount_cents"], amount_cents, "amount_cents")
    assert int(dec(entry["amount_cents"])) > 0, "amount_cents is a positive magnitude"
    assert_money(
        entry["signed_amount_cents"],
        expected_signed_amount(entry_type, amount_cents),
        "signed_amount_cents",
    )
    if balance_after_cents is not None:
        assert_money(entry["balance_after_cents"], balance_after_cents, "balance_after_cents")
    assert isinstance(entry.get("memo"), str) and entry["memo"].strip(), (
        "memo carries a human-readable provenance string"
    )
    if entry_type in ("ACCRUAL", "REVERSAL"):
        assert entry.get("proposal_id") is None, "proposal_id is null on an accrual or reversal"
        assert entry.get("trade_transaction_id") is not None, (
            "trade_transaction_id is populated for the ACCRUAL and REVERSAL types"
        )
    else:
        assert entry.get("trade_transaction_id") is None, (
            "trade_transaction_id is null outside the ACCRUAL and REVERSAL types"
        )
        assert entry.get("proposal_id") is not None, (
            "proposal_id is populated for the COMMITMENT, RELEASE and DISBURSEMENT types"
        )
    if trade_transaction_id is not None:
        assert entry["trade_transaction_id"] == trade_transaction_id
    if proposal_id is not None:
        assert entry["proposal_id"] == proposal_id


def assert_node_credit(node: Dict[str, Any]) -> None:
    """available_credit_kg is certified_input minus claimed_output minus reserved_output."""
    expected = round_half_up(
        dec(node["certified_input_kg"]) - dec(node["claimed_output_kg"]) - dec(node["reserved_output_kg"]),
        3,
    )
    assert_volume(node["available_credit_kg"], expected, "available_credit_kg")
    if node["traceability_mode"] == "MASS_BALANCE":
        assert dec(node["available_credit_kg"]) >= 0, (
            "a MASS_BALANCE node's available_credit_kg is greater than or equal to 0 at all times"
        )


def assert_node_position(
    node: Dict[str, Any],
    certified_input_kg: Optional[Any] = None,
    reserved_output_kg: Optional[Any] = None,
    claimed_output_kg: Optional[Any] = None,
    available_credit_kg: Optional[Any] = None,
) -> None:
    if certified_input_kg is not None:
        assert_volume(node["certified_input_kg"], certified_input_kg, "certified_input_kg")
    if reserved_output_kg is not None:
        assert_volume(node["reserved_output_kg"], reserved_output_kg, "reserved_output_kg")
    if claimed_output_kg is not None:
        assert_volume(node["claimed_output_kg"], claimed_output_kg, "claimed_output_kg")
    if available_credit_kg is not None:
        assert_volume(node["available_credit_kg"], available_credit_kg, "available_credit_kg")
    assert_node_credit(node)


def assert_fund_partition(
    fund: Dict[str, Any],
    total_accrued_cents: Optional[int] = None,
    balance_cents: Optional[int] = None,
    committed_cents: Optional[int] = None,
    disbursed_cents: Optional[int] = None,
) -> None:
    if total_accrued_cents is not None:
        assert_money(fund["total_accrued_cents"], total_accrued_cents, "total_accrued_cents")
    if balance_cents is not None:
        assert_money(fund["balance_cents"], balance_cents, "balance_cents")
    if committed_cents is not None:
        assert_money(fund["committed_cents"], committed_cents, "committed_cents")
    if disbursed_cents is not None:
        assert_money(fund["disbursed_cents"], disbursed_cents, "disbursed_cents")
    assert_fund_conservation(fund)


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "list results are ordered by created_at ascending"


# ---------------------------------------------------------------------------
# The minimum floor and the community development premium (PRD 3.3)
# ---------------------------------------------------------------------------


def expected_applied_floor_cents_per_kg(
    product_code: str, is_organic: bool = False, quality_grade: str = "STANDARD"
) -> int:
    """The three additive floor components, two of them conditional."""
    return (
        FLOOR_BASE_CENTS_PER_KG[product_code]
        + (ORGANIC_FLOOR_DIFFERENTIAL_CENTS_PER_KG if is_organic else 0)
        + QUALITY_FLOOR_DIFFERENTIAL_CENTS_PER_KG[quality_grade]
    )


def expected_settled_unit_price(declared_unit_price_cents_per_kg: int, applied_floor: int) -> int:
    """The floor is a floor and never a ceiling."""
    return max(int(declared_unit_price_cents_per_kg), int(applied_floor))


def expected_floor_topup_cents(
    declared_unit_price_cents_per_kg: int, settled_unit_price: int, volume_kg: Any
) -> int:
    delta = dec(settled_unit_price) - dec(declared_unit_price_cents_per_kg)
    return int(round_half_up(delta * dec(volume_kg), 0))


def expected_gross_value_cents(settled_unit_price: int, volume_kg: Any) -> int:
    return int(round_half_up(dec(settled_unit_price) * dec(volume_kg), 0))


def _premium_rate(product_code: str, is_organic: bool) -> Decimal:
    rate = dec(PREMIUM_BASE_CENTS_PER_KG[product_code])
    if is_organic:
        rate = rate * dec(ORGANIC_PREMIUM_MULTIPLIER)
    return rate


def expected_physical_premium_cents(product_code: str, volume_kg: Any, is_organic: bool = False) -> int:
    """A single product rounded exactly once at the end."""
    return int(round_half_up(_premium_rate(product_code, is_organic) * dec(volume_kg), 0))


def expected_mass_balance_premium_cents(
    product_code: str, volume_kg: Any, is_organic: bool = False
) -> int:
    """The pinned rounding order: each lot is rounded before the lots are summed."""
    rate = _premium_rate(product_code, is_organic)
    factor = dec(MASS_BALANCE_ATTRIBUTION_FACTOR)
    lot_kg = dec(MASS_BALANCE_LOT_KG)
    volume = dec(volume_kg)
    full_lots = int((volume / lot_kg).to_integral_value(rounding=ROUND_DOWN))
    remainder = volume - dec(full_lots) * lot_kg
    per_lot = round_half_up(rate * lot_kg * factor, 0)
    remainder_premium = round_half_up(rate * remainder * factor, 0)
    return int(per_lot) * full_lots + int(remainder_premium)


def expected_premium_cents(
    product_code: str, volume_kg: Any, is_organic: bool, traceability_mode: str
) -> int:
    """Which variant prices the premium is read off the seller node's traceability_mode."""
    if traceability_mode == "MASS_BALANCE":
        return expected_mass_balance_premium_cents(product_code, volume_kg, is_organic)
    return expected_physical_premium_cents(product_code, volume_kg, is_organic)


def expected_premium_basis(traceability_mode: str) -> str:
    return "MASS_BALANCE" if traceability_mode == "MASS_BALANCE" else "PHYSICAL_TRACEABILITY"


# ---------------------------------------------------------------------------
# The tiered label licence fee (PRD 3.8)
# ---------------------------------------------------------------------------


def expected_license_fee(licensed_volume_kg: Any) -> Dict[str, int]:
    """The marginal-rate schedule with each tier rounded before the tiers are added."""
    volume = dec(licensed_volume_kg)
    tier_1_kg = min(volume, dec(LICENSE_TIER_1_CAP_KG))
    tier_2_kg = max(min(volume, dec(LICENSE_TIER_2_CAP_KG)) - dec(LICENSE_TIER_1_CAP_KG), Decimal(0))
    tier_3_kg = max(volume - dec(LICENSE_TIER_2_CAP_KG), Decimal(0))
    tier_1_fee = int(round_half_up(tier_1_kg * dec(LICENSE_TIER_1_RATE_CENTS_PER_KG), 0))
    tier_2_fee = int(round_half_up(tier_2_kg * dec(LICENSE_TIER_2_RATE_CENTS_PER_KG), 0))
    tier_3_fee = int(round_half_up(tier_3_kg * dec(LICENSE_TIER_3_RATE_CENTS_PER_KG), 0))
    volume_fee = tier_1_fee + tier_2_fee + tier_3_fee
    subtotal = volume_fee + LICENSE_BASE_FEE_CENTS
    surcharge = int(round_half_up(dec(subtotal) * dec(LICENSE_SURCHARGE_PCT) / dec(100), 0))
    return {
        "tier_1_fee_cents": tier_1_fee,
        "tier_2_fee_cents": tier_2_fee,
        "tier_3_fee_cents": tier_3_fee,
        "volume_fee_cents": volume_fee,
        "subtotal_cents": subtotal,
        "surcharge_cents": surcharge,
        "license_fee_cents": subtotal + surcharge,
    }


def expected_license_tier(licensed_volume_kg: Any) -> str:
    """Both breakpoints are inclusive."""
    volume = dec(licensed_volume_kg)
    if volume <= dec(LICENSE_TIER_1_CAP_KG):
        return "TIER_1"
    if volume <= dec(LICENSE_TIER_2_CAP_KG):
        return "TIER_2"
    return "TIER_3"


# ---------------------------------------------------------------------------
# Compliance scoring, corrective action deadlines and audit cadence (PRD 3.6)
# ---------------------------------------------------------------------------


def expected_compliance_score(open_critical: int, open_major: int, open_minor: int) -> int:
    """100 less 40 per open critical, 15 per open major and 5 per open minor, floored at 0."""
    raw = (
        PERFECT_COMPLIANCE_SCORE
        - SCORE_WEIGHTS["CRITICAL"] * open_critical
        - SCORE_WEIGHTS["MAJOR"] * open_major
        - SCORE_WEIGHTS["MINOR"] * open_minor
    )
    return max(0, raw)


def expected_deadline_multiplier(pre_insert_score: int) -> Decimal:
    if pre_insert_score >= 90:
        return Decimal("1.5")
    if pre_insert_score >= 70:
        return Decimal("1.0")
    return Decimal("0.5")


def expected_grace_days(pre_insert_score: int) -> int:
    if pre_insert_score >= 90:
        return 14
    if pre_insert_score >= 70:
        return 7
    return 0


def expected_deadline_days(grade: str, pre_insert_score: int) -> int:
    """The grade's base allowance multiplied by the multiplier, truncated downward."""
    product = dec(CAP_BASE_ALLOWANCE_DAYS[grade]) * expected_deadline_multiplier(pre_insert_score)
    return int(product.to_integral_value(rounding=ROUND_DOWN))


def expected_deadline_at(clock_iso: str, grade: str, pre_insert_score: int) -> str:
    return instant_plus_days(clock_iso, expected_deadline_days(grade, pre_insert_score))


def expected_audit_interval_months(post_insert_score: int) -> int:
    if post_insert_score >= 90:
        return 24
    if post_insert_score >= 70:
        return 12
    return 6


def expected_next_audit_due_at(anchor_window_end: str, post_insert_score: int) -> str:
    """The interval added calendar-wise to the latest window_end among CLOSED audits."""
    return add_months(anchor_window_end, expected_audit_interval_months(post_insert_score)) + "T00:00:00Z"


# ---------------------------------------------------------------------------
# Ballot tallies (PRD 3.5) and reconciliation variance (PRD 3.9)
# ---------------------------------------------------------------------------


def expected_turnout_pct(ballot_count: int, member_count: int) -> Decimal:
    """The denominator is the elected membership, not the number of ballots received."""
    if member_count == 0:
        return Decimal("0.00")
    return round_half_up(dec(ballot_count) / dec(member_count) * dec(100), 2)


def expected_approval_pct(approve_count: int, ballot_count: int) -> Decimal:
    """The denominator here is the ballot count, and it includes ABSTAIN ballots."""
    if ballot_count == 0:
        return Decimal("0.00")
    return round_half_up(dec(approve_count) / dec(ballot_count) * dec(100), 2)


def expected_vote_outcome(
    turnout_pct: Any, approval_pct: Any, quorum_pct: Any
) -> str:
    """The three-way fork, with both comparisons inclusive at their boundary."""
    if dec(turnout_pct) < dec(quorum_pct):
        return "REVISION_REQUESTED"
    if dec(approval_pct) >= dec(str(APPROVAL_THRESHOLD_PCT)):
        return "APPROVED"
    return "REJECTED"


def expected_variance_pct(declared_volume_kg: Any, counterparty_volume_kg: Any) -> Decimal:
    """Signed, rounded on the absolute value; 0.00 by definition when the divisor is 0."""
    counterparty = dec(counterparty_volume_kg)
    if counterparty == 0:
        return Decimal("0.00")
    raw = (dec(declared_volume_kg) - counterparty) / counterparty * dec(100)
    return round_half_up(raw, 2)


def expected_reconciliation_status(variance_pct: Any) -> str:
    magnitude = abs(dec(variance_pct))
    if magnitude > dec("10.00"):
        return "REFUSED"
    if magnitude <= dec("2.00"):
        return "MATCHED"
    return "VARIANCE_FLAGGED"


# ---------------------------------------------------------------------------
# Whole-resource shape checks used by the birth-state instances
# ---------------------------------------------------------------------------


def assert_new_holder_defaults(holder: Dict[str, Any]) -> None:
    """The field-by-field opening position of a newly registered holder (PRD 3.1)."""
    assert holder["certificate_status"] == "PENDING"
    assert_score(holder["compliance_score"], 100)
    assert holder["label_license_status"] == "NONE"
    assert holder["certified_at"] is None
    assert holder["suspension_reason"] == "NONE"
    assert holder["transition_deadline_at"] is None
    assert holder["license_year"] is None
    assert holder["licensed_volume_kg"] is None
    assert holder["license_tier"] is None
    assert_money(holder["license_fee_cents"], 0, "license_fee_cents")
    assert_money(holder["license_fee_paid_cents"], 0, "license_fee_paid_cents")
    assert holder["license_fee_settled"] is False
    assert_volume(holder["annual_certified_volume_kg"], 0, "annual_certified_volume_kg")
    assert holder["next_audit_due_at"] is None
    assert holder["open_critical_count"] == 0
    assert holder["open_major_count"] == 0
    assert holder["open_minor_count"] == 0


def assert_zeroed_fund(fund: Dict[str, Any], holder_id: str, fiscal_year: int) -> None:
    assert fund["holder_id"] == holder_id
    assert fund["fiscal_year"] == fiscal_year
    assert_fund_partition(fund, 0, 0, 0, 0)
    assert fund["pending_proposal_count"] == 0


def assert_new_node_position(node: Dict[str, Any]) -> None:
    assert_node_position(node, 0, 0, 0, 0)
