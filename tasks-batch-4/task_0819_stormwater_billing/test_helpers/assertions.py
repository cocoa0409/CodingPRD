"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §2.6)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version present (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["owner_name"], str) and len(data["owner_name"]) > 0
    assert data["billing_method"] in ("TAX_ROLL", "UTILITY_BILL")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["delinquency_status"] in ("CURRENT", "PAST_DUE", "DELINQUENT")


def assert_parcel(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE")
    assert data["land_use"] in (
        "RESIDENTIAL_SF", "RESIDENTIAL_MF", "COMMERCIAL",
        "INDUSTRIAL", "INSTITUTIONAL", "UNDEVELOPED",
    )
    assert isinstance(data["impervious_area_sqft"], int)
    assert isinstance(data["billable_eru"], (int, float))
    assert isinstance(data["current_fee_cents"], int)


def assert_measurement(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert data["method"] in ("GIS", "FIELD_SURVEY", "AERIAL")
    assert data["source"] in ("ROUTINE", "APPEAL_REMEASURE")
    assert isinstance(data["measured_sqft"], int) and data["measured_sqft"] >= 0


def assert_exemption(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED")
    assert data["category"] in (
        "GOVERNMENT", "RELIGIOUS", "AGRICULTURAL", "UNDEVELOPED", "LOW_IMPACT",
    )


def assert_bmp_credit(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")
    assert data["bmp_type"] in (
        "RAIN_GARDEN", "DETENTION_POND", "PERMEABLE_PAVEMENT", "GREEN_ROOF", "CISTERN",
    )
    assert isinstance(data["credit_pct"], (int, float))


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED")
    assert data["result"] in (None, "PASS", "FAIL")


def assert_bill(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "ISSUED", "PARTIALLY_PAID", "PAID", "DELINQUENT", "ADJUSTED", "VOID",
    )
    assert data["fee_variant"] in ("MARGINAL", "FLAT")
    assert isinstance(data["net_fee_cents"], int)
    assert isinstance(data["assessed_fee_cents"], int)


def assert_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "NEEDS_REMEASURE", "UPHELD", "DENIED",
    )
    assert data["grounds"] in (
        "MEASUREMENT_ERROR", "LAND_USE_ERROR", "EXEMPTION_DENIED", "CREDIT_DENIED",
    )


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("APPLIED", "REFUNDED")
    assert data["method"] in ("ACH", "CARD", "CHECK", "TAX_ROLL")


def assert_fund_ledger_entry(data: dict):
    """FundLedgerEntry is append-only: only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "FundLedgerEntry must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "FundLedgerEntry must not carry version (PRD §2.4)"
    assert data["fund"] in ("CAPITAL", "OPERATING")
    assert data["entry_type"] in ("ALLOCATION", "REVERSAL")


def find_ledger_entry(entries: list, fund: str, entry_type: str) -> dict:
    """Return the single fund-ledger entry matching fund + entry_type, or fail."""
    matches = [e for e in entries if e["fund"] == fund and e["entry_type"] == entry_type]
    assert len(matches) == 1, \
        f"expected exactly one {entry_type} {fund} entry, found {len(matches)}"
    return matches[0]
