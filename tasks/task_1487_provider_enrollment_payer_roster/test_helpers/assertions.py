"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _assert_common(data: dict):
    """PRD §2.4 common property set: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_date(value, field):
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"{field} must be a YYYY-MM-DD date string, got {value!r}"
    )


def _assert_optional_date(value, field):
    if value is not None:
        _assert_date(value, field)


def _assert_optional_timestamp(value, field):
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"


def assert_timestamp_second(value: str, expected_second_prefix: str):
    """Compare an ISO 8601 timestamp at second precision (PRD §2.6: clock
    comparisons happen at second precision). expected_second_prefix is the
    first 19 chars, e.g. '2026-11-29T00:00:00'."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 timestamp: {value!r}"
    assert value[:19] == expected_second_prefix, (
        f"Expected second {expected_second_prefix}, got {value!r}"
    )


def assert_practice_group(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["group_npi"], str) and data["group_npi"]


def assert_provider(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_group_id", ""))
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["specialty"], str) and data["specialty"]
    assert data["status"] in ("ACTIVE", "TERMINATED")
    _assert_optional_date(data.get("termination_date"), "termination_date")
    assert data.get("termination_reason") is None or isinstance(data["termination_reason"], str)
    assert isinstance(data["recoupment_balance_cents"], int)
    assert data["recoupment_balance_cents"] >= 0


def assert_payer(data: dict):
    _assert_common(data)
    assert isinstance(data["payer_code"], str) and data["payer_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["is_medicare"], bool)
    assert data["effective_date_policy"] in ("APPROVAL_DATE", "RETRO_90")
    assert isinstance(data["claims_hold_enabled"], bool)
    assert isinstance(data["revalidation_interval_days"], int)
    assert data["revalidation_interval_days"] > 0


def assert_caqh_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["status"] in ("NEVER_ATTESTED", "ATTESTED", "DUE", "LAPSED")
    _assert_optional_timestamp(data.get("last_attested_at"), "last_attested_at")
    _assert_optional_timestamp(data.get("due_at"), "due_at")


def assert_enrollment_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("payer_id", ""))
    assert data["enrollment_scope"] in ("GROUP_LINK", "INDIVIDUAL")
    _assert_date(data["requested_effective_date"], "requested_effective_date")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "PENDING_INFO", "APPROVED", "REJECTED", "WITHDRAWN",
    )
    _assert_optional_timestamp(data.get("submitted_at"), "submitted_at")
    _assert_optional_timestamp(data.get("approved_at"), "approved_at")
    assert data.get("info_request_reason") is None or isinstance(data["info_request_reason"], str)
    assert data.get("decision_reason") is None or isinstance(data["decision_reason"], str)


def assert_enrollment_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("payer_id", ""))
    if data.get("source_application_id") is not None:
        assert is_valid_uuid(data["source_application_id"])
    if data.get("source_roster_line_id") is not None:
        assert is_valid_uuid(data["source_roster_line_id"])
    assert data["enrollment_scope"] in ("GROUP_LINK", "INDIVIDUAL")
    assert data["benefit_assignment"] in ("GROUP", "INDIVIDUAL")
    _assert_date(data["effective_date"], "effective_date")
    _assert_optional_date(data.get("termination_date"), "termination_date")
    assert is_iso8601_timestamp(data.get("last_revalidation_completed_at", ""))
    _assert_date(data["revalidation_due_date"], "revalidation_due_date")
    _assert_date(data["revalidation_window_start"], "revalidation_window_start")
    assert isinstance(data["gross_impacted_cents"], int) and data["gross_impacted_cents"] >= 0
    assert isinstance(data["net_recouped_cents"], int) and data["net_recouped_cents"] >= 0
    assert data["status"] in ("ACTIVE", "PENDING_REVALIDATION", "DEACTIVATED", "TERMINATED")


def assert_delegation_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_group_id", ""))
    assert is_valid_uuid(data.get("payer_id", ""))
    _assert_date(data["effective_date"], "effective_date")
    _assert_date(data["expiry_date"], "expiry_date")
    assert data["status"] in ("ACTIVE", "EXPIRED", "TERMINATED")


def assert_roster_file(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert data["status"] in (
        "SUBMITTED", "CONFIRMED", "PARTIALLY_CONFIRMED", "RECONCILED", "SUPERSEDED",
    )
    for field in ("total_lines", "pending_count", "confirmed_count",
                  "rejected_count", "discrepancy_count", "superseded_count"):
        assert isinstance(data[field], int) and data[field] >= 0, field


def assert_roster_rollup_invariant(data: dict):
    """PRD §3.5: the five status counts always sum to total_lines."""
    total = (
        data["pending_count"] + data["confirmed_count"] + data["rejected_count"]
        + data["discrepancy_count"] + data["superseded_count"]
    )
    assert total == data["total_lines"], (
        f"rollup buckets {total} != total_lines {data['total_lines']}"
    )


def assert_roster_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("roster_file_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["line_index"], int) and data["line_index"] >= 0
    assert data["action"] in ("ADD", "TERM")
    _assert_date(data["expected_effective_date"], "expected_effective_date")
    _assert_optional_date(data.get("confirmed_effective_date"), "confirmed_effective_date")
    assert data["status"] in ("PENDING", "CONFIRMED", "REJECTED", "DISCREPANCY", "SUPERSEDED")
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("payer_id", ""))
    _assert_date(data["service_date"], "service_date")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("RELEASED", "HELD", "DENIED", "RECOUPED")
    assert data.get("denial_reason") is None or data["denial_reason"] in (
        "PAYER_HOLD_DISABLED", "ENROLLMENT_TERMINATED", "ENROLLMENT_DEACTIVATED",
    )
    assert isinstance(data["recoupment_fee_cents"], int) and data["recoupment_fee_cents"] >= 0
