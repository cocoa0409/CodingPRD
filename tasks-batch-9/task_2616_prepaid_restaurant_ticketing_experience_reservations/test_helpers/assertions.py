"""
Domain assertions for the Prepaid Restaurant Ticketing API.

These wrap the invariants the PRD states absolutely, so a test can assert one
of them in a single call and get a diagnostic message that names the rule that
was broken.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants as C


# ─── instants ─────────────────────────────────────────────────────────────


def _as_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected: str, field: str = "instant") -> None:
    """Assert that a datetime field carries the instant the PRD pins for it.

    The PRD pins *which instant* each of these fields carries — a table
    assignment "writes `assigned_table_id` and `seat_from_utc` onto the
    reservation", seating "pins `seat_to_utc` to `seat_from_utc` plus the
    service's `turn_time_minutes`", promotion "sets `offer_expires_at_utc` to
    the logical clock plus the restaurant's `offer_ttl_minutes`". It does not
    pin how many fractional digits those fields are rendered with: §2.4 asks
    for "three fractional digits" of `created_at` and `updated_at` alone. The
    comparison is therefore on the instant, not on its spelling.
    """
    assert actual is not None, f"{field} should be {expected!r}, got None"
    assert _as_instant(actual) == _as_instant(expected), (
        f"{field} should be the instant {expected!r}, got {actual!r}"
    )


# ─── common resource properties ───────────────────────────────────────────


def assert_common_fields(resource: Dict) -> None:
    """Every persisted resource carries a server-minted UUID id, created_at,
    updated_at and a version that starts at 1."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), (
        f"created_at is not ISO 8601: {resource['created_at']!r}"
    )
    assert is_iso8601_timestamp(resource["updated_at"]), (
        f"updated_at is not ISO 8601: {resource['updated_at']!r}"
    )
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1 on creation"


def assert_ledger_row_shape(row: Dict) -> None:
    """A PaymentTransaction "carries only id and created_at, and both
    updated_at and version are absent from it entirely"."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not ISO 8601: {row['created_at']!r}"
    )
    assert "updated_at" not in row, "updated_at must be absent from a ledger row"
    assert "version" not in row, "version must be absent from a ledger row"


def assert_signed_amount(row: Dict) -> None:
    """"The kind alone fixes the sign of signed_amount_cents"."""
    magnitude = row["amount_cents"]
    assert magnitude >= 1, "amount_cents is always at least 1 and always unsigned"
    if row["kind"] in C.POSITIVE_LEDGER_KINDS:
        assert row["signed_amount_cents"] == magnitude, (
            f"{row['kind']} must carry a positive signed_amount_cents"
        )
    else:
        assert row["signed_amount_cents"] == -magnitude, (
            f"{row['kind']} must carry a negative signed_amount_cents"
        )


# ─── seat pool ────────────────────────────────────────────────────────────


def assert_seat_pool_identity(ticket_class: Dict) -> None:
    """"seats_allocated always equals seats_sold plus seats_held plus
    seats_released plus seats_available"."""
    total = (
        ticket_class["seats_sold"]
        + ticket_class["seats_held"]
        + ticket_class["seats_released"]
        + ticket_class["seats_available"]
    )
    assert ticket_class["seats_allocated"] == total, (
        "seat pool identity violated: allocated="
        f"{ticket_class['seats_allocated']} sold={ticket_class['seats_sold']} "
        f"held={ticket_class['seats_held']} "
        f"released={ticket_class['seats_released']} "
        f"available={ticket_class['seats_available']}"
    )


def assert_sell_through(ticket_class: Dict) -> None:
    """sell_through_bp is the floor of 10000*(sold+held)/allocated."""
    expected = C.sell_through_bp(
        ticket_class["seats_sold"],
        ticket_class["seats_held"],
        ticket_class["seats_allocated"],
    )
    assert ticket_class["sell_through_bp"] == expected, (
        f"sell_through_bp should be {expected}, got "
        f"{ticket_class['sell_through_bp']}"
    )


def assert_ladder_status(ticket_class: Dict) -> None:
    """The precedence ladder: released beats available, available beats
    sold out; PAUSED and CLOSED are sticky."""
    status = ticket_class["status"]
    if status in ("PAUSED", "CLOSED"):
        return
    if ticket_class["seats_released"] > 0:
        expected = "RELEASED"
    elif ticket_class["seats_available"] > 0:
        expected = "OPEN"
    else:
        expected = "SOLD_OUT"
    assert status == expected, (
        f"precedence ladder should yield {expected}, got {status} "
        f"(released={ticket_class['seats_released']}, "
        f"available={ticket_class['seats_available']})"
    )


