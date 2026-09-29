"""Domain assertions and pure reference arithmetic.

The arithmetic helpers reimplement the normative order of operations declared by
the contract -- single division then single rounding for unit prices, a single
floor after the sum for penalty exposure, independently floored refund-credit
candidates -- so a test can assert an expected figure without restating the
whole chain inline.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ACTION_WEIGHTS,
    AUDIT_AGGRAVATOR_PCT,
    CLEAN_SCORE,
    FLUID_OUNCES_PER_GALLON,
    OUNCES_PER_POUND,
    PENALTY_ITEM_CAP,
    REFUND_CREDIT_EXPOSURE_PCT,
    REFUND_CREDIT_LIABILITY_PCT,
    SEVERITY_WEIGHTS,
    TASK_WEIGHTED_DENOMINATOR_OFFSET,
    TASK_WEIGHTED_NUMERATOR_FACTOR,
    TIER_MEDIUM_MAX_FINDINGS,
    TIER_MULTIPLIER_LARGE,
    TIER_MULTIPLIER_MEDIUM,
    TIER_MULTIPLIER_SMALL,
    TIER_SMALL_MAX_FINDINGS,
)

CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Rounding primitives
# ---------------------------------------------------------------------------
def round_half_up_2dp(value) -> Decimal:
    """Round to two decimal places, half away from zero."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct(value) -> float:
    """A percentage rounded half up to two decimals, as a float."""
    return float(round_half_up_2dp(value))


def floor_div(numerator: int, denominator: int) -> int:
    """Integer floor of a ratio of integers."""
    return numerator // denominator


# ---------------------------------------------------------------------------
# Unit price: one division then one rounding, in that order
# ---------------------------------------------------------------------------
def unit_price_basis(
    net_content_qty, net_content_uom: str, uom_rule: str
) -> tuple:
    """Return ``(basis_qty, basis_uom)`` without rounding anything."""
    qty = Decimal(str(net_content_qty))
    if uom_rule == "PER_SINGLE_ITEM":
        return Decimal(1), "EACH"
    if uom_rule == "PER_100_COUNT" and net_content_uom == "CT":
        return qty / Decimal(100), "100CT"
    if net_content_uom == "OZ":
        return qty / Decimal(OUNCES_PER_POUND), "LB"
    if net_content_uom == "LB":
        return qty, "LB"
    if net_content_uom == "FL_OZ":
        return qty / Decimal(FLUID_OUNCES_PER_GALLON), "GAL"
    if net_content_uom == "GAL":
        return qty, "GAL"
    if net_content_uom == "CT":
        return qty, "CT"
    return Decimal(1), "EACH"


def expected_unit_price_display_cents(
    new_retail_cents: int,
    net_content_qty,
    net_content_uom: str,
    uom_rule: str = "PER_UNIT_MEASURE_CANONICAL",
    decimal_places: int = 2,
    rounding: str = "ROUND_HALF_UP",
) -> Optional[float]:
    """The printed unit price, or ``None`` when the basis works out to zero."""
    basis_qty, _ = unit_price_basis(net_content_qty, net_content_uom, uom_rule)
    if basis_qty == 0:
        return None
    quotient = Decimal(new_retail_cents) / basis_qty
    kept = max(decimal_places - 2, 0)
    exponent = Decimal(1).scaleb(-kept)
    mode = ROUND_CEILING if rounding == "ROUND_CEILING" else ROUND_HALF_UP
    rounded = quotient.quantize(exponent, rounding=mode)
    return int(rounded) if kept == 0 else float(rounded)


# ---------------------------------------------------------------------------
# Audit error rates
# ---------------------------------------------------------------------------
def expected_gross_error_rate_pct(
    overcharge_count: int, undercharge_count: int, sample_size: int
) -> float:
    numerator = Decimal(overcharge_count + undercharge_count)
    return pct(numerator / Decimal(sample_size) * 100)


def expected_net_overcharge_rate_pct(
    overcharge_count: int, undercharge_count: int, sample_size: int
) -> float:
    net = max(overcharge_count - undercharge_count, 0)
    return pct(Decimal(net) / Decimal(sample_size) * 100)


# ---------------------------------------------------------------------------
# Accountability score
# ---------------------------------------------------------------------------
def outstanding_weight(action_types: List[str]) -> int:
    return sum(ACTION_WEIGHTS[a] for a in action_types)


def expected_occurrence_weighted_score(action_types: List[str]) -> float:
    return float(max(CLEAN_SCORE - outstanding_weight(action_types), 0))


def expected_task_weighted_score(
    action_types: List[str], verified_placement_count: int
) -> float:
    total = Decimal(outstanding_weight(action_types))
    denominator = Decimal(verified_placement_count + TASK_WEIGHTED_DENOMINATOR_OFFSET)
    reduction = total * Decimal(TASK_WEIGHTED_NUMERATOR_FACTOR) / denominator
    score = round_half_up_2dp(Decimal(CLEAN_SCORE) - reduction)
    return float(max(score, Decimal(0)))


# ---------------------------------------------------------------------------
# Penalty exposure
# ---------------------------------------------------------------------------
def tier_multiplier(considered_count: int) -> int:
    if considered_count <= TIER_SMALL_MAX_FINDINGS:
        return TIER_MULTIPLIER_SMALL
    if considered_count <= TIER_MEDIUM_MAX_FINDINGS:
        return TIER_MULTIPLIER_MEDIUM
    return TIER_MULTIPLIER_LARGE


