"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the PRD's resource descriptions (PRD 2.4 common fields, PRD 3.x
per-resource chapters). `ComplianceEvent` is the PRD-declared append-only
exception: it carries only `id` and `created_at`, never `updated_at`/`version`
(PRD 2.4).
"""
from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class EntityType(str, Enum):
    CORPORATION = "CORPORATION"
    LLC = "LLC"
    LIMITED_PARTNERSHIP = "LIMITED_PARTNERSHIP"
    NONPROFIT_CORPORATION = "NONPROFIT_CORPORATION"


class LegalEntityStatus(str, Enum):
    DRAFT = "DRAFT"
    FORMATION_PENDING = "FORMATION_PENDING"
    ACTIVE = "ACTIVE"
    DISSOLUTION_PENDING = "DISSOLUTION_PENDING"
    DISSOLVED = "DISSOLVED"


class CompliancePosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"
    FORFEITED = "FORFEITED"


class DueRule(str, Enum):
    FIXED_MONTH_DAY = "FIXED_MONTH_DAY"
    FORMATION_ANNIVERSARY = "FORMATION_ANNIVERSARY"


class FranchiseTaxMethod(str, Enum):
    SHARES_TIERED = "SHARES_TIERED"
    FLAT = "FLAT"
    NONE = "NONE"


class PenaltyDayCounting(str, Enum):
    CALENDAR_DAYS = "CALENDAR_DAYS"
    BUSINESS_DAYS = "BUSINESS_DAYS"


class OfficerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class AgentAppointmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOTICE_PENDING = "NOTICE_PENDING"
    RESIGNED = "RESIGNED"


class ResolutionType(str, Enum):
    AUTHORIZE_FORMATION = "AUTHORIZE_FORMATION"
    AUTHORIZE_DISSOLUTION = "AUTHORIZE_DISSOLUTION"
    REVOKE_DISSOLUTION = "REVOKE_DISSOLUTION"
    AUTHORIZE_QUALIFICATION = "AUTHORIZE_QUALIFICATION"
    AUTHORIZE_WITHDRAWAL = "AUTHORIZE_WITHDRAWAL"
    APPOINT_OFFICER = "APPOINT_OFFICER"
    REMOVE_OFFICER = "REMOVE_OFFICER"
    ACCEPT_RESIGNATION = "ACCEPT_RESIGNATION"
    GRANT_SIGNATURE_AUTHORITY = "GRANT_SIGNATURE_AUTHORITY"
    REVOKE_SIGNATURE_AUTHORITY = "REVOKE_SIGNATURE_AUTHORITY"


class ResolutionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADOPTED = "ADOPTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"


class OfficeTitle(str, Enum):
    PRESIDENT = "PRESIDENT"
    SECRETARY = "SECRETARY"
    TREASURER = "TREASURER"
    CEO = "CEO"
    CFO = "CFO"
    DIRECTOR = "DIRECTOR"


class OfficerAppointmentStatus(str, Enum):
    APPOINTED = "APPOINTED"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"


class FilingType(str, Enum):
    ANNUAL_REPORT = "ANNUAL_REPORT"
    FRANCHISE_TAX = "FRANCHISE_TAX"


class FilingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PREPARED = "PREPARED"
    OVERDUE = "OVERDUE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    WITHDRAWAL_PENDING = "WITHDRAWAL_PENDING"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"


class GrantScope(str, Enum):
    BANKING = "BANKING"
    CONTRACTS = "CONTRACTS"
    TAX_FILINGS = "TAX_FILINGS"
    GOVERNMENT_FILINGS = "GOVERNMENT_FILINGS"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class DeliverySpeed(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class CertificateStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class OwnershipRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ComplianceEventType(str, Enum):
    POSTURE_CHANGED = "POSTURE_CHANGED"
    FILING_OVERDUE = "FILING_OVERDUE"
    FILING_WITHDRAWN = "FILING_WITHDRAWN"
    QUALIFICATION_REVOKED = "QUALIFICATION_REVOKED"
    GRANT_REVOKED = "GRANT_REVOKED"
    CERTIFICATE_DENIED = "CERTIFICATE_DENIED"
    OFFICER_REMOVED = "OFFICER_REMOVED"
    OFFICER_RESIGNED = "OFFICER_RESIGNED"
    AGENT_RESIGNED = "AGENT_RESIGNED"
    DISSOLUTION_COMMENCED = "DISSOLUTION_COMMENCED"
    DISSOLUTION_COMPLETED = "DISSOLUTION_COMPLETED"
    RESOLUTION_EFFECTIVE_BLOCKED = "RESOLUTION_EFFECTIVE_BLOCKED"


class UserRole(str, Enum):
    CORPORATE_SECRETARY = "CorporateSecretary"
    FILING_COORDINATOR = "FilingCoordinator"
    AUTHORIZED_OFFICER = "AuthorizedOfficer"
    REGISTERED_AGENT_USER = "RegisteredAgentUser"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------


class LegalEntity(TypedDict, total=False):
    id: str
    legal_name: str
    entity_type: str
    formation_jurisdiction_id: str
    formation_date: str
    fiscal_year_end_month: int
    authorized_shares: int
    status: str
    compliance_posture: str
    suspended_since: Optional[str]
    fees_accrued_cents: int
    dissolved_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    annual_report_due_rule: str
    annual_report_due_month: Optional[int]
    annual_report_due_day: Optional[int]
    grace_period_days: int
    franchise_tax_method: str
    late_penalty_base_cents: int
    late_penalty_cap_cents: int
    penalty_day_counting: str
    report_fee_cents: int
    cert_fee_cents: int
    ra_resignation_notice_days: int
    forfeiture_window_days: int
    created_at: str
    updated_at: str
    version: int


class RegisteredAgent(TypedDict, total=False):
    id: str
    name: str
    jurisdiction_id: str
    address: str
    created_at: str
    updated_at: str
    version: int


class Officer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AgentAppointment(TypedDict, total=False):
    id: str
    entity_id: str
    agent_id: str
    jurisdiction_id: str
    start_date: str
    notice_date: Optional[str]
    effective_end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Resolution(TypedDict, total=False):
    id: str
    entity_id: str
    resolution_type: str
    payload: Dict[str, Any]
    effective_date: str
    drafted_by_user_id: str
    adopted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficerAppointment(TypedDict, total=False):
    id: str
    entity_id: str
    officer_id: str
    resolution_id: str
    office_title: str
    start_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualFiling(TypedDict, total=False):
    id: str
    entity_id: str
    jurisdiction_id: str
    filing_type: str
    period_year: int
    due_date: str
    report_fee_cents: int
    shares_basis: int
    tax_estimated_cents: Optional[int]
    tax_assessed_cents: Optional[int]
    submitted_date: Optional[str]
    submitted_by_user_id: Optional[str]
    days_late: int
    penalty_cents: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ForeignQualification(TypedDict, total=False):
    id: str
    entity_id: str
    jurisdiction_id: str
    agent_appointment_id: str
    qualified_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SignatureAuthorityGrant(TypedDict, total=False):
    id: str
    entity_id: str
    officer_id: str
    scope: str
    max_amount_cents: int
    effective_date: str
    expiry_date: str
    delegated_from_grant_id: Optional[str]
    source_resolution_id: str
    suspended_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GoodStandingCertificate(TypedDict, total=False):
    id: str
    entity_id: str
    jurisdiction_id: str
    delivery_speed: str
    fee_cents: int
    requested_date: str
    issued_date: Optional[str]
    valid_until: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnershipRecord(TypedDict, total=False):
    id: str
    parent_entity_id: str
    subsidiary_entity_id: str
    percentage_bps: int
    effective_date: str
    end_date: Optional[str]
    supersedes_record_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceEvent(TypedDict, total=False):
    """Append-only audit record: carries ONLY id + created_at as common fields
    (PRD 2.4). No updated_at, no version."""

    id: str
    entity_id: str
    event_type: str
    payload: Dict[str, Any]
    occurred_at: str
    created_at: str
