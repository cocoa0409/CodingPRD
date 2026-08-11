"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_rep(data: dict):
    _assert_common_fields(data, "RegisteredRep")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["crd_number"], str) and data["crd_number"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert is_valid_uuid(data.get("registered_rep_id", ""))
    assert data["customer_type"] in ("INDIVIDUAL", "LEGAL_ENTITY")
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert data["country_risk_tier"] in ("LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert isinstance(data.get("is_pep"), bool)


def assert_account(data: dict):
    _assert_common_fields(data, "BrokerageAccount")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["product_set"], list)
    assert data["lifecycle_status"] in (
        "PENDING_APPROVAL", "OPEN", "RESTRICTED", "CLOSED", "DECLINED",
    )
    assert data["aml_posture"] in ("STANDARD", "ELEVATED", "SEVERE")
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert data["risk_variant_used"] in ("INITIAL", "ONGOING")
    assert data["exposure_tier"] in ("T1", "T2", "T3")
    assert isinstance(data["open_alert_count"], int)
    assert isinstance(data["open_case_count"], int)
    assert isinstance(data["has_suspicion_flag"], bool)


def assert_account_invariants(data: dict):
    """Domain invariants that must hold for any account read (PRD §3.3, §3.5)."""
    if data.get("risk_tier") != "PROHIBITED":
        assert 0 <= data["risk_score"] <= 100, "risk_score clamped to [0, 100]"
    assert data["exposure_30d_amount"] >= 0
    assert data["wire_velocity_30d_amount"] >= 0
    assert data["open_alert_count"] >= 0
    assert data["open_case_count"] >= 0


def assert_document(data: dict):
    _assert_common_fields(data, "IdentificationDocument")
    assert data["doc_type"] in ("GOVERNMENT_ID", "FORMATION_DOC", "PROOF_OF_ADDRESS", "W9")
    assert isinstance(data["document_number"], str) and data["document_number"]
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED", "SUPERSEDED")


def assert_certification(data: dict):
    _assert_common_fields(data, "BeneficialOwnershipCertification")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in ("DRAFT", "CERTIFIED", "SUPERSEDED")
    assert isinstance(data.get("no_25pct_owner_attested"), bool)


def assert_owner(data: dict):
    _assert_common_fields(data, "BeneficialOwner")
    assert is_valid_uuid(data.get("certification_id", ""))
    assert 0 < data["ownership_pct"] <= 100
    assert isinstance(data.get("is_control_person"), bool)
    assert isinstance(data.get("is_entity_owner"), bool)


def assert_edd_review(data: dict):
    _assert_common_fields(data, "EDDReview")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["status"] in ("PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "REFRESH_DUE")
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)


def assert_transaction(data: dict):
    _assert_common_fields(data, "SecurityTransaction")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["txn_type"] in (
        "DEPOSIT_CERT", "DEPOSIT_DTC", "BUY", "SELL", "WIRE_OUT", "JOURNAL",
    )
    assert data["status"] in ("POSTED", "FLAGGED", "CLEARED", "ESCALATED", "REVERSED")
    assert isinstance(data.get("is_low_priced"), bool)


def assert_rule(data: dict):
    _assert_common_fields(data, "MonitoringRule")
    assert data["rule_code"] in (
        "LPS_LIQUIDATION", "LPS_DEPOSIT_LIQUIDATE", "WIRE_VELOCITY", "STRUCTURING",
    )
    assert data["threshold_amount"] > 0
    assert isinstance(data["window_days"], int) and data["window_days"] >= 1
    assert isinstance(data.get("enabled"), bool)


def assert_alert(data: dict):
    _assert_common_fields(data, "MonitoringAlert")
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert data["status"] in ("NEW", "UNDER_REVIEW", "ESCALATED_TO_CASE", "CLOSED_NO_ACTION")
    assert isinstance(data["severity"], int)


def assert_case(data: dict):
    _assert_common_fields(data, "AMLCase")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["priority"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in (
        "OPEN", "INVESTIGATING", "SAR_RECOMMENDED", "DECIDED_FILED",
        "DECIDED_NO_FILE", "CLOSED", "REOPENED",
    )


def assert_sar_filing(data: dict):
    _assert_common_fields(data, "SARFiling")
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["status"] in ("DRAFT", "FILED", "SUPERSEDED")
    assert isinstance(data["filing_deadline"], str)
    assert isinstance(data.get("continuing_review_count"), int)


def assert_fincen_request(data: dict):
    _assert_common_fields(data, "FinCENRequest314A")
    assert isinstance(data["request_reference"], str) and data["request_reference"]
    assert data["status"] in ("RECEIVED", "SCAN_COMPLETE", "RESPONSE_SUBMITTED", "OVERDUE")
    assert isinstance(data.get("match_count"), int)


def assert_match(data: dict):
    _assert_common_fields(data, "Match314A")
    assert is_valid_uuid(data.get("request_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["match_basis"] in ("TAX_ID_EXACT", "NAME_DOB", "NAME_EXACT")
    assert data["status"] in ("PENDING_REVIEW", "CONFIRMED", "FALSE_POSITIVE", "RESOLVED")


def assert_deposit(data: dict):
    _assert_common_fields(data, "PhysicalCertificateDeposit")
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert data["status"] in (
        "RECEIVED", "ELIGIBILITY_REVIEW", "AUTHENTICITY_REVIEW", "CLEARANCE_HOLD",
        "READY_TO_ACCEPT", "ACCEPTED", "REJECTED", "REJECTED_SUSPICIOUS", "RESUBMITTED",
    )
    assert isinstance(data.get("is_low_priced"), bool)


def assert_lost_stolen_entry(data: dict):
    _assert_common_fields(data, "LostStolenCertificateEntry")
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_engagement(data: dict):
    _assert_common_fields(data, "AuditEngagement")
    assert data["scope_unit"] in (
        "AML_PROGRAM", "CIP_PROCESS", "SANCTIONS_SCREENING", "TRANSACTION_MONITORING",
    )
    assert data["status"] in ("PLANNED", "FIELDWORK", "REPORTED", "CLOSED")


def assert_finding(data: dict):
    _assert_common_fields(data, "AuditFinding")
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert data["severity"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    assert data["status"] in ("OPEN", "REMEDIATION_SUBMITTED", "REMEDIATED", "ACCEPTED_RISK")
    assert isinstance(data.get("is_overdue"), bool)
