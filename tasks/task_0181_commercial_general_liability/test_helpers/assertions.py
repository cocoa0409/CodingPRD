"""Entity assertions and domain invariant checkers for the CGL platform."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

POLICY_STATUSES = ["DRAFT", "BOUND", "IN_FORCE", "EXPIRED", "CANCELLED", "AUDIT_CLOSED"]
POSTURES = ["HEALTHY", "IMPAIRED", "EXHAUSTED"]
CLAIM_STATUSES = ["OPEN", "RESERVED", "PAID", "CLOSED", "DENIED", "REOPENED"]
ENDORSEMENT_STATUSES = ["ACTIVE", "SUPERSEDED", "VOID"]
ENDORSEMENT_SCOPES = ["ONGOING_OPS", "COMPLETED_OPS", "BOTH"]
CERTIFICATE_STATUSES = ["DRAFT", "ISSUED", "REVOKED", "EXPIRED"]
AUDIT_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "DISPUTED", "FINALIZED", "WAIVED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_insurer(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["naic_code"], str) and len(data["naic_code"]) > 0
    assert is_iso8601_timestamp(data["current_date"]), "current_date must be ISO 8601"
    assert isinstance(data["audit_waiver_threshold_cents"], int)


def assert_insured(data: dict):
    _assert_versioned(data)
    assert isinstance(data["insurer_id"], str)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["fein"], str) and len(data["fein"]) > 0
    assert data["primary_basis"] in ("PAYROLL", "SALES")


def assert_certificate_holder(data: dict):
    _assert_versioned(data)
    assert isinstance(data["insurer_id"], str)
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert isinstance(data["address"], str)


def assert_policy(data: dict):
    _assert_versioned(data)
    assert isinstance(data["insurer_id"], str)
    assert isinstance(data["insured_id"], str)
    assert isinstance(data["policy_number"], str) and len(data["policy_number"]) > 0
    assert data["coverage_trigger"] in ("OCCURRENCE", "CLAIMS_MADE")
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert isinstance(data["each_occurrence_limit_cents"], int)
    assert isinstance(data["general_aggregate_limit_cents"], int)
    assert isinstance(data["products_aggregate_limit_cents"], int)
    assert data["premium_basis"] in ("PAYROLL", "SALES")
    assert isinstance(data["rate_per_unit_cents"], int)
    assert isinstance(data["minimum_premium_cents"], int)
    assert isinstance(data["estimated_exposure_units"], int)
    assert data["status"] in POLICY_STATUSES, f"unexpected policy status {data['status']!r}"
    if data.get("posture") is not None:
        assert data["posture"] in POSTURES, f"unexpected posture {data['posture']!r}"


def assert_endorsement(data: dict):
    _assert_versioned(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["certificate_holder_id"], str)
    assert data["form_number"] in ("CG2010", "CG2037", "CG2010_2037")
    assert data["scope"] in ENDORSEMENT_SCOPES
    assert is_iso8601_timestamp(data["ai_effective_date"])
    assert data["status"] in ENDORSEMENT_STATUSES


def assert_certificate(data: dict):
    _assert_versioned(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["certificate_holder_id"], str)
    assert isinstance(data["names_as_additional_insured"], bool)
    assert data["status"] in CERTIFICATE_STATUSES


def assert_claim(data: dict):
    _assert_versioned(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["claimant_name"], str) and len(data["claimant_name"]) > 0
    assert data["loss_type"] in ("BODILY_INJURY", "PROPERTY_DAMAGE", "PRODUCTS_COMPLETED_OPS")
    assert is_iso8601_timestamp(data["occurrence_date"])
    assert is_iso8601_timestamp(data["reported_date"])
    assert data["aggregate_bucket"] in ("GENERAL", "PRODUCTS")
    assert isinstance(data["incurred_cents"], int)
    assert isinstance(data["recognized_incurred_cents"], int)
    assert data["status"] in CLAIM_STATUSES


def assert_claim_transaction(data: dict):
    """ClaimTransaction is an immutable ledger entry: id + created_at only,
    no updated_at and no version."""
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert data["txn_type"] in ("RESERVE_SET", "RESERVE_RELEASE", "PAYMENT", "RECOVERY")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["posted_sequence"], int)
    assert "updated_at" not in data, "ClaimTransaction must NOT carry updated_at"
    assert "version" not in data, "ClaimTransaction must NOT carry version"


def assert_premium_audit(data: dict):
    _assert_versioned(data)
    assert isinstance(data["policy_id"], str)
    assert data["audit_basis"] in ("PAYROLL", "SALES")
    assert isinstance(data["audited_exposure_units"], int)
    assert isinstance(data["revision_round"], int)
    assert data["status"] in AUDIT_STATUSES


def assert_exposure_record(data: dict):
    _assert_versioned(data)
    assert isinstance(data["premium_audit_id"], str)
    assert isinstance(data["class_code"], str)
    assert isinstance(data["basis_amount_units"], int)


def assert_loss_run(data: dict):
    _assert_versioned(data)
    assert isinstance(data["policy_id"], str)
    assert is_iso8601_timestamp(data["as_of_date"])
    assert isinstance(data["total_incurred_cents"], int)
    assert isinstance(data["general_incurred_cents"], int)
    assert isinstance(data["products_incurred_cents"], int)
    assert isinstance(data["claim_count"], int)
    assert isinstance(data["open_claim_count"], int)


def assert_aggregate_conservation(policy: dict, recognized_general: int, recognized_products: int):
    """Invariant: remaining + total recognized == limit, per bucket (PRD §3.6)."""
    assert policy["general_aggregate_remaining_cents"] + recognized_general == \
        policy["general_aggregate_limit_cents"], "general aggregate not conserved"
    assert policy["products_aggregate_remaining_cents"] + recognized_products == \
        policy["products_aggregate_limit_cents"], "products aggregate not conserved"
