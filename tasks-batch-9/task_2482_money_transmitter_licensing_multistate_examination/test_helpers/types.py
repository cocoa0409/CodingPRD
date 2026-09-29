"""Typed shapes of the API resources, transcribed from the PRD narratives.

Every family except ``Jurisdiction`` carries the full audit set of ``id``,
``created_at``, ``updated_at`` and ``version`` (PRD 2.4). A jurisdiction
configuration row is immutable once posted and therefore carries only ``id``
and ``created_at`` — no ``updated_at``, no ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LICENSING_MANAGER = "LicensingManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CHIEF_COMPLIANCE_OFFICER = "ChiefComplianceOfficer"
    STATE_REGULATOR = "StateRegulator"
    DELEGATE_OPERATOR = "DelegateOperator"


# ---------------------------------------------------------------------------
# Status enumerations
# ---------------------------------------------------------------------------


class CoveragePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    DEFICIENT = "DEFICIENT"
    FROZEN = "FROZEN"


class ControlChainStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PENDING_CHECKS = "PENDING_CHECKS"
    BLOCKED = "BLOCKED"


class ControlPersonStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SEATED = "SEATED"
    REMOVED = "REMOVED"


class ControlDetermination(str, Enum):
    CONTROL = "CONTROL"
    NON_CONTROL = "NON_CONTROL"


class BackgroundCheckStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    ADVERSE = "ADVERSE"


class ChangeOfControlStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class LicenseStatus(str, Enum):
    PENDING_BOND = "PENDING_BOND"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SURRENDER_REQUESTED = "SURRENDER_REQUESTED"
    SURRENDERED = "SURRENDERED"
    REVOKED = "REVOKED"


class ReportingStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFICIENT_FILING = "DEFICIENT_FILING"


class ExpansionGate(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"


class BondStatus(str, Enum):
    NONE = "NONE"
    POSTED = "POSTED"
    CANCELLATION_NOTICED = "CANCELLATION_NOTICED"
    CANCELLED = "CANCELLED"


class RenewalStatus(str, Enum):
    NOT_RENEWED = "NOT_RENEWED"
    RENEWED = "RENEWED"


class DelegateStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AuthorizationStatus(str, Enum):
    PENDING_OVERSIGHT = "PENDING_OVERSIGHT"
    ACTIVE = "ACTIVE"
    SUSPENDED_BY_POSTURE = "SUSPENDED_BY_POSTURE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class HoldingStatus(str, Enum):
    HELD = "HELD"
    DISPOSED = "DISPOSED"


class TestStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class TestResult(str, Enum):
    PASS = "PASS"
    SHORTFALL = "SHORTFALL"


class ExamStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIELDWORK = "FIELDWORK"
    REPORT_DRAFT = "REPORT_DRAFT"
    REPORT_ISSUED = "REPORT_ISSUED"
    CLOSED = "CLOSED"


class InformationRequestStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    OVERDUE = "OVERDUE"
    ACCEPTED = "ACCEPTED"


class CallReportStatus(str, Enum):
    FILED = "FILED"
    LATE = "LATE"
    FILED_DEFICIENT = "FILED_DEFICIENT"


class EnforcementStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSENT_ORDER = "CONSENT_ORDER"
    CONTESTED = "CONTESTED"
    RESOLVED = "RESOLVED"
    REVOCATION = "REVOCATION"


# ---------------------------------------------------------------------------
# Resource shapes
# ---------------------------------------------------------------------------


class AuditedResource(TypedDict):
    """The audit properties every family but ``Jurisdiction`` carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    """Immutable configuration row: only ``id`` and ``created_at`` (PRD 2.4)."""

    id: str
    created_at: str
    state_code: str
    name: str
    min_net_worth_cents: int
    base_bond_cents: int
    per_delegate_bond_cents: int
    bond_cap_cents: int
    response_window_days: int
    renewal_fee_cents: int
    assessment_rate_bps: int
    call_report_frequency: str
    participates_in_multistate: bool