def expected_penalty_component_cents(
    severity: str, penalty_per_violation_cents: int, affected_item_count: int
) -> int:
    return (
        SEVERITY_WEIGHTS[severity]
        * penalty_per_violation_cents
        * min(affected_item_count, PENALTY_ITEM_CAP)
    )


def expected_penalty_exposure_cents(
    considered: List[Dict[str, Any]],
    penalty_per_violation_cents: int,
    penalty_max_cents: int,
    evidence_audit_failed: bool,
) -> int:
    """One floor, applied after the sum is scaled -- never per finding."""
    raw_total = sum(
        expected_penalty_component_cents(
            f["severity"], penalty_per_violation_cents, f["affected_item_count"]
        )
        for f in considered
    )
    scale = tier_multiplier(len(considered)) + (
        AUDIT_AGGRAVATOR_PCT if evidence_audit_failed else 0
    )
    scaled = floor_div(raw_total * scale, 100)
    return min(scaled, penalty_max_cents)


# ---------------------------------------------------------------------------
# Inspection settlement
# ---------------------------------------------------------------------------
def expected_refund_credit_cents(
    refund_liability_cents: int, penalty_exposure_cents: int
) -> int:
    """Each candidate is floored on its own before the smaller is chosen."""
    from_liability = floor_div(
        refund_liability_cents * REFUND_CREDIT_LIABILITY_PCT, 100
    )
    from_exposure = floor_div(penalty_exposure_cents * REFUND_CREDIT_EXPOSURE_PCT, 100)
    return min(from_liability, from_exposure)


def expected_assessed_penalty_cents(
    penalty_exposure_cents: int,
    refund_credit_cents: int,
    override_cents: Optional[int] = None,
) -> int:
    if override_cents is not None:
        return override_cents
    return max(penalty_exposure_cents - refund_credit_cents, 0)


# ---------------------------------------------------------------------------
# Refund claims
# ---------------------------------------------------------------------------
def expected_claimed_amount_cents(
    shelf_price_cents: int,
    register_price_cents: int,
    policy: str,
    refund_cap_cents: int,
    refund_fixed_bonus_cents: int = 0,
) -> int:
    variance = register_price_cents - shelf_price_cents
    if policy == "REFUND_DIFFERENCE_PLUS_FIXED":
        gross = variance + refund_fixed_bonus_cents
    elif policy == "ITEM_FREE_UP_TO_CAP":
        gross = register_price_cents
    else:
        gross = variance
    return min(gross, refund_cap_cents)


# ---------------------------------------------------------------------------
# Field-shape assertions
# ---------------------------------------------------------------------------
def assert_common_fields(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Identity plus the three common audit fields."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"])
    assert is_iso8601_timestamp(record["updated_at"])
    assert isinstance(record["version"], int)
    if expected_version is not None:
        assert record["version"] == expected_version


def assert_scan_line_shape(record: Dict[str, Any]) -> None:
    """A scan line carries only ``id`` and ``created_at`` -- no version fields."""
    assert is_valid_uuid(record["id"])
    assert is_iso8601_timestamp(record["created_at"])
    assert "updated_at" not in record, "ScanLine must not expose updated_at"
    assert "version" not in record, "ScanLine must not expose version"


def assert_money_cents(value: Any, expected: int) -> None:
    """A monetary field is an integer number of cents, not a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"expected an integer cent amount, got {type(value).__name__}: {value!r}"
    )
    assert value == expected


def assert_pct(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=0.01), (
        f"expected {expected} percent, got {value!r}"
    )


def assert_fields_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], except_fields: List[str]
) -> None:
    """Every field but those named (and the audit trio) is byte-identical."""
    ignored = set(except_fields) | {"updated_at", "version"}
    for key, value in before.items():
        if key in ignored:
            continue
        assert after[key] == value, (
            f"field {key} changed from {value!r} to {after.get(key)!r}"
        )


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int = 1) -> None:
    assert after["version"] == before["version"] + delta, (
        f"version moved from {before['version']} to {after['version']}, "
        f"expected a delta of {delta}"
    )


def assert_posture(store: Dict[str, Any], expected: str) -> None:
    assert store["compliance_posture"] == expected, (
        f"expected posture {expected}, got {store['compliance_posture']} "
        f"(open={store.get('open_finding_count')}, "
        f"escalated={store.get('escalated_finding_count')}, "
        f"failed_30d={store.get('failed_audit_count_30d')}, "
        f"signage={store.get('signage_violation_count')}, "
        f"backlog={store.get('label_backlog_count')})"
    )


def assert_label_serial(serial: Any) -> None:
    assert isinstance(serial, str) and serial.startswith("LBL-"), (
        f"expected a serial prefixed LBL-, got {serial!r}"
    )


def ids_of(records: List[Dict[str, Any]]) -> List[str]:
    return [r["id"] for r in records]


def normalise_instant(value: str) -> str:
    """Drop fractional seconds so an instant can be compared to a pinned one."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    body = value[:-1] if value.endswith("Z") else value
    if "." in body:
        body = body.split(".", 1)[0]
    if "+" in body:
        body = body.split("+", 1)[0]
    return body + "Z"


def assert_instant_is(value: Any, expected: str) -> None:
    """The instant equals ``expected`` regardless of fractional-digit padding."""
    assert normalise_instant(value) == normalise_instant(expected), (
        f"expected the instant {expected}, got {value!r}"
    )
