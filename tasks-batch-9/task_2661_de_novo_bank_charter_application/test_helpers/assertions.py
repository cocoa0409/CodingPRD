"""
Domain assertions for the De Novo Bank Charter Application API.

These wrap the repetitive shape checks that PRD 2.4, 2.5, 2.6 and 2.11 impose on
every entity, so individual tests can spend their lines on the behaviour under
test rather than on envelope bookkeeping.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    BASE_REQUIRED_BPS_NATIONAL,
    BASE_REQUIRED_BPS_STATE_MEMBER,
    BASE_REQUIRED_BPS_STATE_NONMEMBER,
    BPS_DENOMINATOR,
    CONCENTRATION_ADD_ON_CHARGE_BPS,
    CONCENTRATION_ADD_ON_STEP_BPS,
    CONCENTRATION_TRIP_POINT_BPS,
    DE_NOVO_LEVERAGE_FLOOR_BPS,
    REIMBURSEMENT_CAP_PCT,
    REQUIRED_LEVERAGE_CEILING_BPS,
    BREACH_RISK_ADD_ON_BPS,
)
from .types import (
    CHARTER_TYPE_NATIONAL,
    CHARTER_TYPE_STATE_MEMBER,
    CHARTER_TYPE_STATE_NONMEMBER,
    SYSTEM_FIELDS,
)


# ---------------------------------------------------------------------------
# Common resource properties (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_system_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity carries a server-minted uuid id, two timestamps and a version."""
    for field in SYSTEM_FIELDS:
        assert field in entity, f"missing system field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a uuid: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO 8601: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not ISO 8601: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version begins at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_fields_equal(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert a batch of field values in one call, reporting all mismatches."""
    mismatches = []
    for key, want in expected.items():
        assert key in entity, f"missing field {key!r}: {sorted(entity)}"
        got = entity[key]
        if got != want:
            mismatches.append(f"{key}: expected {want!r}, got {got!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """Assert the named fields did not move between two reads of one row."""
    for field in fields:
        assert before[field] == after[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A rejected operation commits no partial mutation, including no version bump."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on an operation that should have changed nothing"
    )


def assert_version_bumped_by(
    before: Dict[str, Any], after: Dict[str, Any], increments: int = 1
) -> None:
    """version increments by exactly 1 per mutation of the row (PRD 2.4)."""
    assert after["version"] == before["version"] + increments, (
        f"expected version {before['version'] + increments}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Numeric representation (PRD 2.5)
# ---------------------------------------------------------------------------
def assert_integer_cents(entity: Dict[str, Any], *fields: str) -> None:
    """Money is carried in integer cents, never as a decimal or float."""
    for field in fields:
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}"
        )


def assert_integer_bps(entity: Dict[str, Any], *fields: str) -> None:
    """Ratios and rates are carried in integer basis points."""
    for field in fields:
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of basis points, got {value!r}"
        )


def assert_two_decimal_places(value: Any, expected: float, field: str = "value") -> None:
    """A field rounded half up to two decimal places compares exactly at 2dp."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == round(float(expected), 2), (
        f"{field}: expected {expected}, got {value}"
    )


def floor_bps(numerator: int, denominator: int) -> int:
    """Flooring division toward negative infinity, as PRD 2.5 requires for ratios."""
    return (numerator * BPS_DENOMINATOR) // denominator


def round_half_up_cents(numerator: int, rate_bps: int) -> int:
    """A rate struck against a cent amount, rounded half up to whole cents."""
    product = numerator * rate_bps
    quotient, remainder = divmod(product, BPS_DENOMINATOR)
    if remainder * 2 >= BPS_DENOMINATOR:
        quotient += 1
    return quotient


# ---------------------------------------------------------------------------
# Conservation invariants (PRD 2.11)
# ---------------------------------------------------------------------------
def assert_escrow_conservation(
    raise_row: Dict[str, Any], subscriptions: Iterable[Dict[str, Any]]
) -> None:
    """cleared escrow equals the counting rows; pledged plus refunded equals every row."""
    rows = list(subscriptions)
    counting = sum(s["amount_cents"] for s in rows if s["counts_toward_escrow"])
    assert raise_row["cleared_escrow_cents"] == counting, (
        "cleared_escrow_cents must equal the sum of amount_cents over exactly the "
        f"subscriptions whose counts_toward_escrow is true: expected {counting}, "
        f"got {raise_row['cleared_escrow_cents']}"
    )
    every = sum(s["amount_cents"] for s in rows)
    assert raise_row["pledged_gross_cents"] + raise_row["refunded_gross_cents"] == every, (
        "pledged_gross_cents plus refunded_gross_cents must equal the sum of "
        f"amount_cents over every subscription of the raise: expected {every}, got "
        f"{raise_row['pledged_gross_cents'] + raise_row['refunded_gross_cents']}"
    )