class Licensee(AuditedResource, total=False):
    legal_name: str
    ein: str
    reported_tangible_net_worth_cents: int
    net_worth_statement_date: Optional[str]
    aggregate_outstanding_obligations_cents: int
    eligible_investment_value_cents: int
    book_investment_value_cents: int
    coverage_ratio_bps: int
    coverage_posture: str
    consecutive_failed_test_count: int
    active_license_count: int
    control_chain_status: str


class ControlPerson(AuditedResource, total=False):
    licensee_id: str
    full_name: str
    role_title: str
    direct_ownership_bps: int
    parent_control_person_id: Optional[str]
    effective_ownership_bps: int
    attributed_ownership_bps: int
    control_determination: str
    background_check_status: str
    change_of_control_status: str
    required_approval_count: int
    approving_jurisdiction_ids: List[str]
    disqualifying_finding: bool
    status: str


class LicenseApplication(AuditedResource, total=False):
    licensee_id: str
    jurisdiction_id: str
    license_class: str
    projected_annual_volume_cents: int
    new_product_narrative: str
    status: str
    submitted_at: Optional[str]
    required_net_worth_cents: int
    required_bond_cents: int
    deficiency_round_count: int
    deficiency_deadline_at: Optional[str]
    denial_reason: Optional[str]
    decision_at: Optional[str]


class StateLicense(AuditedResource, total=False):
    licensee_id: str
    jurisdiction_id: str
    application_id: str
    license_class: str
    license_number: str
    license_status: str
    reporting_status: str
    expansion_gate: str
    bond_status: str
    bond_posted_cents: int
    bond_requirement_cents: int
    bond_issuer: Optional[str]
    bond_effective_date: Optional[str]
    bond_cancellation_effective_date: Optional[str]
    authorized_at: Optional[str]
    outstanding_obligations_cents: int
    annual_volume_cents: int
    active_delegate_count: int
    exam_findings_open: bool
    renewal_status: str
    renewal_year: Optional[int]
    renewal_total_fee_cents: int


class Delegate(AuditedResource, total=False):
    licensee_id: str
    legal_name: str
    delegate_type: str
    status: str
    oversight_score: Optional[int]
    last_oversight_review_at: Optional[str]
    authorized_state_count: int
    oversight_hold: bool


class DelegateAuthorization(AuditedResource, total=False):
    delegate_id: str
    state_license_id: str
    effective_date: str
    expiry_date: str
    monthly_volume_cap_cents: int
    status: str
    activated_at: Optional[str]
    oversight_score_at_activation: Optional[int]


class InvestmentHolding(AuditedResource, total=False):
    licensee_id: str
    asset_class: str
    counterparty_name: str
    book_value_cents: int
    market_value_cents: int
    age_days: int
    status: str


class PermissibleInvestmentTest(AuditedResource, total=False):
    licensee_id: str
    coverage_period_start: str
    coverage_period_end: str
    method: str
    status: str
    obligations_cents: Optional[int]
    investment_value_cents: Optional[int]
    coverage_ratio_bps: Optional[int]
    shortfall_cents: Optional[int]
    result: Optional[str]
    prepared_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    attestation_note: Optional[str]


class MultistateExam(AuditedResource, total=False):
    licensee_id: str
    lead_jurisdiction_id: str
    participating_jurisdiction_ids: List[str]
    fieldwork_start: str
    fieldwork_end: str
    status: str
    participating_state_count: int
    open_request_count: int
    findings_count: int


class InformationRequest(AuditedResource, total=False):
    exam_id: str
    jurisdiction_id: str
    subject: str
    requested_item_count: int
    submitted_item_count: int
    status: str
    due_at: str
    reopen_count: int
    responded_at: Optional[str]
    narrative: Optional[str]


class CallReport(AuditedResource, total=False):
    state_license_id: str
    period_label: str
    transmission_volume_cents: int
    transaction_count: int
    period_end: str
    due_at: str
    filed_at: str
    status: str
    assessment_fee_cents: int


class EnforcementAction(AuditedResource, total=False):
    state_license_id: str
    jurisdiction_id: str
    originating_exam_id: Optional[str]
    basis: str
    penalty_cents: int
    remediation_deadline_at: str
    status: str
    issued_at: str
    response_at: Optional[str]
    remediation_plan_narrative: Optional[str]
    resolved_at: Optional[str]
    remediation_accepted: Optional[bool]
