"""Entity assertions, instant comparison and money helpers."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MONEY_TOLERANCE = 0.005


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Accepts a trailing Z, an explicit offset, and any number of fractional
    digits, because those are rendering choices the contract does not pin.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, message: str = ""):
    """Compare two timestamps as instants, never as strings."""
    a = parse_instant(actual)
    b = parse_instant(expected)
    assert a == b, f"{message} expected instant {expected}, got {actual}"


def assert_same_date(actual, expected, message: str = ""):
    """Compare two calendar dates, tolerating a full ISO rendering on either side."""
    assert isinstance(actual, str) and actual, f"{message} expected a date, got {actual!r}"
    assert actual[:10] == expected[:10], f"{message} expected date {expected}, got {actual}"


def assert_money(actual, expected, message: str = ""):
    """Compare a monetary figure to the cent."""
    assert actual is not None, f"{message} expected {expected}, got None"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{message} expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    """id / created_at / updated_at / version on a fully versioned resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert "_" not in str(data.get("id", "")), "id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict):
    """id / created_at only — the shape of a ChargeLine or a LoadLine."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an append-only row carries no updated_at"
    assert "version" not in data, "an append-only row carries no version"


def assert_party(data: dict):
    assert_common_fields(data)
    assert data["party_type"] in [
        "INDIVIDUAL",
        "FARM",
        "DEALER",
        "PACKER",
        "CARRIER",
    ]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]


def assert_sale_day(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "SCHEDULED",
        "CHECK_IN_OPEN",
        "RINGING",
        "BIDDING_CLOSED",
        "SETTLED",
        "CANCELLED",
    ]
    assert isinstance(data["next_ring_order"], int)
    assert isinstance(data["reopen_count"], int)


def assert_consignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "INTAKE",
        "CHECKED_IN",
        "SORTED",
        "RECONCILED",
        "SETTLED",
        "WITHDRAWN",
    ]
    assert data["weigh_basis"] in ["PENCIL_SHRINK", "STAND_ACTUAL"]
    assert data["yardage_basis"] in ["PER_HEAD_DAY", "FLAT_PER_HEAD"]
    assert data["commission_basis"] in ["TIERED_VALUE", "FLAT_PER_HEAD"]
    assert data["ration_type"] in ["NONE", "STARTER", "GROWER", "HAY"]
    assert data["head_received"] >= 1


def assert_lot(data: dict):
    assert_common_fields(data)
    assert data["sale_status"] in [
        "DRAFT",
        "PENNED",
        "READY",
        "IN_RING",
        "SOLD",
        "NO_SALE",
        "WITHDRAWN",
    ]
    assert data["custody_status"] in ["BARN", "BUYER_PEN", "LOADED", "RELEASED"]
    assert data["weight_class"] in ["NONE", "LIGHT", "MEDIUM", "HEAVY"]
    assert data["bid_basis"] in ["PER_CWT", "PER_HEAD"]
    assert data["head_count"] >= 1


def assert_weigh_ticket(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "CAPTURED", "VOIDED", "SUPERSEDED"]
    assert data["ticket_seq"] >= 1


def assert_buyer_registration(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "APPROVED", "CREDIT_HOLD", "REVOKED"]
    assert data["bond_type"] in ["BONDED", "UNSECURED", "CASH_ONLY"]


def assert_settlement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "HELD", "RELEASED", "ADJUSTED"]
    assert data["hold_reason"] in ["NONE", "AWAITING_FUNDS"]


def assert_settlement_balances(data: dict):
    """The settlement's own arithmetic, as the PRD states balance_ok."""
    expected_gross = (
        data["net_amount"]
        + data["commission_amount"]
        + data["yardage_amount"]
        + data["feed_amount"]
        + data["statutory_amount"]
        + data["brand_fee_amount"]
        + data["indemnity_fee_amount"]
        + data["advances_amount"]
        + data["offset_applied"]
        - data["adjustment_total"]
    )
    assert_money(
        data["gross_amount"],
        expected_gross,
        "settlement arithmetic does not close:",
    )


def assert_buyer_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOIDED"]


def assert_charge_line(data: dict):
    assert_append_only_fields(data)
    assert data["charge_type"] in [
        "COMMISSION",
        "YARDAGE",
        "FEED",
        "CHECKOFF_STATE",
        "CHECKOFF_NATIONAL",
        "BRAND_FEE",
        "INDEMNITY_FEE",
        "BUYER_FEE",
        "HAUL",
        "DOA_CREDIT",
    ]
    assert data["side"] in ["SELLER", "BUYER"]
    assert data["revenue_class"] in [
        "BARN_REVENUE",
        "STATUTORY_REMITTANCE",
        "PASS_THROUGH",
    ]


def assert_inspection_record(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "CLEARED", "FAILED"]
    assert data["inspection_type"] in ["CVI", "BRAND", "TRICH_TEST", "BRUCELLOSIS_TEST"]


def assert_load_manifest(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PLANNED", "LOADING", "DISPATCHED", "DELIVERED", "CLOSED"]
    assert data["haul_basis"] in ["PER_MILE", "PER_HEAD_FLAT"]
    assert data["proration_basis"] in ["BY_WEIGHT", "BY_HEAD"]


def find_charge_line(lines, charge_type: str):
    """Return the single charge line of the given type, or None."""
    matches = [line for line in lines if line.get("charge_type") == charge_type]
    assert len(matches) <= 1, f"expected at most one {charge_type} line, got {len(matches)}"
    return matches[0] if matches else None


def require_charge_line(lines, charge_type: str) -> dict:
    line = find_charge_line(lines, charge_type)
    assert line is not None, f"expected a {charge_type} charge line, found none"
    return line
