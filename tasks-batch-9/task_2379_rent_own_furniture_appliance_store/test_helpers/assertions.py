"""Domain assertions: envelope shape, the three conservation identities, and pricing.

The three identities -- cash conservation, point conservation and possession
conservation -- are the acceptance criterion for the money, points and possession
machinery respectively, so they get first-class helpers here rather than being
open-coded per test.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from prd_bench_local_runner.testing.validators import set_error_http_status_map

from .api_errors import ERROR_HTTP_STATUS, expected_status_for
from .constants import PaymentRowStatus, PossessionStatus, UnitStatus

# Teach the shared validators which HTTP status each documented error carries.
set_error_http_status_map(ERROR_HTTP_STATUS)

JsonDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def success(response: requests.Response, expected_status: int = 200) -> JsonDict:
    """Assert a success envelope and return its ``data`` object."""
    return validate_success(response, expected_status=expected_status)


def created(response: requests.Response) -> JsonDict:
    """Assert a 201 success envelope and return its ``data`` object."""
    return validate_success(response, expected_status=201)


def failure(
    response: requests.Response, error_id: str, expected_status: Optional[int] = None
) -> JsonDict:
    """Assert an error envelope carrying exactly ``error_id`` and its documented status."""
    status = expected_status if expected_status is not None else expected_status_for(error_id)
    return validate_error(response, error_id, expected_status=status)


def page(response: requests.Response) -> Tuple[List[JsonDict], JsonDict]:
    """Assert a list envelope and return its rows and its ``meta``."""
    return validate_paginated(response)


def assert_pagination(
    meta: JsonDict,
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    """Assert the four pagination fields a list response reports inside ``meta``."""
    assert meta.get("limit") == limit, f"expected limit {limit}, got {meta.get('limit')}"
    assert meta.get("offset") == offset, (
        f"expected offset {offset}, got {meta.get('offset')}"
    )
    assert meta.get("total_count") == total_count, (
        f"expected total_count {total_count}, got {meta.get('total_count')}"
    )
    assert meta.get("has_more") is has_more, (
        f"expected has_more {has_more}, got {meta.get('has_more')}"
    )


def assert_row_ids(rows: Sequence[JsonDict], expected_ids: Sequence[str]) -> None:
    """Assert a page holds exactly these rows, in this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"expected rows {list(expected_ids)} in that order, got {actual}"
    )


def assert_ordered_by(rows: Sequence[JsonDict], field: str) -> None:
    """Assert rows come back ascending on one field."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"expected {field} ascending, got {values}"


def assert_total_count(response: requests.Response, expected: int) -> List[JsonDict]:
    """Assert how many rows match the filters before the page window is applied."""
    rows, meta = page(response)
    assert meta.get("total_count") == expected, (
        f"expected total_count {expected}, got {meta.get('total_count')}"
    )
    return rows


# ---------------------------------------------------------------------------
# Identity and bookkeeping
# ---------------------------------------------------------------------------


def assert_tracked_row(row: JsonDict, expected_version: Optional[int] = None) -> None:
    """Assert identity, timestamps and mutation bookkeeping on a mutable row."""
    assert is_valid_uuid(row.get("id")), f"id is not a bare UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"created_at is not ISO 8601 with three fractional digits: {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"updated_at is not ISO 8601 with three fractional digits: {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int) and row["version"] >= 1, (
        f"version must be an integer starting at 1, got {row.get('version')!r}"
    )
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_row(row: JsonDict) -> None:
    """Assert an append-only record carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(row.get("id")), f"id is not a bare UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"created_at is not ISO 8601 with three fractional digits: {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, "an append-only record has no updated_at field"
    assert "version" not in row, "an append-only record has no version field"


_INSTANT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$"
)


