"""Entity assertions for the Copyright Licensing API.

Each assert_* helper validates the entity's PRD-required field shapes.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --- Top-level entities (PRD §2.4: id + created_at + updated_at + version) ---

def assert_rights_holder(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"RightsHolder.id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "RightsHolder.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "RightsHolder.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["holder_type"] in ("INDIVIDUAL", "ENTITY")
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert isinstance(data["jurisdiction"], str) and len(data["jurisdiction"]) == 2


def assert_work(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Work.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["title"], str)
    assert data["work_type"] in ("LITERARY", "MUSIC", "FILM", "SOFTWARE", "ARTWORK")
    assert is_iso8601_timestamp(data["creation_date"])
    assert is_valid_uuid(data["primary_owner_id"])
    assert isinstance(data["co_owners"], list)
    assert isinstance(data["primary_share_bps"], int)
    assert data["registration_status"] in ("DRAFT", "UNDER_REVIEW", "REGISTERED", "REJECTED")
    if data["registration_status"] == "REGISTERED":
        assert data.get("certificate_id") is not None
        assert is_iso8601_timestamp(data.get("certificate_issued_at", ""))
    elif data["registration_status"] in ("DRAFT", "UNDER_REVIEW", "REJECTED"):
        # PRD §2.4: certificate_id remains null until REGISTERED.
        assert data.get("certificate_id") is None
        assert data.get("certificate_issued_at") is None


def assert_license(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["work_id"])
    assert is_valid_uuid(data["licensor_id"])
    assert is_valid_uuid(data["licensee_id"])
    assert data["licensor_id"] != data["licensee_id"]
    assert isinstance(data["territory"], list) and len(data["territory"]) > 0
    assert is_iso8601_timestamp(data["term_start"])
    assert is_iso8601_timestamp(data["term_end"])
    assert isinstance(data["media_types"], list) and len(data["media_types"]) > 0
    for mt in data["media_types"]:
        assert mt in ("DIGITAL", "PRINT", "BROADCAST", "MERCHANDISE")
    assert data["exclusivity"] in ("EXCLUSIVE", "NON_EXCLUSIVE")
    assert isinstance(data["sublicense_allowed"], bool)
    assert data["revision_rights"] in ("NONE", "MINOR", "FULL")
    assert isinstance(data["fixed_fee_cents"], int) and data["fixed_fee_cents"] >= 0
    assert isinstance(data["revenue_share_bps"], int) and 0 <= data["revenue_share_bps"] <= 10000
    assert isinstance(data["minimum_guarantee_cents"], int) and data["minimum_guarantee_cents"] >= 0
    assert isinstance(data["advance_cents"], int) and data["advance_cents"] >= 0
    assert data["settlement_period"] in ("MONTHLY", "QUARTERLY", "ANNUAL")
    assert data["status"] in (
        "OFFERED", "COUNTERED", "ACCEPTED", "SIGNED", "EFFECTIVE",
        "TERMINATED", "EXPIRED", "WITHDRAWN",
    )
    assert isinstance(data["current_round"], int) and data["current_round"] >= 1
    assert isinstance(data["cumulative_advance_recouped_cents"], int)
    # PRD §2.4 server-set null-until rules:
    if data["status"] in ("OFFERED", "COUNTERED", "WITHDRAWN"):
        assert data.get("pinned_work_version") is None
    if data["status"] == "ACCEPTED":
        assert data.get("pinned_work_version") is not None


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["license_id"])
    assert isinstance(data["signing_order"], list) and len(data["signing_order"]) > 0
    for sid in data["signing_order"]:
        assert is_valid_uuid(sid)
    assert is_iso8601_timestamp(data["effective_date_target"])
    assert data["status"] in ("PENDING_SIGNATURES", "FULLY_SIGNED", "EFFECTIVE",
                               "TERMINATED", "SUPERSEDED")
    assert isinstance(data["signed_count"], int) and data["signed_count"] >= 0
    if data["status"] == "PENDING_SIGNATURES":
        assert data.get("fully_signed_at") is None
    else:
        assert is_iso8601_timestamp(data.get("fully_signed_at", ""))


def assert_royalty_statement(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["license_id"])
    assert is_iso8601_timestamp(data["period_start_at"])
    assert is_iso8601_timestamp(data["period_end_at"])
    assert isinstance(data["gross_revenue_cents"], int) and data["gross_revenue_cents"] >= 0
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["earned_royalty_cents"], int) and data["earned_royalty_cents"] >= 0
    assert isinstance(data["advance_recouped_cents"], int) and data["advance_recouped_cents"] >= 0
    assert isinstance(data["net_payable_cents"], int) and data["net_payable_cents"] >= 0
    assert data["status"] in ("DRAFT", "SETTLED", "REVERSED")


def assert_infringement_case(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["work_id"])
    assert is_valid_uuid(data["reporter_id"])
    assert is_valid_uuid(data["alleged_infringer_id"])
    assert isinstance(data["evidence_doc_ids"], list) and len(data["evidence_doc_ids"]) > 0
    assert data["review_stage"] in (
        "REPORTED", "OWNERSHIP_VERIFIED", "RESPONSE_RECEIVED",
        "UNDER_ARBITRATION", "RESOLVED", "DISMISSED",
    )


# --- Append-only sub-resources (PRD §2.4: id + created_at only — NO updated_at, NO version) ---

def assert_negotiation_round(data: dict):
    """NegotiationRound is append-only: only id + created_at + payload fields."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["license_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert is_valid_uuid(data["proposed_by_id"])
    assert data["action"] in ("OFFER", "COUNTER", "ACCEPT", "WITHDRAW")
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_signature(data: dict):
    """Signature is append-only: only id + created_at + payload fields."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["signer_id"])
    assert isinstance(data["signature_payload"], str)
    assert is_iso8601_timestamp(data["signed_at"])


def assert_rights_chain_event(data: dict):
    """RightsChainEvent is append-only: only id + created_at + payload fields."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["work_id"])
    assert data["event_type"] in (
        "REGISTERED", "LICENSE_SIGNED", "LICENSE_TERMINATED",
        "INFRINGEMENT_RESOLVED", "OWNERSHIP_TRANSFERRED",
    )
    assert isinstance(data["actor_id"], str)
    assert data["ref_entity"] in ("License", "Contract", "InfringementCase", "Work")
    assert isinstance(data["ref_id"], str)


