"""Entity assertions and domain invariant checkers.

Each assert_* checks the PRD-named fields of one resource: identity and
common properties (id, created_at, updated_at, version) plus the fields the
PRD narratives attach to that resource. Monetary amounts are integer cents.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationStatus,
    AuditPackageStatus,
    CertificateStatus,
    ClawbackStatus,
    PenaltyMode,
    ProductionType,
    ProgramStatus,
    ResidencyStatus,
    SpendCategory,
    SpendEntryStatus,
    TransferStatus,
    TriggerReason,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_jurisdiction_program(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in ProgramStatus]
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["annual_cap_cents"], int) and data["annual_cap_cents"] > 0
    assert isinstance(data["minimum_qualified_spend_cents"], int)
    assert isinstance(data["allocated_credit_cents"], int)
    assert isinstance(data["remaining_cap_cents"], int)


def assert_program_ledger_invariant(program: dict):
    """The program cap ledger: allocated + remaining == annual cap (always)."""
    assert program["allocated_credit_cents"] + program["remaining_cap_cents"] == \
        program["annual_cap_cents"], (
            f"ledger invariant violated: {program['allocated_credit_cents']} + "
            f"{program['remaining_cap_cents']} != {program['annual_cap_cents']}"
        )


def assert_production_company(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]


def assert_production(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_company_id", ""))
    assert data["production_type"] in [t.value for t in ProductionType]
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] > 0


def assert_credit_buyer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_program_id", ""))
    assert data["status"] in [s.value for s in ApplicationStatus]
    for field in ("atl_qualified_cents", "btl_qualified_cents",
                  "capped_total_qualified_cents", "provisional_credit_cents",
                  "recomputed_credit_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["allocation_share_pct"], (int, float))


def assert_vendor(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert data["residency_status"] in [s.value for s in ResidencyStatus]


def assert_spend_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert data["category"] in [c.value for c in SpendCategory]
    assert data["status"] in [s.value for s in SpendEntryStatus]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["effective_amount_cents"], int)
    assert isinstance(data["is_resident_labor"], bool)


def assert_audit_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["status"] in [s.value for s in AuditPackageStatus]
    assert isinstance(data["cpa_user_id"], str) and data["cpa_user_id"]
    assert isinstance(data["exception_count"], int) and data["exception_count"] >= 0


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["status"] in [s.value for s in CertificateStatus]
    for field in ("issued_amount_cents", "remaining_amount_cents",
                  "redeemed_total_cents", "transferred_total_cents",
                  "overissued_exposure_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_transfer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert is_valid_uuid(data.get("buyer_id", ""))
    assert data["status"] in [s.value for s in TransferStatus]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["current_price_cents"], int)
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0


def assert_clawback_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert data["status"] in [s.value for s in ClawbackStatus]
    assert data["trigger_reason"] in [r.value for r in TriggerReason]
    assert data["penalty_mode"] in [m.value for m in PenaltyMode]
    assert isinstance(data["shortfall_amount_cents"], int)


def assert_milestone_present(milestones: list, name: str, date_prefix: str,
                             amount_cents: int):
    """A milestone entry must carry the PRD-named milestone token, the expected
    calendar date, and the expected whole-cent amount. Field naming inside a
    milestone object is an implementation choice, so membership is checked
    across the entry's values."""
    assert isinstance(milestones, list), "milestones must be an array"
    for entry in milestones:
        values = list(entry.values()) if isinstance(entry, dict) else []
        if name not in values:
            continue
        if amount_cents not in values:
            continue
        if any(isinstance(v, str) and v.startswith(date_prefix) for v in values):
            return
    raise AssertionError(
        f"no milestone matching ({name!r}, date {date_prefix!r}, "
        f"{amount_cents} cents) in {milestones!r}"
    )
