"""Domain assertion helpers for the Premium Sports Hospitality API."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import SECONDS_PER_DAY

# --------------------------------------------------------------------------
# Timestamps and identifiers (§2.4)
# --------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_utc(moment: datetime) -> str:
    """Render an instant in the PRD's three-fractional-digit UTC format."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.astimezone(timezone.utc).microsecond // 1000:03d}Z"
    )


def shift_days(value: str, days: int) -> str:
    """The instant ``days`` whole days after ``value``, in PRD format."""
    return iso_utc(parse_instant(value) + timedelta(days=days))


def shift_minutes(value: str, minutes: int) -> str:
    """The instant ``minutes`` minutes after ``value``, in PRD format."""
    return iso_utc(parse_instant(value) + timedelta(minutes=minutes))


def days_between(earlier: str, later: str) -> int:
    """Whole elapsed days: seconds difference divided by 86,400, truncated (§2.4)."""
    delta = (parse_instant(later) - parse_instant(earlier)).total_seconds()
    return int(delta // SECONDS_PER_DAY)


def assert_bare_uuid(value: Any) -> None:
    """An id is a server-minted UUID carrying no type prefix (§2.4)."""
    assert isinstance(value, str), f"id must be a string, got {value!r}"
    assert is_valid_uuid(value), f"id must be a UUID, got {value!r}"
    assert len(value) == 36, f"id must be 36 characters, got {len(value)}"
    assert "_" not in value, f"id must carry no type prefix, got {value!r}"


def assert_utc_millis(value: Any) -> None:
    """An ISO 8601 UTC timestamp with exactly three fractional digits (§2.4)."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert value.endswith("Z"), f"timestamp must end in Z: {value!r}"
    assert len(value) == 24, f"timestamp must carry three fractional digits: {value!r}"
    assert value[19] == ".", f"timestamp must carry a fractional part: {value!r}"


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries id, created_at, updated_at and version (§2.4)."""
    assert_bare_uuid(entity["id"])
    assert_utc_millis(entity["created_at"])
    assert_utc_millis(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


# --------------------------------------------------------------------------
# Money and fractions (§2.5)
# --------------------------------------------------------------------------


def assert_cents(value: Any) -> None:
    """Monetary amounts are integer counts of cents with no fractional part."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"money must be an integer count of cents, got {value!r}"
    )


def assert_fraction_4dp(value: Any, expected: float) -> None:
    """margin_pct and volume_discount_pct are four-decimal-place fractions."""
    assert value == pytest.approx(expected, abs=0.00005), (
        f"expected {expected} to four decimal places, got {value!r}"
    )


def round_half_up(value: float) -> int:
    """Round to the nearest whole cent with ties away from zero (§2.5)."""
    from decimal import Decimal, ROUND_HALF_UP

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Envelope and pagination (§2.2, §2.3)
# --------------------------------------------------------------------------


def assert_object_envelope(response: Any) -> None:
    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert_utc_millis(body["meta"]["api_request_timestamp"])


def assert_list_page(response: Any, expected_total: int, expected_rows: int,
                     expected_limit: Optional[int] = None,
                     expected_offset: Optional[int] = None,
                     expected_has_more: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Assert a list page's rows and its four pagination counters (§2.3)."""
    data, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    assert len(data) == expected_rows, f"expected {expected_rows} rows, got {len(data)}"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more
    return data


def assert_total_count(response: Any, expected_total: int) -> List[Dict[str, Any]]:
    data, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    return data


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


# --------------------------------------------------------------------------
# Domain-shaped assertions
# --------------------------------------------------------------------------


def assert_deal_position(deal: Dict[str, Any], released: int, shortfall: int,
                         liability: int, status: str,
                         unallocated: Optional[int] = None) -> None:
    """The deal's four derived exposure figures plus its status (§3.1)."""
    assert deal["released_units"] == released
    assert deal["shortfall_units"] == shortfall
    assert deal["minimum_liability_cents"] == liability
    assert deal["deal_status"] == status
    if unallocated is not None:
        assert deal["unallocated_units"] == unallocated


def assert_block_position(block: Dict[str, Any], allocated: int, committed: int,
                          released_back: int, state: str) -> None:
    """An allocation block's three counters plus its state (§2.9, §3.3)."""
    assert block["allocated_units"] == allocated
    assert block["committed_units"] == committed
    assert block["released_back_units"] == released_back
    assert block["block_state"] == state


def assert_package_pricing(package: Dict[str, Any], base_cost: int, subtotal: int,
                           list_price: int, margin_pct: float,
                           status: Optional[str] = None) -> None:
    """The four derived package money fields (§3.4)."""
    assert package["base_cost_cents"] == base_cost
    assert package["component_price_subtotal_cents"] == subtotal
    assert package["list_price_cents"] == list_price
    assert_fraction_4dp(package["margin_pct"], margin_pct)
    if status is not None:
        assert package["package_status"] == status


def assert_booking_price_buildup(booking: Dict[str, Any], gross: int,
                                 volume_discount_pct: float, discounted_subtotal: int,
                                 commission: int, surcharge: int, net: int) -> None:
    """The six-step price build-up of §3.5, each figure rounded once."""
    assert booking["gross_price_cents"] == gross
    assert_fraction_4dp(booking["volume_discount_pct"], volume_discount_pct)
    assert booking["discounted_subtotal_cents"] == discounted_subtotal
    assert booking["partner_commission_cents"] == commission
    assert booking["guarantee_surcharge_cents"] == surcharge
    assert booking["net_price_cents"] == net
    assert net == discounted_subtotal - commission + surcharge, (
        "net_price_cents must be the discounted subtotal less the commission "
        "plus the surcharge"
    )


def assert_booking_dimensions(booking: Dict[str, Any], fulfillment_status: str,
                              payment_status: str) -> None:
    """The two parallel status dimensions of a booking (§3.5)."""
    assert booking["fulfillment_status"] == fulfillment_status
    assert booking["payment_status"] == payment_status


def assert_settlement_identity(booking: Dict[str, Any], pre_paid_cents: int) -> None:
    """The fee equals the pre-cancellation paid amount, less the refund, plus
    the balance due (§3.8), and both legs are clamped at 0."""
    fee = booking["cancellation_fee_cents"]
    refund = booking["refund_cents"]
    balance = booking["balance_due_cents"]
    assert refund >= 0, "refund_cents is floored at 0"
    assert balance >= 0, "balance_due_cents is floored at 0"
    assert fee == pre_paid_cents - refund + balance, (
        f"conserved identity broken: {fee} != {pre_paid_cents} - {refund} + {balance}"
    )
    assert not (refund > 0 and balance > 0), "at most one of the two legs is positive"


def assert_schedule_conservation(installments: List[Dict[str, Any]],
                                 net_price_cents: int,
                                 already_paid_cents: int = 0) -> None:
    """The total amount across live SCHEDULE lines plus what was already paid
    equals the booking's net price (§3.6)."""
    live = [
        line for line in installments
        if line["installment_kind"] == "SCHEDULE"
        and line["installment_state"] in ("SCHEDULED", "OVERDUE", "PAID")
    ]
    total = sum(line["amount_cents"] for line in live)
    assert total + already_paid_cents == net_price_cents, (
        f"schedule conservation broken: {total} + {already_paid_cents} "
        f"!= {net_price_cents}"
    )


def assert_schedule_amounts(installments: List[Dict[str, Any]],
                            expected_amounts: List[int]) -> None:
    """The SCHEDULE lines in sequence_no order carry the expected amounts."""
    lines = sorted(
        [line for line in installments if line["installment_kind"] == "SCHEDULE"],
        key=lambda line: line["sequence_no"],
    )
    assert [line["amount_cents"] for line in lines] == expected_amounts
    assert [line["sequence_no"] for line in lines] == list(
        range(1, len(expected_amounts) + 1)
    ), "sequence_no is 1-based and contiguous within a booking"


def assert_risk_band(event: Dict[str, Any], score: int, posture: str) -> None:
    """The integer score and the band derived from it (§3.9)."""
    assert event["fulfillment_risk_score"] == score
    assert event["risk_posture"] == posture
    assert event["fulfillment_risk_score"] <= 100, "the score is capped at 100"


def assert_margin_report(report: Dict[str, Any], variant: str, revenue: int,
                         rights_cost: int, build_cost: int, cost: int,
                         unsold_units: int, unsold_exposure: int,
                         margin: int, net_margin: int, margin_pct: float) -> None:
    """The ten answered fields of the margin report (§3.9)."""
    assert report["variant"] == variant
    assert report["revenue_cents"] == revenue
    assert report["rights_cost_cents"] == rights_cost
    assert report["build_cost_cents"] == build_cost
    assert report["cost_cents"] == cost
    assert report["unsold_units"] == unsold_units
    assert report["unsold_exposure_cents"] == unsold_exposure
    assert report["margin_cents"] == margin
    assert report["net_margin_cents"] == net_margin
    assert_fraction_4dp(report["margin_pct"], margin_pct)
    assert cost == rights_cost + build_cost
    assert margin == revenue - cost
    assert net_margin == margin - unsold_exposure


def assert_itinerary(itinerary: Dict[str, Any], event_name: str, event_date: str,
                     venue_name: str, hotel_nights: int, transport_included: bool,
                     credential_count: int, host_names: List[str]) -> None:
    """The frozen servicing itinerary's pinned key set (§3.7)."""
    assert set(itinerary.keys()) == {
        "event_name",
        "event_date",
        "venue_name",
        "hotel_nights",
        "transport_included",
        "credential_count",
        "host_names",
    }
    assert itinerary["event_name"] == event_name
    assert itinerary["event_date"] == event_date
    assert itinerary["venue_name"] == venue_name
    assert itinerary["hotel_nights"] == hotel_nights
    assert itinerary["transport_included"] is transport_included
    assert itinerary["credential_count"] == credential_count
    assert itinerary["host_names"] == host_names


def assert_daily_run_report(report: Dict[str, Any], run_at: Optional[str] = None,
                            lapsed: Optional[int] = None,
                            overdue: Optional[int] = None,
                            shortfall: Optional[int] = None,
                            client_changes: Optional[int] = None) -> None:
    """The five counters the rollover sweep answers with (§3.6)."""
    for key in (
        "run_at",
        "lapsed_tranche_count",
        "overdue_installment_count",
        "shortfall_deal_count",
        "client_status_change_count",
    ):
        assert key in report, f"the sweep must report {key}"
    if run_at is not None:
        assert report["run_at"] == run_at
    if lapsed is not None:
        assert report["lapsed_tranche_count"] == lapsed
    if overdue is not None:
        assert report["overdue_installment_count"] == overdue
    if shortfall is not None:
        assert report["shortfall_deal_count"] == shortfall
    if client_changes is not None:
        assert report["client_status_change_count"] == client_changes
