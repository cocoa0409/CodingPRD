"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_UNIT_STATUSES = {"STABILIZED", "EXEMPT", "DECONTROLLED"}
_REG_STATUSES = {"ACTIVE", "SUPERSEDED"}
_TENANCY_STATUSES = {"ACTIVE", "ENDED"}
_PETITION_STATUSES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION",
                      "HEARING_SCHEDULED", "GRANTED", "PARTIAL", "DENIED"}
_HEARING_STATUSES = {"SCHEDULED", "HELD"}
_CLAIM_STATUSES = {"OPEN", "INVESTIGATING", "SUBSTANTIATED", "DISMISSED", "RESTORED"}
_BUYOUT_STATUSES = {"DRAFT", "FILED", "RESCINDED", "COMPLETED"}
_EXEMPTION_STATUSES = {"REQUESTED", "APPROVED", "DENIED"}
_PENALTY_STATUSES = {"ASSESSED", "CONFIRMED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_landlord(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["business_license_no"], str)
    assert isinstance(data["escrow_committed_cents"], int)
    assert data["escrow_committed_cents"] >= 0, "escrow_committed_cents must never be negative"


def assert_tenant(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_hearing_officer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["active"], bool)


def assert_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["landlord_id"])
    assert isinstance(data["address"], str)
    assert isinstance(data["bedrooms"], int) and data["bedrooms"] >= 0
    assert isinstance(data["base_rent_cents"], int) and data["base_rent_cents"] > 0
    assert isinstance(data["current_lawful_rent_cents"], int)
    assert isinstance(data["banked_pct"], (int, float))
    assert data["stabilization_status"] in _UNIT_STATUSES
    assert isinstance(data["decrease_active"], bool)


def assert_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["registration_year"], int)
    assert isinstance(data["declared_rent_cents"], int) and data["declared_rent_cents"] > 0
    assert data["status"] in _REG_STATUSES


def assert_tenancy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data["monthly_rent_cents"], int)
    assert data["status"] in _TENANCY_STATUSES


def assert_aga(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["effective_year"], int)
    assert isinstance(data["aga_pct"], (int, float))


def assert_petition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["landlord_id"])
    assert data["petition_type"] in {"CAPITAL_IMPROVEMENT", "HARDSHIP"}
    assert data["status"] in _PETITION_STATUSES
    assert isinstance(data["granted_amount_cents"], int)
    assert isinstance(data["revision_count"], int)


def assert_hearing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["petition_id"])
    assert is_valid_uuid(data["officer_id"])
    assert data["status"] in _HEARING_STATUSES


def assert_service_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert data["claim_type"] in {"HEAT", "WATER", "MAINTENANCE", "PEST"}
    assert data["severity"] in {"MINOR", "SUBSTANTIAL"}
    assert data["status"] in _CLAIM_STATUSES
    assert isinstance(data["decrease_amount_cents"], int)


def assert_buyout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["landlord_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data["offer_amount_cents"], int) and data["offer_amount_cents"] > 0
    assert isinstance(data["relocation_amount_cents"], int) and data["relocation_amount_cents"] >= 0
    assert isinstance(data["disclosure_acknowledged"], bool)
    assert data["status"] in _BUYOUT_STATUSES


def assert_exemption(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["exemption_type"] in {"SUBSTANTIAL_REHAB", "OWNER_OCCUPIED",
                                      "VACANCY_DECONTROL", "NEW_CONSTRUCTION"}
    assert data["status"] in _EXEMPTION_STATUSES


def assert_penalty(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["landlord_id"])
    assert data["penalty_type"] in {"OVERCHARGE", "LATE_REGISTRATION", "FAILURE_TO_FILE"}
    assert isinstance(data["assessed_amount_cents"], int)
    assert data["status"] in _PENALTY_STATUSES


def assert_escrow_conservation(landlord: dict, filed_relocation_total: int):
    """§2.9: escrow_committed_cents must equal the sum of relocation_amount_cents
    across the landlord's currently-FILED buyouts."""
    assert landlord["escrow_committed_cents"] == filed_relocation_total, (
        f"escrow_committed_cents {landlord['escrow_committed_cents']} != "
        f"expected FILED-relocation total {filed_relocation_total}"
    )