def as_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 UTC instant, tolerating the fractional digits it is stamped with."""
    if not isinstance(value, str) or not _INSTANT_PATTERN.match(value):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:  # pragma: no cover - guarded by the pattern above
        return None


def assert_fields(row: JsonDict, **expected: Any) -> None:
    """Assert several fields of one row at once, reporting every mismatch together.

    Instants are compared as instants, so a stamp carrying three fractional digits
    matches the same moment written without them.
    """
    problems = []
    for field, want in expected.items():
        got = row.get(field, "<absent>")
        if isinstance(want, bool) or want is None:
            ok = got is want
        else:
            wanted_instant = as_instant(want)
            got_instant = as_instant(got)
            if wanted_instant is not None and got_instant is not None:
                ok = wanted_instant == got_instant
            else:
                ok = got == want
        if not ok:
            problems.append(f"{field}: expected {want!r}, got {got!r}")
    assert not problems, "field mismatches: " + "; ".join(problems)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def assert_pricing(
    agreement: JsonDict,
    adjusted_cash_price_cents: int,
    renewal_rate_cents: int,
    rent_subtotal_cents: int,
    processing_fee_cents: int,
    total_of_payments_cents: int,
    monthly_equivalent_rate_cents: int,
) -> None:
    """Assert the ten pinned pricing steps landed on these disclosed figures."""
    assert_fields(
        agreement,
        adjusted_cash_price_cents=adjusted_cash_price_cents,
        renewal_rate_cents=renewal_rate_cents,
        rent_subtotal_cents=rent_subtotal_cents,
        processing_fee_cents=processing_fee_cents,
        total_of_payments_cents=total_of_payments_cents,
        monthly_equivalent_rate_cents=monthly_equivalent_rate_cents,
    )
    assert (
        agreement["rent_subtotal_cents"] + agreement["processing_fee_cents"]
        == agreement["total_of_payments_cents"]
    ), "total of payments must be the rent subtotal plus the processing fee"


def assert_signing_anchors_unset(agreement: JsonDict) -> None:
    """Billing does not begin at signing, so both anchors are left null."""
    assert agreement.get("cycle_anchor_at") is None, (
        f"cycle_anchor_at must be null at signing, got {agreement.get('cycle_anchor_at')!r}"
    )
    assert agreement.get("current_period_due_at") is None, (
        "current_period_due_at must be null at signing, got "
        f"{agreement.get('current_period_due_at')!r}"
    )


def assert_paid_pct(agreement: JsonDict, expected: float) -> None:
    """``paid_pct`` is a ratio stored to exactly four decimal places."""
    got = agreement.get("paid_pct")
    assert isinstance(got, (int, float)), f"paid_pct must be a number, got {got!r}"
    assert round(float(got), 4) == round(float(expected), 4), (
        f"expected paid_pct {expected}, got {got}"
    )


# ---------------------------------------------------------------------------
# The three conservation identities
# ---------------------------------------------------------------------------


def assert_cash_conserved(agreement: JsonDict, payments: Iterable[JsonDict]) -> None:
    """Posted tender must equal the sum of the agreement's five destinations."""
    posted = sum(
        p["amount_cents"]
        for p in payments
        if p.get("status") == PaymentRowStatus.POSTED
    )
    destinations = (
        agreement["rent_applied_cents"]
        + agreement["late_fee_paid_cents"]
        + agreement["reinstatement_fee_paid_cents"]
        + agreement["partial_credit_cents"]
        + agreement["customer_credit_contributed_cents"]
    )
    assert posted == destinations, (
        "cash conservation broken: posted tender "
        f"{posted} != rent {agreement['rent_applied_cents']} + late fees paid "
        f"{agreement['late_fee_paid_cents']} + reinstatement paid "
        f"{agreement['reinstatement_fee_paid_cents']} + carried credit "
        f"{agreement['partial_credit_cents']} + customer credit "
        f"{agreement['customer_credit_contributed_cents']} = {destinations}"
    )


def assert_points_conserved(
    customer: JsonDict, ledger_entries: Iterable[JsonDict]
) -> None:
    """The append-only ledger is the single source of truth for both point totals."""
    entries = list(ledger_entries)
    balance = sum(e["delta_points"] for e in entries)
    lifetime = sum(e["delta_points"] for e in entries if e["delta_points"] > 0)
    assert customer["loyalty_points_balance"] == balance, (
        "point conservation broken: balance "
        f"{customer['loyalty_points_balance']} != sum of deltas {balance}"
    )
    assert customer["loyalty_points_lifetime"] == lifetime, (
        "point conservation broken: lifetime "
        f"{customer['loyalty_points_lifetime']} != sum of positive deltas {lifetime}"
    )


def assert_possession_conserved(
    store: JsonDict,
    units: Iterable[JsonDict],
    agreements: Iterable[JsonDict],
) -> None:
    """Units in customers' hands must equal agreements holding goods, and the counters."""
    on_rent_units = [u for u in units if u.get("status") == UnitStatus.ON_RENT]
    in_service_units = [u for u in units if u.get("status") == UnitStatus.IN_SERVICE]
    holding = [
        a
        for a in agreements
        if a.get("possession_status")
        in (PossessionStatus.DELIVERED, PossessionStatus.SERVICE_SWAP_PENDING)
    ]
    assert len(on_rent_units) == len(holding), (
        "possession conservation broken: "
        f"{len(on_rent_units)} units on rent vs {len(holding)} agreements holding goods"
    )
    assert store["units_on_rent_count"] == len(on_rent_units), (
        "possession conservation broken: units_on_rent_count "
        f"{store['units_on_rent_count']} != {len(on_rent_units)} units on rent"
    )
    assert store["units_in_service_count"] == len(in_service_units), (
        "possession conservation broken: units_in_service_count "
        f"{store['units_in_service_count']} != {len(in_service_units)} units in service"
    )


def assert_intake_gate(store: JsonDict) -> None:
    """``service_intake_open`` is false exactly when the bays are full."""
    expected = store["units_in_service_count"] < store["service_bay_capacity"]
    assert store["service_intake_open"] is expected, (
        "service_intake_open must be "
        f"{expected} while {store['units_in_service_count']} of "
        f"{store['service_bay_capacity']} bays are occupied, got "
        f"{store['service_intake_open']}"
    )
