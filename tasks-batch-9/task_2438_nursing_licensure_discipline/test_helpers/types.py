"""Domain types for the Nursing Licensure & Discipline API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Every one of the twelve resource families carries the four
system-managed properties `id`, `created_at`, `updated_at` and `version`.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    LICENSURE_ANALYST = "LicensureAnalyst"
    INVESTIGATOR = "Investigator"
    BOARD_MEMBER = "BoardMember"
    MONITORING_COORDINATOR = "MonitoringCoordinator"
    APPLICANT = "Applicant"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class BoardConfigStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProgramApprovalStatus(str, Enum):
    APPROVED = "APPROVED"
    PROVISIONAL = "PROVISIONAL"
    PROBATION = "PROBATION"
    WITHDRAWN = "WITHDRAWN"


class DegreeLevel(str, Enum):
    PN = "PN"
    ADN = "ADN"
    BSN = "BSN"
    MSN = "MSN"


class NurseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENCUMBERED = "ENCUMBERED"
    REVOKED = "REVOKED"


class EvidenceType(str, Enum):
    DRIVER_LICENSE = "DRIVER_LICENSE"
    TAX_RETURN = "TAX_RETURN"
    VOTER_REGISTRATION = "VOTER_REGISTRATION"


class LicenseApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEFICIENT = "DEFICIENT"
    QUALIFICATION_VERIFIED = "QUALIFICATION_VERIFIED"
    SCREENING_IN_PROGRESS = "SCREENING_IN_PROGRESS"
    SCREENING_FLAGGED = "SCREENING_FLAGGED"
    BOARD_REVIEW = "BOARD_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    ISSUED = "ISSUED"


class ScreeningStatus(str, Enum):
    NOT_ORDERED = "NOT_ORDERED"
    REQUESTED = "REQUESTED"
    CLEARED = "CLEARED"
    DISQUALIFYING = "DISQUALIFYING"


class BoardDecision(str, Enum):
    NONE = "NONE"
    APPROVED_UNCONDITIONAL = "APPROVED_UNCONDITIONAL"
    APPROVED_WITH_MONITORING = "APPROVED_WITH_MONITORING"
    DENIED = "DENIED"


class Pathway(str, Enum):
    EXAMINATION = "EXAMINATION"
    ENDORSEMENT = "ENDORSEMENT"


class CredentialType(str, Enum):
    RN = "RN"
    LPN = "LPN"
    APRN = "APRN"
    NURSE_AIDE = "NURSE_AIDE"


class AprnRole(str, Enum):
    NP = "NP"
    CRNA = "CRNA"
    CNS = "CNS"
    CNM = "CNM"


class NclexResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TAKEN = "NOT_TAKEN"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    EXPIRED = "EXPIRED"
    LAPSED = "LAPSED"
    SURRENDERED = "SURRENDERED"


class EncumbranceStatus(str, Enum):
    CLEAR = "CLEAR"
    INVESTIGATION_PENDING = "INVESTIGATION_PENDING"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class MultistatePrivilegeStatus(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    SINGLE_STATE = "SINGLE_STATE"
    MULTISTATE = "MULTISTATE"
    PRIVILEGE_REVOKED = "PRIVILEGE_REVOKED"


class PrivilegeVariant(str, Enum):
    RESIDENCY_DECLARED = "RESIDENCY_DECLARED"
    RESIDENCY_EVIDENCED = "RESIDENCY_EVIDENCED"


class RenewalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CE_DEFICIENT = "CE_DEFICIENT"
    CE_VERIFIED = "CE_VERIFIED"
    RENEWED = "RENEWED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AuditStatus(str, Enum):
    NOT_SELECTED = "NOT_SELECTED"
    SELECTED = "SELECTED"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    DOCS_SUBMITTED = "DOCS_SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CeCategory(str, Enum):
    LIVE_CONTACT = "LIVE_CONTACT"
    SELF_STUDY = "SELF_STUDY"
    IN_SERVICE = "IN_SERVICE"
    ACADEMIC = "ACADEMIC"


class CeVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    CONSOLIDATED = "CONSOLIDATED"
    INVESTIGATION_OPEN = "INVESTIGATION_OPEN"
    EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"
    ATD_OFFERED = "ATD_OFFERED"
    ATD_ACTIVE = "ATD_ACTIVE"
    REFERRED_FOR_HEARING = "REFERRED_FOR_HEARING"
    PROCEEDING_OPENED = "PROCEEDING_OPENED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class JurisdictionFinding(str, Enum):
    PENDING = "PENDING"
    JURISDICTION_CONFIRMED = "JURISDICTION_CONFIRMED"
    NO_JURISDICTION = "NO_JURISDICTION"
    DUPLICATE = "DUPLICATE"


class ComplainantType(str, Enum):
    PATIENT = "PATIENT"
    EMPLOYER = "EMPLOYER"
    SELF_REPORT = "SELF_REPORT"
    BOARD_INITIATED = "BOARD_INITIATED"
    OTHER_STATE_BOARD = "OTHER_STATE_BOARD"


class ViolationCategory(str, Enum):
    PRACTICE_STANDARD = "PRACTICE_STANDARD"
    SUBSTANCE_USE = "SUBSTANCE_USE"
    FRAUD = "FRAUD"
    BOUNDARY_VIOLATION = "BOUNDARY_VIOLATION"
    CRIMINAL_CONDUCT = "CRIMINAL_CONDUCT"


class ComplaintDisposition(str, Enum):
    DISMISS = "DISMISS"
    OFFER_ATD = "OFFER_ATD"
    REFER_TO_PROCEEDING = "REFER_TO_PROCEEDING"


class RecordClass(str, Enum):
    EMPLOYER_PERSONNEL = "EMPLOYER_PERSONNEL"
    EMPLOYER_INCIDENT = "EMPLOYER_INCIDENT"
    PATIENT_CHART = "PATIENT_CHART"
    PHARMACY_DISPENSING = "PHARMACY_DISPENSING"


class EvidenceRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PRODUCED = "PRODUCED"
    WITHDRAWN = "WITHDRAWN"


class MonitoringAgreementStatus(str, Enum):
    OFFERED = "OFFERED"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    SUSPENDED_PENDING_REVIEW = "SUSPENDED_PENDING_REVIEW"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    TERMINATED = "TERMINATED"


class MonitoringEventType(str, Enum):
    COMPLIANCE_REPORT = "COMPLIANCE_REPORT"
    MISSED_SCREEN = "MISSED_SCREEN"
    BREACH = "BREACH"
    COMPLETION = "COMPLETION"


class ProceedingStatus(str, Enum):
    NOTICED = "NOTICED"
    HEARING_CONVENED = "HEARING_CONVENED"
    CONTINUED = "CONTINUED"
    DELIBERATION = "DELIBERATION"
    ORDER_ISSUED = "ORDER_ISSUED"
    DISMISSED_BY_PANEL = "DISMISSED_BY_PANEL"


class HearingEventType(str, Enum):
    CONVENE = "CONVENE"
    CONTINUE = "CONTINUE"
    CLOSE_HEARING = "CLOSE_HEARING"
    REOPEN = "REOPEN"


class SanctionTier(str, Enum):
    NONE = "NONE"
    REPRIMAND = "REPRIMAND"
    FINE = "FINE"
    PROBATION = "PROBATION"
    PRACTICE_RESTRICTION = "PRACTICE_RESTRICTION"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class ReportChannel(str, Enum):
    NPDB = "NPDB"
    INTERSTATE_COMPACT = "INTERSTATE_COMPACT"
    NURSE_AIDE_REGISTRY = "NURSE_AIDE_REGISTRY"


class ReportKind(str, Enum):
    INITIAL = "INITIAL"
    REVISION = "REVISION"
    VOID = "VOID"


class ReportStatus(str, Enum):
    QUEUED = "QUEUED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    VOID = "VOID"


class SourceEntityType(str, Enum):
    LICENSE = "LICENSE"
    DISCIPLINARY_PROCEEDING = "DISCIPLINARY_PROCEEDING"
    MONITORING_AGREEMENT = "MONITORING_AGREEMENT"
    LICENSE_APPLICATION = "LICENSE_APPLICATION"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every family carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class StateBoardConfig(TypedDict):
    id: str
    state_code: str
    board_name: str
    compact_member: bool
    status: str
    ce_hours_required: float
    ce_self_study_cap_hours: float
    ce_in_service_cap_hours: float
    ce_carry_over_cap_hours: float
    practice_hours_required: int
    practice_lookback_months: int
    renewal_period_months: int
    renewal_grace_period_days: int
    lapse_after_grace_days: int
    audit_sample_rate_bp: int
    criminal_lookback_years: int
    disqualifying_offense_codes: List[str]
    renewal_base_fee_cents: int
    late_fee_tier1_cents: int
    late_fee_tier2_cents: int
    reinstatement_fee_cents: int
    failed_audit_surcharge_cents: int
    phi_authorization_required: bool
    max_concurrent_custodian_holds: int
    monitoring_clearance_gap_days: int
    revocation_vote_threshold_bp: int
    majority_vote_threshold_bp: int
    created_at: str
    updated_at: str
    version: int


class EducationProgram(TypedDict):
    id: str
    state_board_config_id: str
    program_code: str
    program_name: str
    degree_level: str
    approval_status: str
    nclex_first_time_pass_rate_bp: int
    approval_expires_on: str
    created_at: str
    updated_at: str
    version: int


class Nurse(TypedDict):
    id: str
    home_board_config_id: str
    full_name: str
    birth_year: int
    ssn_last4: str
    declared_primary_state: str
    residency_evidence: List[Dict[str, Any]]
    status: str
    fee_credit_cents: int
    fee_paid_total_cents: int
    prior_discipline_count: int
    atd_participation_count: int
    created_at: str
    updated_at: str
    version: int


class LicenseApplication(TypedDict):
    id: str
    nurse_id: str
    board_config_id: str
    pathway: str
    credential_type: str
    education_program_id: Optional[str]
    aprn_role: Optional[str]
    nclex_result: str
    base_license_id: Optional[str]
    prior_license_state: Optional[str]
    prior_license_number: Optional[str]
    prior_license_verified: bool
    status: str
    screening_status: str
    screening_offense_records: List[Dict[str, Any]]
    deficiency_cycle_count: int
    board_decision: str
    reason_note: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    nurse_id: str
    issuing_board_config_id: str
    source_application_id: str
    credential_type: str
    aprn_role: Optional[str]
    base_license_id: Optional[str]
    license_number: str
    license_status: str
    encumbrance_status: str
    multistate_privilege_status: str
    privilege_variant: Optional[str]
    privilege_basis_state: Optional[str]
    practice_restriction_codes: List[str]
    open_encumbrance_count: int
    issued_on: str
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class RenewalApplication(TypedDict):
    id: str
    license_id: str
    renewal_status: str
    audit_status: str
    period_start_on: str
    period_end_on: str
    attested_practice_hours: int
    carry_over_hours_claimed: float
    ce_credit_hours_provisional: Optional[float]
    ce_credit_hours_audited: Optional[float]
    verified_practice_hours: Optional[int]
    practice_hour_periods: List[Dict[str, Any]]
    audit_risk_score: Optional[float]
    doc_request_cycle_count: int
    fee_applied_cents: int
    fee_paid_cents: int
    late_days: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CeRecord(TypedDict):
    id: str
    renewal_application_id: str
    provider_code: str
    provider_accredited: bool
    category: str
    minutes: int
    credit_hours: float
    completion_date: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    license_id: str
    complainant_type: str
    violation_category: str
    incident_date: str
    allegation_codes: List[str]
    employer_custodian_codes: List[str]
    status: str
    jurisdiction_finding: str
    consolidated_into_complaint_id: Optional[str]
    triaged_by_user_id: Optional[str]
    investigator_user_id: Optional[str]
    received_at: str
    disposition_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceRequest(TypedDict):
    id: str
    complaint_id: str
    record_class: str
    custodian_code: str
    hold_start_at: str
    hold_end_at: str
    phi_authorization_id: Optional[str]
    status: str
    page_count: int
    produced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringAgreement(TypedDict):
    id: str
    nurse_id: str
    complaint_id: str
    start_date: str
    end_date: str
    narcotic_access_restricted: bool
    required_screens_per_quarter: int
    worksite_approval_required: bool
    approved_by_user_id: str
    status: str
    compliance_report_count: int
    missed_screen_count: int
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplinaryProceeding(TypedDict):
    id: str
    complaint_id: str
    presiding_member_user_id: str
    seated_member_user_ids: List[str]
    recused_member_user_ids: List[str]
    hearing_date: str
    notice_period_days: int
    noticed_at: str
    status: str
    continuance_count: int
    votes: List[Dict[str, Any]]
    sanction_floor_tier: str
    adopted_sanction_tier: str
    ordered_restriction_codes: List[str]
    order_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NotificationReport(TypedDict):
    id: str
    subject_nurse_id: str
    source_entity_type: str
    source_entity_id: str
    channel: str
    report_kind: str
    basis_code: str
    payload_summary: str
    status: str
    queued_at: str
    transmitted_at: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
