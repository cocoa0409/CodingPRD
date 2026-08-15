"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Timestamps are compared as instants
(parse-then-compare) so either whole-second or fractional-second renderings
of the same logical-clock instant satisfy the assertion.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value):
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_same_instant(actual, expected_iso, label="timestamp"):
    """Assert two timestamps denote the same instant regardless of rendering."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_title(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_code"], str) and data["title_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["content_type"] in ("FILM", "SERIES")
    assert isinstance(data["original_language"], str) and data["original_language"]
    assert isinstance(data["production_year"], int)
    assert isinstance(data["embargoed_territories"], list)
    for territory in data["embargoed_territories"]:
        assert isinstance(territory, str)


def assert_rights_holder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["payee_reference"], str) and data["payee_reference"]
    assert 0 < data["royalty_share_pct"] <= 100


def assert_platform(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["platform_type"] in ("SVOD", "AVOD", "TVOD", "EST")
    assert isinstance(data["metadata_spec_version"], str) and data["metadata_spec_version"]
    assert isinstance(data["required_asset_profiles"], list)
    assert len(data["required_asset_profiles"]) >= 1


def assert_rights_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert isinstance(data["rights_holder_id"], str)
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert isinstance(data["language_code"], str) and data["language_code"]
    assert data["window_type"] in ("THEATRICAL", "EST", "TVOD", "SVOD", "AVOD", "FREE_TV")
    assert is_iso8601_timestamp(data["sellable_from"])
    assert is_iso8601_timestamp(data["sellable_to"])
    assert data["slot_status"] in ("AVAILABLE", "ENCUMBERED", "WITHDRAWN", "EXPIRED")


def assert_package_line(line: dict):
    assert isinstance(line["slot_id"], str)
    assert is_iso8601_timestamp(line["license_start"])
    assert is_iso8601_timestamp(line["license_end"])
    assert isinstance(line["exclusive"], bool)
    assert line["fee_model"] in ("FLAT_FEE", "REVENUE_SHARE", "MINIMUM_GUARANTEE")
    assert line["line_status"] in ("PENDING", "OFFERED", "BLOCKED", "LICENSED", "NOT_SELECTED")
    assert "created_license_id" in line


def assert_avail_package(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["platform_id"], str)
    assert isinstance(data["name"], str)
    assert is_iso8601_timestamp(data["offer_expires_at"])
    assert data["package_status"] in ("DRAFT", "OFFERED", "ACCEPTED", "PARTIALLY_ACCEPTED",
                                      "DECLINED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert_package_line(line)
    assert isinstance(data["guaranteed_total_cents"], int)


def assert_license_agreement(data: dict):
    _assert_common_fields(data)
    assert "package_id" in data
    assert isinstance(data["platform_id"], str)
    assert isinstance(data["slot_id"], str)
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert isinstance(data["language_code"], str) and data["language_code"]
    assert data["window_type"] in ("THEATRICAL", "EST", "TVOD", "SVOD", "AVOD", "FREE_TV")
    assert is_iso8601_timestamp(data["license_start"])
    assert is_iso8601_timestamp(data["license_end"])
    assert isinstance(data["exclusive"], bool)
    assert data["fee_model"] in ("FLAT_FEE", "REVENUE_SHARE", "MINIMUM_GUARANTEE")
    assert data["proration_mode"] in ("DAILY_PRORATION", "MONTHLY_PRORATION")
    assert isinstance(data["allocated_fee_cents"], int)
    assert isinstance(data["recouped_cents"], int)
    assert isinstance(data["royalty_payable_cents"], int)
    assert isinstance(data["outstanding_recoupment_cents"], int)
    assert data["license_status"] in ("EXECUTED", "ACTIVE", "EXPIRED", "TERMINATED")


def assert_delivery_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["license_id"], str)
    assert isinstance(data["asset_manifest"], list) and len(data["asset_manifest"]) >= 1
    assert isinstance(data["metadata_spec_version"], str)
    assert data["delivery_status"] in ("QUEUED", "DELIVERED", "REJECTED")
    assert isinstance(data["missing_profiles"], list)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_takedown_notice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["license_id"], str)
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert data["notice_status"] in ("SCHEDULED", "EXECUTED", "CANCELLED")


def assert_revenue_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["license_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["gross_revenue_cents"], int) and data["gross_revenue_cents"] > 0
    assert isinstance(data["royalty_accrued_cents"], int)
    assert isinstance(data["recoupment_applied_cents"], int)
    assert isinstance(data["payable_cents"], int)
    assert data["report_status"] in ("SUBMITTED", "REVERSED")
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_royalty_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["rights_holder_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["attribution_mode"] in ("BY_REPORT_DATE", "BY_USAGE_PERIOD")
    assert isinstance(data["included_report_ids"], list)
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["studio_net_royalty_cents"], int)
    assert isinstance(data["holder_royalty_due_cents"], int)
    assert data["statement_status"] in ("DRAFT", "FINALIZED", "PAID")


def assert_recoupment_ledger_invariant(license_data: dict, submitted_reports: list):
    """Recoupment conservation: recouped + payable equals the sum of accrued
    royalty over the license's still-SUBMITTED reports."""
    accrued_total = sum(r["royalty_accrued_cents"] for r in submitted_reports)
    ledger_total = license_data["recouped_cents"] + license_data["royalty_payable_cents"]
    assert ledger_total == accrued_total, (
        f"recouped {license_data['recouped_cents']} + payable "
        f"{license_data['royalty_payable_cents']} != accrued over SUBMITTED reports "
        f"{accrued_total}"
    )
    expected_outstanding = max(
        0, license_data.get("minimum_guarantee_cents", 0) - license_data["recouped_cents"]
    )
    assert license_data["outstanding_recoupment_cents"] == expected_outstanding, (
        f"outstanding {license_data['outstanding_recoupment_cents']} != "
        f"max(0, guarantee - recouped) = {expected_outstanding}"
    )
