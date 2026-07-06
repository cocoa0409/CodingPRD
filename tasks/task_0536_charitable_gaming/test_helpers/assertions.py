"""Entity assertions and domain invariant checkers for the Charitable Gaming PRD."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields carried by every resource (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_organization(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["nonprofit_type"] in ("501C3", "501C4", "501C8", "501C10", "501C19", "OTHER")
    assert isinstance(data["good_standing"], bool)
    assert isinstance(data["months_active"], int) and data["months_active"] >= 0
    assert data["eligibility_status"] in ("ELIGIBLE", "INELIGIBLE")


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["organization_id"], str)
    assert data["license_type"] in ("BINGO", "RAFFLE", "COMBINED")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["annual_prize_limit_cents"], int)
    assert isinstance(data["prize_committed_cents"], int)
    assert isinstance(data["prize_settled_cents"], int)
    assert isinstance(data["prize_allowance_remaining_cents"], int)
    assert isinstance(data["total_violation_points_active"], int)


def assert_occasion(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["occasion_type"] in ("BINGO", "RAFFLE")
    assert data["status"] in ("SCHEDULED", "HELD", "REPORTED", "CANCELLED")


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["business_name"], str)
    assert data["status"] in ("PENDING", "REGISTERED")


def assert_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_id"], str)
    assert data["equipment_type"] in ("BINGO_BLOWER", "FLASHBOARD", "RAFFLE_DRUM", "CARD_MINDER")
    assert data["status"] in ("REGISTERED", "RETIRED")


def assert_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["equipment_id"], str)
    assert isinstance(data["occasion_id"], str)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_financial_report(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_violation(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["violation_type"] in (
        "LATE_REPORT", "PRIZE_LIMIT_EXCEEDED", "UNREGISTERED_EQUIPMENT", "PROCEEDS_MISUSE"
    )
    assert data["source"] in ("MANUAL", "AUTO")
    assert data["status"] in ("OPEN", "WAIVED")


def assert_renewal(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "SUPERSEDED")


def assert_license_ledger_invariants(data: dict):
    """Prize ledger identity that must hold on any License (§3.5)."""
    assert (
        data["prize_allowance_remaining_cents"]
        == data["annual_prize_limit_cents"]
        - data["prize_committed_cents"]
        - data["prize_settled_cents"]
    ), "prize_allowance_remaining_cents must equal limit - committed - settled"