def assert_seat_pool(
    ticket_class: Dict,
    *,
    sold: Optional[int] = None,
    held: Optional[int] = None,
    released: Optional[int] = None,
    available: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    """Assert the four counters, the identity, the sell-through and the
    ladder-derived status in one call."""
    if sold is not None:
        assert ticket_class["seats_sold"] == sold, (
            f"seats_sold should be {sold}, got {ticket_class['seats_sold']}"
        )
    if held is not None:
        assert ticket_class["seats_held"] == held, (
            f"seats_held should be {held}, got {ticket_class['seats_held']}"
        )
    if released is not None:
        assert ticket_class["seats_released"] == released, (
            f"seats_released should be {released}, got "
            f"{ticket_class['seats_released']}"
        )
    if available is not None:
        assert ticket_class["seats_available"] == available, (
            f"seats_available should be {available}, got "
            f"{ticket_class['seats_available']}"
        )
    if status is not None:
        assert ticket_class["status"] == status, (
            f"status should be {status}, got {ticket_class['status']}"
        )
    assert_seat_pool_identity(ticket_class)
    assert_sell_through(ticket_class)
    assert_ladder_status(ticket_class)


# ─── reservation money ────────────────────────────────────────────────────


def assert_balance_due(reservation: Dict) -> None:
    """"balance_due_cents is the greater of zero and grand_total_cents minus
    amount_paid_cents"."""
    expected = max(
        0, reservation["grand_total_cents"] - reservation["amount_paid_cents"]
    )
    assert reservation["balance_due_cents"] == expected, (
        f"balance_due_cents should be {expected}, got "
        f"{reservation['balance_due_cents']}"
    )


def assert_money_breakdown(
    reservation: Dict,
    *,
    ticket_subtotal: Optional[int] = None,
    add_on_total: Optional[int] = None,
    service_charge: Optional[int] = None,
    grand_total: Optional[int] = None,
    deposit_due: Optional[int] = None,
    amount_paid: Optional[int] = None,
    refunded: Optional[int] = None,
    forfeited: Optional[int] = None,
    goodwill_applied: Optional[int] = None,
) -> None:
    """Assert the charge breakdown figures a caller cares about, plus the
    grand-total identity and the balance derivation."""
    checks = [
        ("ticket_subtotal_cents", ticket_subtotal),
        ("add_on_total_cents", add_on_total),
        ("service_charge_cents", service_charge),
        ("grand_total_cents", grand_total),
        ("deposit_due_cents", deposit_due),
        ("amount_paid_cents", amount_paid),
        ("refunded_cents", refunded),
        ("forfeited_cents", forfeited),
        ("goodwill_applied_cents", goodwill_applied),
    ]
    for field, expected in checks:
        if expected is not None:
            assert reservation[field] == expected, (
                f"{field} should be {expected}, got {reservation[field]}"
            )
    assert reservation["grand_total_cents"] == (
        reservation["ticket_subtotal_cents"]
        + reservation["add_on_total_cents"]
        + reservation["service_charge_cents"]
    ), "grand_total_cents must be the sum of the three charge components"
    assert_balance_due(reservation)


def assert_payment_status(reservation: Dict, expected: str) -> None:
    assert reservation["payment_status"] == expected, (
        f"payment_status should be {expected}, got "
        f"{reservation['payment_status']}"
    )


def assert_fulfillment_status(reservation: Dict, expected: str) -> None:
    assert reservation["fulfillment_status"] == expected, (
        f"fulfillment_status should be {expected}, got "
        f"{reservation['fulfillment_status']}"
    )


def assert_settled_ledger_identity(reservation: Dict) -> None:
    """"once its money dimension reads REFUNDED, FORFEITED or
    PARTIALLY_REFUNDED — amount_paid_cents equals refunded_cents plus
    forfeited_cents exactly"."""
    assert reservation["payment_status"] in (
        "REFUNDED",
        "FORFEITED",
        "PARTIALLY_REFUNDED",
    ), "this identity only holds once the reservation has fully settled"
    assert reservation["amount_paid_cents"] == (
        reservation["refunded_cents"] + reservation["forfeited_cents"]
    ), (
        f"amount_paid_cents {reservation['amount_paid_cents']} should equal "
        f"refunded {reservation['refunded_cents']} plus forfeited "
        f"{reservation['forfeited_cents']}"
    )


def assert_signed_sum_matches(reservation: Dict, rows: List[Dict]) -> None:
    """"the sum of signed_amount_cents across a reservation's rows equals
    amount_paid_cents minus refunded_cents minus forfeited_cents"."""
    signed_sum = sum(row["signed_amount_cents"] for row in rows)
    expected = (
        reservation["amount_paid_cents"]
        - reservation["refunded_cents"]
        - reservation["forfeited_cents"]
    )
    assert signed_sum == expected, (
        f"signed ledger sum {signed_sum} should equal {expected}"
    )


def assert_derived_ledger_figures(reservation: Dict, rows: List[Dict]) -> None:
    """Re-derive the four figures from the rows and compare them."""
    paid = sum(
        row["amount_cents"]
        for row in rows
        if row["kind"]
        in ("DEPOSIT_CHARGE", "BALANCE_CHARGE", "GOODWILL_REDEMPTION", "TRANSFER_IN")
    )
    refunded = sum(row["amount_cents"] for row in rows if row["kind"] == "REFUND")
    forfeited = sum(
        row["amount_cents"] for row in rows if row["kind"] == "FORFEITURE"
    ) - sum(
        row["amount_cents"]
        for row in rows
        if row["kind"] == "FORFEITURE_REVERSAL"
    )
    goodwill = sum(
        row["amount_cents"]
        for row in rows
        if row["kind"] == "GOODWILL_REDEMPTION"
    )
    assert reservation["amount_paid_cents"] == paid, (
        f"amount_paid_cents {reservation['amount_paid_cents']} should replay to "
        f"{paid}"
    )
    assert reservation["refunded_cents"] == refunded, (
        f"refunded_cents {reservation['refunded_cents']} should replay to "
        f"{refunded}"
    )
    assert reservation["forfeited_cents"] == forfeited, (
        f"forfeited_cents {reservation['forfeited_cents']} should replay to "
        f"{forfeited}"
    )
    assert reservation["goodwill_applied_cents"] == goodwill, (
        f"goodwill_applied_cents {reservation['goodwill_applied_cents']} should "
        f"replay to {goodwill}"
    )


# ─── goodwill credit ──────────────────────────────────────────────────────


def assert_credit_identity(credit: Dict) -> None:
    """"Invariant I3 holds at all times: issued_cents equals redeemed_cents
    plus revoked_cents plus remaining_cents"."""
    assert credit["issued_cents"] == (
        credit["redeemed_cents"] + credit["revoked_cents"] + credit["remaining_cents"]
    ), (
        f"I3 violated: issued={credit['issued_cents']} "
        f"redeemed={credit['redeemed_cents']} revoked={credit['revoked_cents']} "
        f"remaining={credit['remaining_cents']}"
    )


def assert_credit_status(credit: Dict) -> None:
    """The pinned precedence order: REVOKED, then EXHAUSTED, then
    PARTIALLY_REDEEMED, else ISSUED."""
    if credit["revoked_cents"] > 0:
        expected = "REVOKED"
    elif credit["remaining_cents"] == 0:
        expected = "EXHAUSTED"
    elif 0 < credit["redeemed_cents"] < credit["issued_cents"]:
        expected = "PARTIALLY_REDEEMED"
    else:
        expected = "ISSUED"
    assert credit["status"] == expected, (
        f"credit status should be {expected}, got {credit['status']}"
    )
    assert_credit_identity(credit)


# ─── list ordering and pagination ─────────────────────────────────────────


def assert_created_at_ascending(rows: List[Dict]) -> None:
    """"list results are ordered by the row's own created_at timestamp,
    ascending — oldest first"."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in ascending created_at order: {stamps}"


def assert_pagination_meta(
    meta: Dict, *, limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, f"meta.limit should be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"meta.offset should be {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count should be {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more should be {has_more}, got {meta['has_more']}"
    )


def assert_version_advanced_by(new_version: int, old_version: int, delta: int = 1) -> None:
    """"version is an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that resource"."""
    assert new_version == old_version + delta, (
        f"version should have moved {old_version} -> {old_version + delta}, got "
        f"{new_version}"
    )
