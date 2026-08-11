"""Entity assertions and domain invariant checkers (PRD §2.5, §2.8, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AircraftRegistryStatus,
    DepositPurpose,
    DepositStatus,
    DisbursementPurpose,
    DisbursementStatus,
    DocType,
    DocumentStatus,
    EscrowFileStatus,
    EscrowPosture,
    FilingStatus,
    FilingType,
    LienReleaseStatus,
    LienStatus,
    LienType,
    PartyType,
    ProrationMethod,
    TitleSearchStatus,
    TrustAgreementStatus,
    VerificationStatus,
)


def _assert_common(data: dict):
    """PRD §2.5 standard system-managed field set present on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_money(data: dict, field: str):
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        f"{field} must be integer cents, got {data.get(field)!r}"
    )


def assert_aircraft(data: dict):
    _assert_common(data)
    assert isinstance(data["n_number"], str) and data["n_number"]
    assert isinstance(data["serial_number"], str)
    assert isinstance(data["make_model"], str)
    assert isinstance(data["year"], int)
    assert 1900 <= data["year"] <= 2100
    assert isinstance(data["is_international_registry"], bool)
    assert data["registry_status"] in {s.value for s in AircraftRegistryStatus}


def assert_party(data: dict):
    _assert_common(data)
    assert data["party_type"] in {t.value for t in PartyType}
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["is_citizenship_verified"], bool)


def assert_escrow_file(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["aircraft_id"])
    assert is_valid_uuid(data["buyer_party_id"])
    assert is_valid_uuid(data["seller_party_id"])
    assert isinstance(data["requires_trust"], bool)
    _assert_money(data, "purchase_price_cents")
    assert data["purchase_price_cents"] > 0
    _assert_money(data, "annual_registration_fee_cents")
    assert data["annual_registration_fee_cents"] >= 0
    assert data["proration_method"] in {m.value for m in ProrationMethod}
    assert isinstance(data["expected_close_date"], str)
    assert data["status"] in {s.value for s in EscrowFileStatus}
    assert data["posture"] in {p.value for p in EscrowPosture}
    for field in (
        "escrow_fee_cents",
        "proration_amount_cents",
        "buyer_amount_due_cents",
        "total_funded_cents",
        "escrow_balance_cents",
        "seller_net_proceeds_cents",
    ):
        _assert_money(data, field)


def assert_escrow_money_invariants(data: dict):
    """PRD §2.8/§3.5 live-figure invariants that must hold after any operation."""
    assert data["total_funded_cents"] >= 0
    assert data["escrow_balance_cents"] >= 0
    assert data["escrow_balance_cents"] <= data["total_funded_cents"]


def assert_statement(data: dict):
    """PRD §4 closing-statement read: full pinned field set, integer cents."""
    for field in (
        "purchase_price_cents",
        "proration_amount_cents",
        "escrow_fee_cents",
        "buyer_amount_due_cents",
        "total_funded_cents",
        "escrow_balance_cents",
        "seller_net_proceeds_cents",
    ):
        _assert_money(data, field)


def assert_trust_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["aircraft_id"])
    assert is_valid_uuid(data["trustee_party_id"])
    assert isinstance(data["beneficiary_name"], str) and data["beneficiary_name"]
    assert data["beneficiary_citizenship"] in ("US_CITIZEN", "NON_US_CITIZEN")
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert data["status"] in {s.value for s in TrustAgreementStatus}


def assert_title_search(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["escrow_file_id"])
    assert data["status"] in {s.value for s in TitleSearchStatus}
    assert isinstance(data["finding_count"], int) and data["finding_count"] >= 0


def assert_lien(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["escrow_file_id"])
    assert is_valid_uuid(data["aircraft_id"])
    assert is_valid_uuid(data["title_search_id"])
    assert is_valid_uuid(data["lienor_party_id"])
    assert isinstance(data["lienor_name"], str) and data["lienor_name"]
    _assert_money(data, "original_amount_cents")
    assert data["original_amount_cents"] > 0
    _assert_money(data, "amount_paid_cents")
    _assert_money(data, "outstanding_cents")
    assert data["lien_type"] in {t.value for t in LienType}
    assert isinstance(data["filed_at"], str)
    assert data["status"] in {s.value for s in LienStatus}


def assert_lien_release(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lien_id"])
    assert data["status"] in {s.value for s in LienReleaseStatus}


def assert_deposit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["escrow_file_id"])
    assert is_valid_uuid(data["payer_party_id"])
    _assert_money(data, "amount_cents")
    assert data["amount_cents"] > 0
    assert data["purpose"] in {p.value for p in DepositPurpose}
    assert data["status"] in {s.value for s in DepositStatus}


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["escrow_file_id"])
    assert is_valid_uuid(data["payee_party_id"])
    _assert_money(data, "amount_cents")
    assert data["amount_cents"] > 0
    assert data["purpose"] in {p.value for p in DisbursementPurpose}
    assert data["status"] in {s.value for s in DisbursementStatus}
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_filing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["escrow_file_id"])
    assert is_valid_uuid(data["aircraft_id"])
    assert data["filing_type"] in {t.value for t in FilingType}
    assert data["status"] in {s.value for s in FilingStatus}
    assert data["verification_status"] in {v.value for v in VerificationStatus}


def assert_closing_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["escrow_file_id"])
    assert data["doc_type"] in {t.value for t in DocType}
    assert isinstance(data["required_signer_party_ids"], list)
    assert isinstance(data["signed_party_ids"], list)
    assert data["status"] in {s.value for s in DocumentStatus}
