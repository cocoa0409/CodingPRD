"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the system-managed fields and the entity's own
fields. Append-only AuditEvent carries id + created_at only.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ACT_TYPES = {"ACKNOWLEDGMENT", "JURAT", "OATH", "COPY_CERTIFICATION", "SIGNATURE_WITNESS"}


def _assert_common(data: dict):
    """Common fields for primary resources: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["ron_allowed"], bool)
    assert isinstance(data["bond_minimum_cents"], int) and data["bond_minimum_cents"] >= 0
    assert data["commission_term_months"] in (48, 60, 96, 120)
    assert isinstance(data["renewal_grace_days"], int) and data["renewal_grace_days"] >= 0
    assert isinstance(data["session_act_fee_cap_cents"], int) and data["session_act_fee_cap_cents"] >= 0
    assert isinstance(data["ron_surcharge_cap_cents"], int) and data["ron_surcharge_cap_cents"] >= 0


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["act_type"] in _ACT_TYPES
    assert isinstance(data["max_act_fee_cents"], int) and data["max_act_fee_cents"] >= 0


def assert_notary(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["enotary_requested"], bool)
    assert isinstance(data["enotary_authorized"], bool)
    assert data["status"] in (
        "APPLIED", "COMMISSIONED", "ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED", "REJECTED",
    )
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert isinstance(data["lifetime_fees_collected_cents"], int) and data["lifetime_fees_collected_cents"] >= 0


def assert_bond(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["notary_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] >= 0
    assert is_iso8601_timestamp(data["coverage_start_at"])
    assert is_iso8601_timestamp(data["coverage_end_at"])
    assert isinstance(data["claims_paid_cents"], int) and data["claims_paid_cents"] >= 0
    assert isinstance(data["remaining_cents"], int)
    assert data["status"] in ("PENDING", "ACTIVE", "EXHAUSTED", "CANCELLED")


def assert_bond_ledger_invariant(data: dict):
    """face_value_cents == claims_paid_cents + remaining_cents (PRD §3.3 / §3.8)."""
    assert data["face_value_cents"] == data["claims_paid_cents"] + data["remaining_cents"], (
        f"Bond ledger invariant violated: face {data['face_value_cents']} != "
        f"claims {data['claims_paid_cents']} + remaining {data['remaining_cents']}"
    )


def assert_renewal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["notary_id"])
    assert is_valid_uuid(data["new_bond_id"])
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")
    assert isinstance(data["filed_within_grace"], bool)


def assert_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["notary_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert isinstance(data["requested_surcharge_cents"], int) and data["requested_surcharge_cents"] >= 0
    assert data["fee_basis"] in ("PER_ACT", "AGGREGATE")
    assert data["status"] in (
        "SCHEDULED", "IDENTITY_PENDING", "ID_VERIFIED", "ID_FAILED",
        "ACTIVE", "COMPLETED", "TERMINATED", "EXPIRED",
    )
    assert isinstance(data["surcharge_charged_cents"], int)
    assert isinstance(data["act_fees_total_cents"], int)
    assert isinstance(data["session_total_fee_cents"], int)


def assert_signer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["kba_passed"], bool)
    assert isinstance(data["credential_analysis_passed"], bool)
    assert data["id_status"] in ("UNVERIFIED", "VERIFIED", "FAILED")


def assert_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["signer_id"])
    assert data["act_type"] in _ACT_TYPES
    assert isinstance(data["requested_fee_cents"], int) and data["requested_fee_cents"] >= 0
    assert isinstance(data["capped_fee_cents"], int) and data["capped_fee_cents"] >= 0
    assert data["status"] in ("PENDING", "NOTARIZED", "REFUSED")


def assert_journal_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["notary_id"])
    assert data["act_type"] in _ACT_TYPES
    assert isinstance(data["signer_name"], str)
    assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0
    assert data["status"] in ("POSTED", "AMENDED", "VOID")


def assert_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["notary_id"])
    assert data["category"] in ("FRAUD", "RECORDKEEPING", "FEE_OVERCHARGE", "OTHER")
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] >= 0
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "INFO_REQUESTED", "SUBSTANTIATED", "DISMISSED", "SETTLED",
    )
    assert isinstance(data["settled_claim_cents"], int) and data["settled_claim_cents"] >= 0


def assert_audit_event(data: dict):
    """AuditEvent is append-only: id + created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "audit event id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "AuditEvent must NOT carry updated_at"
    assert "version" not in data, "AuditEvent must NOT carry version"
    assert data["entity_type"] in (
        "NOTARY", "SESSION", "JOURNAL_ENTRY", "COMPLAINT", "BOND", "RENEWAL",
    )
    assert data["actor_role"] in ("NOTARY", "COMMISSION_AUTHORITY", "SYSTEM")
    assert isinstance(data["action"], str) and len(data["action"]) > 0