def assert_external_event(data: dict):
    """ExternalEvent is append-only: only id + created_at + payload fields."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["source"] in ("PAYMENT", "E_SIGN", "COPYRIGHT_AUTHORITY", "DISTRIBUTION_PLATFORM")
    assert isinstance(data["event_type"], str)
    assert isinstance(data["external_event_id"], str)
    assert isinstance(data.get("applied"), bool)


def assert_audit_log(data: dict):
    """AuditLog is append-only: only id + created_at + payload fields."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["subject_entity"], str)
    assert isinstance(data["subject_id"], str)
    assert data["change_type"] in (
        "LICENSE_CHANGED", "CONTRACT_AMENDED", "DISPUTE_LOGGED",
        "ROYALTY_REVERSED", "RIGHTS_CONFLICT_DETECTED",
    )


# --- Domain invariant checkers ---

def assert_ownership_shares_total(work: dict):
    """PRD §2.8 / §3.1: primary_share_bps + sum(co_owners[i].share_bps) == 10000."""
    total = work["primary_share_bps"] + sum(
        co["share_bps"] for co in work.get("co_owners", [])
    )
    assert total == 10000, (
        f"Ownership shares must total 10000 bps, got {total} "
        f"(primary={work['primary_share_bps']}, co_owners={work.get('co_owners')})"
    )


def assert_advance_recoupment_invariant_ge_zero(license_data: dict):
    """PRD §3.7: cumulative_advance_recouped_cents must be >= 0."""
    assert license_data["cumulative_advance_recouped_cents"] >= 0
    assert license_data["cumulative_advance_recouped_cents"] <= license_data["advance_cents"], (
        f"cumulative_advance_recouped_cents={license_data['cumulative_advance_recouped_cents']} "
        f"cannot exceed advance_cents={license_data['advance_cents']}"
    )
