"""Entity assertions and domain invariant checkers for the Pole-Attachment &
Joint-Use Management API. Uses the framework's generic format checkers
internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """The four system-managed fields every resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_pole_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["owner_category"] in ("ELECTRIC_UTILITY", "ILEC", "MUNICIPAL")
    assert isinstance(data["annual_rental_rate_cents"], int)
    assert isinstance(data["make_ready_labor_rate_cents_per_hour"], int)


def assert_pole(data: dict):
    _assert_common(data)
    assert isinstance(data["usable_communication_space_inches"], int)
    assert isinstance(data["occupied_space_inches"], int)
    assert isinstance(data["reserved_space_inches"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert_pole_space_invariants(data)


def assert_pole_space_invariants(data: dict):
    """Space accounting conservation invariants (PRD §2.8)."""
    assert data["occupied_space_inches"] >= 0, "occupied space must be non-negative"
    assert data["reserved_space_inches"] >= 0, "reserved space must be non-negative"


def assert_attacher(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["cin"], str) and len(data["cin"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["account_balance_cents"], int)
    assert data["account_balance_cents"] >= 0, "account balance must be non-negative"


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "SURVEYED", "ESTIMATE_ISSUED", "ESTIMATE_ACCEPTED",
        "ESTIMATE_REJECTED", "ESTIMATE_EXPIRED", "PERMIT_GRANTED",
        "PERMIT_DENIED", "WITHDRAWN",
    )
    assert data["purpose"] in ("FIBER", "COAX", "POWER_SUPPLY", "WIRELESS")
    assert isinstance(data["requested_space_inches"], int)
    assert isinstance(data["requested_position_inches"], int)


def assert_attachment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "TRANSFERRED", "ABANDONED")
    assert isinstance(data["allotted_space_inches"], int)
    assert isinstance(data["position_inches"], int)
    assert isinstance(data["authorized"], bool)


def assert_finding(data: dict):
    _assert_common(data)
    assert data["status"] in ("FLAGGED", "LEGALIZED", "REMOVED", "DISPUTED")
    assert isinstance(data["discovered_space_inches"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["back_rental_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["invoice_type"] in ("MAKE_READY", "ANNUAL_RENTAL", "UNAUTHORIZED")
    assert data["status"] in ("ISSUED", "PAID", "VOID", "OVERDUE")
    assert isinstance(data["amount_cents"], int)


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "UNDER_REVIEW", "INFO_REQUESTED",
        "RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "WITHDRAWN",
    )
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
