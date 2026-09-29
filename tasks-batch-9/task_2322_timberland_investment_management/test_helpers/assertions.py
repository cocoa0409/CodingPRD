"""Domain assertion helpers for the Timberland Investment Management API.

Monetary amounts, tonnage and acreage are held at two decimal places, so equality
is asserted with an absolute tolerance of one hundredth. Per-plot net tons per
acre and the stand-level mean of those figures are held at three decimal places
and get their own helper.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

MONEY_TOLERANCE = 0.01
THREE_DECIMAL_TOLERANCE = 0.001


def _parse_instant(value: Any, label: str) -> datetime:
    assert isinstance(value, str), f"{label} must be an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC strings denote the same instant.

    The PRD pins the *instant* a timestamp field records (for example an
    appraisal signature records "the current logical-clock instant") but never
    pins how many fractional digits such a field is rendered with, so the
    comparison is made on the parsed instant rather than on its spelling.
    """
    assert _parse_instant(actual, label) == _parse_instant(expected, label), (
        f"{label}: expected the instant {expected}, got {actual}"
    )


def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    assert actual is not None, f"{label} must be present, got None"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_tons(actual: Any, expected: float, label: str = "tons") -> None:
    assert actual is not None, f"{label} must be present, got None"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_acres(actual: Any, expected: float, label: str = "acres") -> None:
    assert actual is not None, f"{label} must be present, got None"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_tons_per_acre(actual: Any, expected: float, label: str = "tons per acre") -> None:
    """Per-plot and stand-mean figures are held at three decimal places."""
    assert actual is not None, f"{label} must be present, got None"
    assert float(actual) == pytest.approx(expected, abs=THREE_DECIMAL_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_bps(actual: Any, expected: int, label: str = "basis points") -> None:
    """Basis-point yields are integers."""
    assert actual is not None, f"{label} must be present, got None"
    assert int(actual) == expected, f"{label}: expected {expected}, got {actual}"


def assert_stand_partition(
    stand: Dict[str, Any],
    net_merch_tons: Optional[float] = None,
    reserved_tons: Optional[float] = None,
    committed_tons: Optional[float] = None,
    dedicated_tons: Optional[float] = None,
    hbu_withdrawn_tons: Optional[float] = None,
    available_tons: Optional[float] = None,
) -> None:
    """Assert the named buckets and then the conserved five-bucket identity."""
    named = {
        "net_merch_tons": net_merch_tons,
        "reserved_tons": reserved_tons,
        "committed_tons": committed_tons,
        "dedicated_tons": dedicated_tons,
        "hbu_withdrawn_tons": hbu_withdrawn_tons,
        "available_tons": available_tons,
    }
    for field, expected in named.items():
        if expected is not None:
            assert_tons(stand.get(field), expected, f"stand {field}")
    assert_inventory_identity(stand)


def assert_inventory_identity(stand: Dict[str, Any]) -> None:
    """available_tons is net_merch_tons less each of the four claim buckets."""
    residue = (
        float(stand["net_merch_tons"])
        - float(stand["reserved_tons"])
        - float(stand["committed_tons"])
        - float(stand["dedicated_tons"])
        - float(stand["hbu_withdrawn_tons"])
    )
    assert float(stand["available_tons"]) == pytest.approx(residue, abs=MONEY_TOLERANCE), (
        "available_tons must equal net_merch_tons less reserved, committed, "
        f"dedicated and hbu_withdrawn tons: got {stand['available_tons']} "
        f"against a residue of {residue}"
    )


def assert_property_dimensions(
    prop: Dict[str, Any],
    status: Optional[str] = None,
    appraisal_status: Optional[str] = None,
    certification_posture: Optional[str] = None,
    harvest_plan_status: Optional[str] = None,
) -> None:
    """Assert any combination of a property's four independent state dimensions."""
    if status is not None:
        assert prop["status"] == status, f"property status: expected {status}, got {prop['status']}"
    if appraisal_status is not None:
        assert prop["appraisal_status"] == appraisal_status, (
            f"appraisal_status: expected {appraisal_status}, got {prop['appraisal_status']}"
        )
    if certification_posture is not None:
        assert prop["certification_posture"] == certification_posture, (
            "certification_posture: expected "
            f"{certification_posture}, got {prop['certification_posture']}"
        )
    if harvest_plan_status is not None:
        assert prop["harvest_plan_status"] == harvest_plan_status, (
            f"harvest_plan_status: expected {harvest_plan_status}, "
            f"got {prop['harvest_plan_status']}"
        )


def assert_fund_cash(
    fund: Dict[str, Any],
    cash_balance_usd: Optional[float] = None,
    net_operating_cash_usd: Optional[float] = None,
    cash_yield_bps: Optional[int] = None,
    harvest_acceleration_required: Optional[bool] = None,
    nav_usd: Optional[float] = None,
) -> None:
    if cash_balance_usd is not None:
        assert_money(fund.get("cash_balance_usd"), cash_balance_usd, "cash_balance_usd")
    if net_operating_cash_usd is not None:
        assert_money(
            fund.get("net_operating_cash_usd"),
            net_operating_cash_usd,
            "net_operating_cash_usd",
        )
    if cash_yield_bps is not None:
        assert_bps(fund.get("cash_yield_bps"), cash_yield_bps, "cash_yield_bps")
    if harvest_acceleration_required is not None:
        assert fund.get("harvest_acceleration_required") is harvest_acceleration_required, (
            "harvest_acceleration_required: expected "
            f"{harvest_acceleration_required}, got {fund.get('harvest_acceleration_required')}"
        )
    if nav_usd is not None:
        assert_money(fund.get("nav_usd"), nav_usd, "nav_usd")


def assert_no_versioning_fields(body: Dict[str, Any]) -> None:
    """A cruise plot carries neither an `updated_at` field nor a `version` field."""
    assert "version" not in body, f"expected no version field, found {body.get('version')!r}"
    assert "updated_at" not in body, (
        f"expected no updated_at field, found {body.get('updated_at')!r}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if limit is not None:
        assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_reallocation_entry(
    entry: Dict[str, Any],
    target_type: str,
    target_id: Optional[str] = None,
    tons_cut: Optional[float] = None,
    resulting_status: Optional[str] = None,
) -> None:
    assert entry["target_type"] == target_type, (
        f"target_type: expected {target_type}, got {entry['target_type']}"
    )
    if target_id is not None:
        assert entry["target_id"] == target_id, (
            f"target_id: expected {target_id}, got {entry['target_id']}"
        )
    if tons_cut is not None:
        assert_tons(entry.get("tons_cut"), tons_cut, "tons_cut")
    if resulting_status is not None:
        assert entry["resulting_status"] == resulting_status, (
            f"resulting_status: expected {resulting_status}, got {entry['resulting_status']}"
        )
