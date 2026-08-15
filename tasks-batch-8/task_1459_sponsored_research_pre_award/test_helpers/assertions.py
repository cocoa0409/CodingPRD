"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_funding_opportunity(data: dict):
    _assert_common_fields(data, "FundingOpportunity")
    assert isinstance(data["sponsor_code"], str) and data["sponsor_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["activity_codes_allowed"], list)
    assert is_iso8601_timestamp(data["sponsor_deadline_at"])
    assert is_iso8601_timestamp(data["internal_deadline_at"])
    assert isinstance(data["internal_lead_days"], int)
    assert data["status"] in ("PUBLISHED", "INTAKE_CLOSED")


def assert_principal_investigator(data: dict):
    _assert_common_fields(data, "PrincipalInvestigator")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["rank"] in ("ASSISTANT", "ASSOCIATE", "FULL", "RESEARCH_SCIENTIST")
    assert isinstance(data["delinquent_report_count"], int)
    assert isinstance(data["is_eligible"], bool)
    assert data["is_eligible"] == (data["delinquent_report_count"] == 0), (
        "is_eligible must hold exactly when delinquent_report_count is zero (PRD §3.1)"
    )


def assert_proposal(data: dict):
    _assert_common_fields(data, "Proposal")
    assert is_valid_uuid(data["opportunity_id"])
    assert isinstance(data["pi_id"], str) and data["pi_id"]
    assert data["activity_code"] in (
        "RESEARCH_ON_CAMPUS", "RESEARCH_OFF_CAMPUS", "INSTRUCTION", "OTHER_SPONSORED",
    )
    assert isinstance(data["total_direct_cents"], int)
    assert isinstance(data["total_indirect_cents"], int)
    assert isinstance(data["total_request_cents"], int)
    assert isinstance(data["is_cost_share_adequate"], bool)
    assert data["compliance_posture"] in ("CLEAR", "REVIEW_PENDING", "BLOCKED")
    assert data["status"] in (
        "DRAFT", "BUDGET_LOCKED", "ROUTED", "RETURNED_FOR_REVISION",
        "INSTITUTIONALLY_APPROVED", "SUBMITTED", "JIT_REQUESTED", "NEGOTIATING",
        "AWARDED", "SETUP_COMPLETE", "WITHDRAWN", "DECLINED",
    )


def assert_budget_line(data: dict):
    _assert_common_fields(data, "BudgetLine")
    assert data["category"] in (
        "PERSONNEL", "EQUIPMENT", "TRAVEL", "PARTICIPANT_SUPPORT", "MATERIALS",
        "PUBLICATION", "CONSULTANT", "SUBAWARD", "TUITION", "OTHER_DIRECT",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["counts_toward_mtdc"], bool)


def assert_budget_snapshot(data: dict):
    _assert_common_fields(data, "BudgetSnapshot")
    assert isinstance(data["snapshot_index"], int) and data["snapshot_index"] >= 1
    assert data["fa_base_type"] in ("MTDC", "TDC")
    assert data["rate_source"] in ("FINAL_RATE", "PROVISIONAL_RATE")
    assert isinstance(data["total_direct_cents"], int)
    assert isinstance(data["total_indirect_cents"], int)
    assert isinstance(data["total_request_cents"], int)
    assert data["total_request_cents"] == (
        data["total_direct_cents"] + data["total_indirect_cents"]
    ), "total_request_cents must equal direct + indirect (PRD §3.3)"
    assert isinstance(data["per_line_indirect"], list)
    assert data["status"] in ("CURRENT", "SUPERSEDED")


def assert_fa_rate_agreement(data: dict):
    _assert_common_fields(data, "FaRateAgreement")
    assert data["rate_type"] in (
        "ON_CAMPUS_RESEARCH", "OFF_CAMPUS_RESEARCH", "INSTRUCTION", "OTHER_SPONSORED",
    )
    assert 0 < data["rate_pct"] <= 100
    assert data["status"] in ("PROVISIONAL", "FINAL")


def assert_cost_share_commitment(data: dict):
    _assert_common_fields(data, "CostShareCommitment")
    assert data["source_type"] in (
        "DEPARTMENT", "COLLEGE", "CENTRAL_OFFICE", "THIRD_PARTY_IN_KIND",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PLEDGED", "APPROVED", "RELEASED", "WITHDRAWN")


def assert_compliance_review(data: dict):
    _assert_common_fields(data, "ComplianceReview")
    assert data["review_type"] in ("IRB", "IACUC", "EXPORT_CONTROL", "CONFLICT_OF_INTEREST")
    assert data["status"] in (
        "PENDING", "INFO_REQUESTED", "APPROVED", "EXPIRED", "DISAPPROVED", "CANCELLED",
    )


def assert_subrecipient_org(data: dict):
    _assert_common_fields(data, "SubrecipientOrg")
    assert isinstance(data["uei"], str) and data["uei"]
    assert data["single_audit_status"] in ("CURRENT", "DELINQUENT", "NOT_REQUIRED", "MISSING")
    assert isinstance(data["risk_score"], int)
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")


def assert_subrecipient_commitment(data: dict):
    _assert_common_fields(data, "SubrecipientCommitment")
    assert isinstance(data["subaward_amount_cents"], int)
    assert data["subaward_amount_cents"] > 0
    assert data["status"] in ("DRAFT", "VERIFIED", "STALE", "VOIDED")


def assert_negotiation_offer(data: dict):
    _assert_common_fields(data, "NegotiationOffer")
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["origin"] in ("SPONSOR", "INSTITUTION")
    assert isinstance(data["offered_total_cents"], int) and data["offered_total_cents"] > 0
    assert data["status"] in ("PROPOSED", "ACCEPTED", "DECLINED", "VOIDED")


def assert_submission_package(data: dict):
    """SubmissionPackage is append-only (PRD §2.5): id + created_at only among
    the system-managed fields; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "SubmissionPackage.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "SubmissionPackage.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, "SubmissionPackage must not carry updated_at"
    assert "version" not in data, "SubmissionPackage must not carry version"
    assert isinstance(data["portal_confirmation_code"], str)
    assert data["portal_confirmation_code"]
    assert data["status"] == "ACCEPTED_BY_PORTAL"


def assert_award_handoff(data: dict):
    _assert_common_fields(data, "AwardHandoff")
    assert isinstance(data["budget_verified"], bool)
    assert isinstance(data["compliance_verified"], bool)
    assert isinstance(data["subrecipient_verified"], bool)
    assert data["status"] in ("DRAFT", "READY", "BLOCKED", "HANDED_OFF")


def assert_proposal_invariants(data: dict):
    """Domain invariants that must hold after any proposal read (PRD §3.3)."""
    assert data["total_request_cents"] == (
        data["total_direct_cents"] + data["total_indirect_cents"]
    ), "total_request_cents must equal direct + indirect"
    assert data["total_direct_cents"] >= 0
    assert data["total_indirect_cents"] >= 0
    assert data["total_approved_cost_share_cents"] >= 0
    assert data["total_effective_cost_share_cents"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
