"""Entity assertions and domain invariant checkers for the PRD contract."""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AuditStatus,
    BoardConfigStatus,
    BoardDecision,
    CeCategory,
    CeVerificationStatus,
    ComplainantType,
    ComplaintStatus,
    CredentialType,
    DegreeLevel,
    EncumbranceStatus,
    EvidenceRequestStatus,
    LicenseApplicationStatus,
    LicenseStatus,
    MonitoringAgreementStatus,
    MultistatePrivilegeStatus,
    NurseStatus,
    Pathway,
    PrivilegeVariant,
    ProceedingStatus,
    ProgramApprovalStatus,
    RecordClass,
    RenewalStatus,
    ReportChannel,
    ReportKind,
    ReportStatus,
    SanctionTier,
    ScreeningStatus,
    SourceEntityType,
    ViolationCategory,
)


def _members(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


# ---------------------------------------------------------------------------
# System-managed properties shared by all twelve resource families (PRD §2.6)
# ---------------------------------------------------------------------------

def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """`id` is a bare UUID, both timestamps are ISO 8601, `version` starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no type prefix: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_created_fresh(data: Dict[str, Any]) -> None:
    """A newly created record carries version 1 and equal timestamps."""
    assert_common_fields(data, expected_version=1)
    assert data["created_at"] == data["updated_at"], (
        f"A freshly created record has updated_at == created_at, got "
        f"{data['created_at']} vs {data['updated_at']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_board_config(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code must be two uppercase letters"
    assert isinstance(data["board_name"], str) and data["board_name"]
    assert isinstance(data["compact_member"], bool)
    assert data["status"] in _members(BoardConfigStatus)
    for money_field in (
        "renewal_base_fee_cents",
        "late_fee_tier1_cents",
        "late_fee_tier2_cents",
        "reinstatement_fee_cents",
        "failed_audit_surcharge_cents",
    ):
        assert isinstance(data[money_field], int), f"{money_field} must be integer cents"
    for bp_field in ("audit_sample_rate_bp", "revocation_vote_threshold_bp",
                     "majority_vote_threshold_bp"):
        assert 0 <= data[bp_field] <= 10000, f"{bp_field} must be within 0 through 10000"
    assert isinstance(data["disqualifying_offense_codes"], list)
    assert isinstance(data["phi_authorization_required"], bool)
    assert data["ce_hours_required"] > 0, "ce_hours_required must be greater than zero"


def assert_education_program(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["state_board_config_id"])
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert data["degree_level"] in _members(DegreeLevel)
    assert data["approval_status"] in _members(ProgramApprovalStatus)
    assert 0 <= data["nclex_first_time_pass_rate_bp"] <= 10000
    assert isinstance(data["approval_expires_on"], str) and data["approval_expires_on"]


def assert_nurse(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["home_board_config_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_year"], int)
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["declared_primary_state"], str) and len(data["declared_primary_state"]) == 2
    assert isinstance(data["residency_evidence"], list)
    assert data["status"] in _members(NurseStatus)
    for counter in ("fee_credit_cents", "fee_paid_total_cents", "prior_discipline_count",
                    "atd_participation_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )


def assert_license_application(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["nurse_id"])
    assert is_valid_uuid(data["board_config_id"])
    assert data["pathway"] in _members(Pathway)
    assert data["credential_type"] in _members(CredentialType)
    assert data["status"] in _members(LicenseApplicationStatus)
    assert data["screening_status"] in _members(ScreeningStatus)
    assert data["board_decision"] in _members(BoardDecision)
    assert isinstance(data["screening_offense_records"], list)
    assert isinstance(data["deficiency_cycle_count"], int) and data["deficiency_cycle_count"] >= 0
    assert isinstance(data["prior_license_verified"], bool)


def assert_license(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["nurse_id"])
    assert is_valid_uuid(data["issuing_board_config_id"])
    assert is_valid_uuid(data["source_application_id"])
    assert data["credential_type"] in _members(CredentialType)
    assert isinstance(data["license_number"], str) and data["license_number"], (
        "the system mints a board-assigned license_number"
    )
    assert data["license_status"] in _members(LicenseStatus)
    assert data["encumbrance_status"] in _members(EncumbranceStatus)
    assert data["multistate_privilege_status"] in _members(MultistatePrivilegeStatus)
    if data.get("privilege_variant") is not None:
        assert data["privilege_variant"] in _members(PrivilegeVariant)
    assert isinstance(data["practice_restriction_codes"], list)
    assert isinstance(data["open_encumbrance_count"], int) and data["open_encumbrance_count"] >= 0
    assert isinstance(data["issued_on"], str) and data["issued_on"]
    assert isinstance(data["expires_on"], str) and data["expires_on"]


def assert_renewal_application(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["license_id"])
    assert data["renewal_status"] in _members(RenewalStatus)
    assert data["audit_status"] in _members(AuditStatus)
    assert isinstance(data["practice_hour_periods"], list)
    for cents in ("fee_applied_cents", "fee_paid_cents"):
        assert isinstance(data[cents], int) and data[cents] >= 0, (
            f"{cents} must be a non-negative integer number of cents"
        )
    assert isinstance(data["late_days"], int) and data["late_days"] >= 0
    assert isinstance(data["doc_request_cycle_count"], int) and data["doc_request_cycle_count"] >= 0


def assert_ce_record(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["renewal_application_id"])
    assert isinstance(data["provider_code"], str) and data["provider_code"]
    assert isinstance(data["provider_accredited"], bool)
    assert data["category"] in _members(CeCategory)
    assert isinstance(data["minutes"], int) and data["minutes"] > 0, (
        "contact minutes must be greater than zero"
    )
    assert data["verification_status"] in _members(CeVerificationStatus)
    assert_quarter_hour_quantised(data["credit_hours"])


def assert_complaint(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["license_id"])
    assert data["complainant_type"] in _members(ComplainantType)
    assert data["violation_category"] in _members(ViolationCategory)
    assert data["status"] in _members(ComplaintStatus)
    assert isinstance(data["allegation_codes"], list)
    assert isinstance(data["employer_custodian_codes"], list)
    assert isinstance(data["received_at"], str) and data["received_at"]


def assert_evidence_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["complaint_id"])
    assert data["record_class"] in _members(RecordClass)
    assert isinstance(data["custodian_code"], str) and data["custodian_code"]
    assert data["status"] in _members(EvidenceRequestStatus)
    assert isinstance(data["page_count"], int) and data["page_count"] >= 0
    assert data["hold_start_at"] < data["hold_end_at"], (
        "a records hold's start must be strictly before its end"
    )


def assert_monitoring_agreement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["nurse_id"])
    assert is_valid_uuid(data["complaint_id"])
    assert data["status"] in _members(MonitoringAgreementStatus)
    assert isinstance(data["narcotic_access_restricted"], bool)
    assert isinstance(data["worksite_approval_required"], bool)
    assert isinstance(data["required_screens_per_quarter"], int)
    assert isinstance(data["compliance_report_count"], int) and data["compliance_report_count"] >= 0
    assert isinstance(data["missed_screen_count"], int) and data["missed_screen_count"] >= 0
    assert data["start_date"] <= data["end_date"], (
        "a monitoring agreement's start_date must be at or before its end_date"
    )
    assert isinstance(data["approved_by_user_id"], str) and data["approved_by_user_id"]


def assert_disciplinary_proceeding(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["complaint_id"])
    assert isinstance(data["presiding_member_user_id"], str) and data["presiding_member_user_id"]
    assert isinstance(data["seated_member_user_ids"], list)
    assert isinstance(data["recused_member_user_ids"], list)
    assert data["presiding_member_user_id"] not in data["seated_member_user_ids"], (
        "the presiding member is removed from seated_member_user_ids"
    )
    assert data["status"] in _members(ProceedingStatus)
    assert isinstance(data["continuance_count"], int) and data["continuance_count"] >= 0
    assert isinstance(data["votes"], list)
    assert data["sanction_floor_tier"] is None or data["sanction_floor_tier"] in _members(SanctionTier)
    assert data["adopted_sanction_tier"] in _members(SanctionTier)
    assert isinstance(data["ordered_restriction_codes"], list)


def assert_notification_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subject_nurse_id"])
    assert data["source_entity_type"] in _members(SourceEntityType)
    assert is_valid_uuid(data["source_entity_id"])
    assert data["channel"] in _members(ReportChannel)
    assert data["report_kind"] in _members(ReportKind)
    assert data["status"] in _members(ReportStatus)
    assert isinstance(data["basis_code"], str) and data["basis_code"]
    assert isinstance(data["queued_at"], str) and data["queued_at"]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_quarter_hour_quantised(credit_hours: float) -> None:
    """Continuing-education credit is quantised to quarter-hour increments."""
    assert credit_hours is not None, "credit_hours must be stored on the record"
    scaled = round(float(credit_hours) * 100)
    assert abs(float(credit_hours) * 100 - scaled) < 0.5, (
        f"credit_hours must be carried to 2 decimal places, got {credit_hours!r}"
    )
    assert scaled % 25 == 0, (
        f"credit_hours must be a whole number of quarter hours, got {credit_hours!r}"
    )


def assert_fee_ledger_identity(nurse: Dict[str, Any],
                               renewals: List[Dict[str, Any]]) -> None:
    """`fee_paid_total_cents` equals `fee_credit_cents` plus every non-withdrawn
    filing's `fee_applied_cents`."""
    applied = sum(
        renewal["fee_applied_cents"]
        for renewal in renewals
        if renewal["renewal_status"] != "WITHDRAWN"
    )
    expected = nurse["fee_credit_cents"] + applied
    assert nurse["fee_paid_total_cents"] == expected, (
        f"Fee ledger drift: fee_paid_total_cents {nurse['fee_paid_total_cents']} != "
        f"fee_credit_cents {nurse['fee_credit_cents']} + applied {applied}"
    )


def assert_privilege_triple(license_data: Dict[str, Any], expected_status: str,
                            expected_variant: Optional[str] = None,
                            expected_basis_state: Optional[str] = None) -> None:
    """The three fields written by the compact privilege determination."""
    assert license_data["multistate_privilege_status"] == expected_status, (
        f"Expected multistate_privilege_status {expected_status}, "
        f"got {license_data['multistate_privilege_status']}"
    )
    if expected_variant is not None:
        assert license_data["privilege_variant"] == expected_variant, (
            f"Expected privilege_variant {expected_variant}, got {license_data['privilege_variant']}"
        )
    if expected_basis_state is not None:
        assert license_data["privilege_basis_state"] == expected_basis_state, (
            f"Expected privilege_basis_state {expected_basis_state}, "
            f"got {license_data['privilege_basis_state']}"
        )


def assert_license_dimensions(license_data: Dict[str, Any], license_status: str,
                              encumbrance_status: str) -> None:
    """Both status dimensions of a credential, checked independently."""
    assert license_data["license_status"] == license_status, (
        f"Expected license_status {license_status}, got {license_data['license_status']}"
    )
    assert license_data["encumbrance_status"] == encumbrance_status, (
        f"Expected encumbrance_status {encumbrance_status}, got {license_data['encumbrance_status']}"
    )


def assert_renewal_dimensions(renewal: Dict[str, Any], renewal_status: str,
                              audit_status: str) -> None:
    """Both status dimensions of a renewal filing, checked independently."""
    assert renewal["renewal_status"] == renewal_status, (
        f"Expected renewal_status {renewal_status}, got {renewal['renewal_status']}"
    )
    assert renewal["audit_status"] == audit_status, (
        f"Expected audit_status {audit_status}, got {renewal['audit_status']}"
    )


def assert_reports_match(reports: List[Dict[str, Any]], channel: str, basis_code: str,
                         expected_count: int) -> List[Dict[str, Any]]:
    """Filter queued reports by channel and basis and assert the exact count."""
    matched = [
        report for report in reports
        if report["channel"] == channel and report["basis_code"] == basis_code
    ]
    assert len(matched) == expected_count, (
        f"Expected {expected_count} report(s) on channel {channel} with basis_code "
        f"{basis_code}, got {len(matched)}"
    )
    return matched


def assert_pagination_meta(meta: Dict[str, Any], limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    """The four pagination values a list response carries in `meta`."""
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, f"Expected has_more {has_more}, got {meta['has_more']}"


def assert_decimal_equals(actual: Any, expected: float, label: str = "value") -> None:
    """Compare a two-decimal-place figure without floating-point noise."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - expected) < 0.005, (
        f"Expected {label} {expected:.2f}, got {actual!r}"
    )