def assert_waterfall_reconciles(raise_row: Dict[str, Any]) -> None:
    """Gross cleared escrow always reconciles to reimbursement plus net."""
    gross = raise_row["cleared_escrow_cents"]
    reimbursement = raise_row["projected_reimbursement_cents"]
    net = raise_row["projected_net_release_cents"]
    assert reimbursement + net == gross, (
        f"waterfall does not reconcile: {reimbursement} + {net} != {gross}"
    )
    cap = round_half_up_cents(gross, REIMBURSEMENT_CAP_PCT * 100)
    assert reimbursement <= cap, (
        f"reimbursement {reimbursement} exceeds the five percent gross cap {cap}"
    )


def assert_condition_counts_conserved(
    filing: Dict[str, Any], expected_total: int
) -> None:
    """condition_total_count equals the conditions attached; nothing else moves it."""
    assert filing["condition_total_count"] == expected_total, (
        f"expected condition_total_count {expected_total}, got "
        f"{filing['condition_total_count']}"
    )
    assert filing["settled_condition_count"] <= filing["condition_total_count"], (
        "settled_condition_count may never exceed condition_total_count"
    )


# ---------------------------------------------------------------------------
# Capital adequacy derivation (PRD 3.3)
# ---------------------------------------------------------------------------
BASE_REQUIRED_BY_CHARTER_TYPE = {
    CHARTER_TYPE_NATIONAL: BASE_REQUIRED_BPS_NATIONAL,
    CHARTER_TYPE_STATE_MEMBER: BASE_REQUIRED_BPS_STATE_MEMBER,
    CHARTER_TYPE_STATE_NONMEMBER: BASE_REQUIRED_BPS_STATE_NONMEMBER,
}


def expected_concentration_add_on_bps(concentration_bps: int) -> int:
    """Five basis points for each full ten basis points above the 6500 trip point."""
    if concentration_bps <= CONCENTRATION_TRIP_POINT_BPS:
        return 0
    excess = concentration_bps - CONCENTRATION_TRIP_POINT_BPS
    return (excess // CONCENTRATION_ADD_ON_STEP_BPS) * CONCENTRATION_ADD_ON_CHARGE_BPS


def expected_required_leverage_bps(
    charter_type: str, breach_scenario_count: int, concentration_bps: int
) -> int:
    """The larger of the base tier and the risk-adjusted floor, capped at 1200."""
    add_on = expected_concentration_add_on_bps(concentration_bps)
    risk_add_on = breach_scenario_count * BREACH_RISK_ADD_ON_BPS + add_on
    base = BASE_REQUIRED_BY_CHARTER_TYPE[charter_type]
    return min(max(base, DE_NOVO_LEVERAGE_FLOOR_BPS + risk_add_on), REQUIRED_LEVERAGE_CEILING_BPS)


def assert_adequacy_derivation_consistent(derivation: Dict[str, Any]) -> None:
    """Re-derive every intermediate term from the ones the read returned."""
    assert derivation["base_required_bps"] == BASE_REQUIRED_BY_CHARTER_TYPE[
        derivation["charter_type"]
    ], "base_required_bps does not match the charter type's tier"
    assert derivation["concentration_add_on_bps"] == expected_concentration_add_on_bps(
        derivation["concentration_bps"]
    ), "concentration_add_on_bps does not match the trip-point derivation"
    expected_risk = (
        derivation["breach_scenario_count"] * BREACH_RISK_ADD_ON_BPS
        + derivation["concentration_add_on_bps"]
    )
    assert derivation["risk_add_on_bps"] == expected_risk, (
        f"expected risk_add_on_bps {expected_risk}, got {derivation['risk_add_on_bps']}"
    )
    expected_required = min(
        max(derivation["base_required_bps"], DE_NOVO_LEVERAGE_FLOOR_BPS + expected_risk),
        REQUIRED_LEVERAGE_CEILING_BPS,
    )
    assert derivation["required_leverage_bps"] == expected_required, (
        f"expected required_leverage_bps {expected_required}, got "
        f"{derivation['required_leverage_bps']}"
    )
    expected_verdict = (
        "ADEQUATE"
        if derivation["worst_governing_min_leverage_ratio_bps"]
        >= derivation["required_leverage_bps"]
        else "DEFICIENT"
    )
    assert derivation["verdict"] == expected_verdict, (
        f"expected verdict {expected_verdict}, got {derivation['verdict']}"
    )
