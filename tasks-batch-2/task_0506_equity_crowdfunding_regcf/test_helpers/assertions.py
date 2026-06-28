"""Entity assertions and domain invariant checkers for the Equity Crowdfunding Portal."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_issuer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "issuer id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["ein"], str)
    assert data["status"] in ("ONBOARDING", "VERIFIED", "BARRED")
    assert isinstance(data["bad_actor_flag"], bool)
    assert isinstance(data["total_raised_trailing_12mo_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_offering(data: dict):
    assert is_valid_uuid(data.get("id", "")), "offering id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be a valid UUID"
    assert data["regulation"] in ("REG_CF", "REG_A_TIER_1", "REG_A_TIER_2")
    assert data["security_type"] in ("EQUITY", "SAFE")
    assert data["status"] in ("DRAFT", "LIVE", "FUNDED", "FAILED", "CANCELLED")
    assert data["form_c_status"] in ("DRAFT", "SUBMITTED", "QUALIFIED", "REJECTED")
    assert isinstance(data["min_target_cents"], int)
    assert isinstance(data["max_target_cents"], int)
    assert isinstance(data["committed_amount_cents"], int)
    assert isinstance(data["swept_amount_cents"], int)
    assert isinstance(data["secondary_listing_enabled"], bool)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_investor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "investor id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["net_worth_cents"], int)
    assert data["accreditation_status"] in ("UNACCREDITED", "ACCREDITED")
    assert isinstance(data["annual_limit_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_accreditation_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "accreditation request id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("investor_id", "")), "investor_id must be a valid UUID"
    assert data["method"] in ("INCOME", "NET_WORTH", "THIRD_PARTY_LETTER")
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_investment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "investment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("offering_id", "")), "offering_id must be a valid UUID"
    assert is_valid_uuid(data.get("investor_id", "")), "investor_id must be a valid UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("COMMITTED", "RECONFIRMED", "ISSUED", "REFUNDED", "CANCELLED")
    assert isinstance(data["securities_issued"], int)
    assert isinstance(data["refund_amount_cents"], int)
    assert isinstance(data["reconfirm_required"], bool)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_escrow_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "escrow id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("offering_id", "")), "offering_id must be a valid UUID"
    assert isinstance(data["held_amount_cents"], int)
    assert isinstance(data["disbursed_amount_cents"], int)
    assert isinstance(data["refunded_amount_cents"], int)


def assert_cap_table_entry(data: dict):
    """CapTableEntry is immutable: id + created_at only, no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "cap-table entry id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("offering_id", "")), "offering_id must be a valid UUID"
    assert is_valid_uuid(data.get("investor_id", "")), "investor_id must be a valid UUID"
    assert is_valid_uuid(data.get("investment_id", "")), "investment_id must be a valid UUID"
    assert data["instrument"] in ("EQUITY", "SAFE")
    assert isinstance(data["principal_cents"], int)


def assert_investor_update(data: dict):
    assert is_valid_uuid(data.get("id", "")), "investor update id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("offering_id", "")), "offering_id must be a valid UUID"
    assert isinstance(data["title"], str)
    assert isinstance(data["body"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_escrow_conservation(escrow: dict, offering: dict):
    """Escrow conservation invariant (PRD §3.4): escrow held always equals the offering's
    committed amount."""
    assert escrow["held_amount_cents"] == offering["committed_amount_cents"], (
        f"escrow held {escrow['held_amount_cents']} must equal offering committed "
        f"{offering['committed_amount_cents']}"
    )
