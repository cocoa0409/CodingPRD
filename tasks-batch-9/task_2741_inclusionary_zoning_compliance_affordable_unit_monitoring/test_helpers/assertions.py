"""Domain assertions and the arithmetic helpers the contract's rules imply."""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import COMMON_FIELDS


# --- arithmetic ---------------------------------------------------------------
def round_half_up(numerator: int, denominator: int) -> int:
    """Divide and round half away from zero, the contract's only rounding mode."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def apply_bps(amount_cents: int, bps: int) -> int:
    """amount * bps / 10000, rounded half up to the cent."""
    return round_half_up(amount_cents * bps, 10000)


# --- clock helpers ------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating both the Z and +00:00 forms."""
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instant_plus_days(value: str, days: int) -> str:
    """The instant `days` days after `value`, rendered with a trailing Z."""
    moment = parse_instant(value) + timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_plus_days(value: str, days: int) -> str:
    """The calendar date `days` days after the YYYY-MM-DD date `value`."""
    day = datetime.strptime(value, "%Y-%m-%d") + timedelta(days=days)
    return day.strftime("%Y-%m-%d")


def same_instant(left: str, right: str) -> bool:
    """Compare two instants by value, ignoring sub-second and offset spelling."""
    return parse_instant(left) == parse_instant(right)


def same_calendar_day(left: str, right: str) -> bool:
    return parse_instant(left).date() == parse_instant(right).date()


# --- shared row assertions ----------------------------------------------------
def assert_common_fields(row: Dict[str, Any]) -> None:
    """Every resource family carries id, created_at, updated_at and version."""
    for field in COMMON_FIELDS:
        assert field in row, f"missing common field {field}: {row}"
    assert is_valid_uuid(row["id"]), f"id is not a uuid: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int) and row["version"] >= 1, row["version"]


def assert_has_fields(row: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert field in row, f"missing field {field}: {sorted(row)}"


def assert_money_cents(value: Any, label: str = "amount") -> None:
    """Money crosses the wire as an integer count of cents, never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_version_is(row: Dict[str, Any], expected: int) -> None:
    assert row["version"] == expected, f"expected version {expected}, got {row['version']}"


# --- conserved quantities -----------------------------------------------------
COMPLIANT_POSTURES = ("COMPLIANT_ONSITE", "COMPLIANT_BY_FEE")


def assert_obligation_equivalents_conserved(project: Dict[str, Any]) -> None:
    """The onsite and fee-covered legs sum to the whole obligation.

    The PRD scopes this invariant precisely: "For a subject project that has
    reached a compliant posture, the sum of `onsite_unit_equivalents_bps` and
    `fee_covered_equivalents_bps` equals `total_obligation_bps` exactly."  A
    `DEFICIENT` project is by definition short of its obligation (posture clause
    4 fires exactly when the two legs sum to strictly less than the total), and
    an `UNDER_ENFORCEMENT` project may be short as well, so neither is required
    to balance.  Checking the sum outside the compliant postures would assert
    the opposite of what the specification says.
    """
    if project.get("compliance_posture") not in COMPLIANT_POSTURES:
        return
    onsite = project["onsite_unit_equivalents_bps"]
    fee_covered = project["fee_covered_equivalents_bps"]
    total = project["total_obligation_bps"]
    assert onsite + fee_covered == total, (
        "onsite_unit_equivalents_bps + fee_covered_equivalents_bps must equal "
        f"total_obligation_bps: {onsite} + {fee_covered} != {total}"
    )


def assert_fund_money_conserved(summary: Dict[str, Any]) -> None:
    """Every cent that entered the fund sits in exactly one of the three buckets."""
    unencumbered = summary["unencumbered_balance_cents"]
    encumbered = summary["encumbered_cents"]
    disbursed = summary["disbursed_cents"]
    inflow = summary["total_inflow_cents"]
    assert unencumbered + encumbered + disbursed == inflow, (
        "unencumbered_balance_cents + encumbered_cents + disbursed_cents must equal "
        f"total_inflow_cents: {unencumbered} + {encumbered} + {disbursed} != {inflow}"
    )


def assert_fund_inflow_composed(summary: Dict[str, Any]) -> None:
    """Total inflow is exactly paid fees plus recaptured resale proceeds."""
    assert (
        summary["total_paid_fees_cents"] + summary["total_recapture_cents"]
        == summary["total_inflow_cents"]
    ), summary


def assert_waterfall_conserved(resale: Dict[str, Any]) -> None:
    """The four closing buckets always sum to net proceeds exactly."""
    buckets = (
        resale["seller_equity_cents"]
        + resale["seller_improvement_credit_cents"]
        + resale["seller_appreciation_share_cents"]
        + resale["city_recapture_cents"]
    )
    assert buckets == resale["net_proceeds_cents"], (
        "the four proceeds buckets must sum to net_proceeds_cents: "
        f"{buckets} != {resale['net_proceeds_cents']}"
    )


# --- entity-shaped assertions -------------------------------------------------
def assert_project_state(
    project: Dict[str, Any],
    state: Optional[str] = None,
    applicability: Optional[str] = None,
    compliance_posture: Optional[str] = None,
) -> None:
    if state is not None:
        assert project["state"] == state, f"expected state {state}, got {project['state']}"
    if applicability is not None:
        assert project["applicability"] == applicability, project["applicability"]
    if compliance_posture is not None:
        assert project["compliance_posture"] == compliance_posture, (
            f"expected posture {compliance_posture}, got {project['compliance_posture']}"
        )


def assert_unit_dimensions(
    unit: Dict[str, Any],
    occupancy_status: Optional[str] = None,
    compliance_status: Optional[str] = None,
    restriction_state: Optional[str] = None,
) -> None:
    """The unit's three state dimensions move independently of one another."""
    if occupancy_status is not None:
        assert unit["occupancy_status"] == occupancy_status, unit["occupancy_status"]
    if compliance_status is not None:
        assert unit["compliance_status"] == compliance_status, unit["compliance_status"]
    if restriction_state is not None:
        assert unit["restriction_state"] == restriction_state, unit["restriction_state"]


def assert_fee_pricing_chain(fee: Dict[str, Any]) -> None:
    """The four pricing steps agree with one another on any assessment."""
    assert (
        fee["base_amount_cents"] + fee["surcharge_cents"] == fee["pre_discount_total_cents"]
    ), fee
    assert (
        fee["pre_discount_total_cents"] - fee["discount_cents"] == fee["assessed_amount_cents"]
    ), fee
    assert fee["discount_cents"] == apply_bps(
        fee["pre_discount_total_cents"], fee["discount_bps_applied"]
    ), fee
