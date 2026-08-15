"""Entity assertions and domain invariant checkers.

Each assert_* enforces the shape PRD §2.4 (common fields) and the
field-presence rules of §3. Append-only ledger entities (DirectiveRecord,
ReleaseCertificate, TraceabilityRecord) are required to NOT carry
`updated_at` or `version` per PRD §2.4.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime for instant
    comparison.

    PRD §2.4 pins the "three fractional digits" serialization only for
    `created_at` / `updated_at` (and §2.2 for `api_request_timestamp`); the
    serialization format of the other clock-stamped fields (`received_at`,
    `quote_submitted_at`, `released_at`, `promised_return_at`, ...) is not
    pinned by the PRD — §2.5 even writes the clock instant without fractional
    digits. Tests therefore compare instants, not exact strings.
    """
    v = str(value).strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def _assert_has_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be int, got {data.get('version')!r}"


def _assert_has_ledger_fields(data: dict):
    """Append-only: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "ledger entity must not expose updated_at"
    assert "version" not in data, "ledger entity must not expose version"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------

def assert_customer(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert isinstance(data["contract_tat_hours"], int)
    assert isinstance(data["tat_penalty_rate_cents_per_hour"], int)
    assert isinstance(data["tat_penalty_cap_pct"], int)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["penalty_delay_rule"] in ("ADJUSTED", "CALENDAR")
    assert isinstance(data["current_exposure_cents"], int)
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] == "ACTIVE"


def assert_part(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["ata_chapter"], str) and data["ata_chapter"]
    assert isinstance(data["is_rotable"], bool)
    assert isinstance(data["cmm_reference"], str) and data["cmm_reference"]
    assert isinstance(data["replacement_value_cents"], int)
    assert isinstance(data["ber_threshold_pct"], int)
    assert isinstance(data["warranty_cycle_limit"], int)
    assert isinstance(data["warranty_month_limit"], int)
    assert isinstance(data["flat_overhaul_price_cents"], int)


def assert_directive_record(data: dict):
    _assert_has_ledger_fields(data)
    assert data["directive_type"] in ("AD", "SB")
    assert isinstance(data["directive_number"], str) and data["directive_number"]
    assert isinstance(data["mandatory"], bool)
    assert isinstance(data["description"], str)


def assert_unit(data: dict):
    _assert_has_common_fields(data)
    assert data["ownership"] in ("SHOP", "CUSTOMER")
    assert data["condition_status"] in ("SERVICEABLE", "UNSERVICEABLE", "SCRAPPED")
    assert data["custody_status"] in (
        "OFF_SITE", "IN_SHOP", "AWAITING_SHIPMENT", "SHIPPED", "IN_POOL", "ON_LEASE",
    )
    assert isinstance(data["total_cycles"], int)
    assert isinstance(data["cycles_since_overhaul"], int)
    assert isinstance(data["manufactured_at"], str) and data["manufactured_at"]


def assert_work_order(data: dict):
    _assert_has_common_fields(data)
    assert data["work_scope"] in ("REPAIR", "OVERHAUL", "WARRANTY_REWORK")
    assert data["status"] in (
        "TEARDOWN_IN_PROGRESS", "AWAITING_QUOTE", "QUOTE_SUBMITTED",
        "REPAIR_IN_PROGRESS", "AWAITING_PARTS", "READY_FOR_TEST",
        "TEST_PASSED", "RELEASED", "CLOSED", "CANCELLED", "BER_SCRAPPED",
    )
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["test_attempt_count"], int)
    assert isinstance(data["open_discrepancy_count"], int)
    assert isinstance(data["parts_charge_cents"], int)


def assert_discrepancy_card(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["finding_text"], str) and data["finding_text"]
    assert data["severity"] in ("MINOR", "MAJOR")
    assert data["status"] in ("OPEN", "DISPOSITIONED", "CLOSED")


def assert_directive_compliance(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["directive_number"], str)
    assert data["directive_type"] in ("AD", "SB")
    assert isinstance(data["mandatory"], bool)
    assert data["status"] in ("PENDING", "COMPLIED", "NOT_APPLICABLE")


def assert_parts_requisition(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["part_number"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["requested_source"] in ("OEM", "PMA")
    assert data["status"] in (
        "REQUESTED", "PMA_PENDING_CUSTOMER", "APPROVED",
        "SOURCE_REJECTED", "PMA_REJECTED", "RECEIVED", "ISSUED",
    )


def assert_test_cell(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["supported_ata_chapters"], list)
    assert isinstance(data["hourly_rate_cents"], int)


def assert_test_cell_booking(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["test_cell_id"], str)
    assert isinstance(data["work_order_id"], str)
    assert is_iso8601_timestamp(data["start_time"])
    assert is_iso8601_timestamp(data["end_time"])
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")
    assert isinstance(data["fee_cents"], int)


def assert_release_certificate(data: dict):
    _assert_has_ledger_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["cert_number"], str) and data["cert_number"].startswith("8130-")
    assert isinstance(data["signed_by"], str) and data["signed_by"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert data["status"] == "ISSUED"


def assert_exchange_agreement(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["part_id"], str)
    assert data["status"] in ("OPEN", "FULFILLED", "CLOSED", "DEFAULTED")


def assert_lease_agreement(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["daily_rate_cents"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("ACTIVE", "RETURNED")


def assert_warranty_claim(data: dict):
    _assert_has_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["original_work_order_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["claim_cycles_used"], int)
    assert isinstance(data["claim_months_used"], int)
    assert isinstance(data["failure_description"], str)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "DENIED", "SETTLED")


def assert_invoice(data: dict):
    _assert_has_common_fields(data)
    assert data["source_type"] in ("WORK_ORDER", "EXCHANGE", "LEASE")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("ISSUED", "PAID")
    assert is_iso8601_timestamp(data["issued_at"])


def assert_traceability_record(data: dict):
    _assert_has_ledger_fields(data)
    assert isinstance(data["unit_id"], str)
    assert data["event_type"] in (
        "BIRTH", "INDUCT", "DISPOSITION", "RELEASE_OVERHAUL", "RELEASE_REPAIR",
        "SCRAP", "EXCHANGE_OUT", "CORE_IN", "LEASE_OUT", "LEASE_RETURN",
        "WARRANTY_INDUCT",
    )
    assert is_iso8601_timestamp(data["event_at"])
