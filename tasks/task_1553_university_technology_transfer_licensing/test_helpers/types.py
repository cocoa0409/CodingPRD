"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common fields (id, created_at, updated_at, version)
described in PRD "Common Resource Properties and Money Conventions".
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    INVENTOR = "Inventor"
    TECH_TRANSFER_OFFICER = "TechTransferOfficer"
    LICENSING_MANAGER = "LicensingManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COMPLIANCE_DIRECTOR = "ComplianceDirector"
    FINANCE_OFFICER = "FinanceOfficer"
    FINANCE_DIRECTOR = "FinanceDirector"
    SYSTEM_ADMIN = "SystemAdmin"


class DisclosureStatus(str, Enum):
    INVENTORSHIP_REVIEW = "INVENTORSHIP_REVIEW"
    INVENTORSHIP_DISPUTED = "INVENTORSHIP_DISPUTED"
    INVENTORSHIP_CONFIRMED = "INVENTORSHIP_CONFIRMED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    PATENT_PURSUED = "PATENT_PURSUED"
    WAIVED_TO_INVENTORS = "WAIVED_TO_INVENTORS"
    SHELVED = "SHELVED"


class EntryConfirmationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class PatentStatus(str, Enum):
    FILED = "FILED"
    OFFICE_ACTION_RECEIVED = "OFFICE_ACTION_RECEIVED"
    RESPONSE_FILED = "RESPONSE_FILED"
    GRANTED = "GRANTED"
    ABANDONED = "ABANDONED"


class ReimbursementStatus(str, Enum):
    UNREIMBURSED = "UNREIMBURSED"
    REIMBURSED = "REIMBURSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class StartupStatus(str, Enum):
    INCORPORATION = "INCORPORATION"
    EQUITY_ISSUED = "EQUITY_ISSUED"
    DISSOLVED = "DISSOLVED"


class CoiPlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class LicenseStatus(str, Enum):
    IN_NEGOTIATION = "IN_NEGOTIATION"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    DEFAULT_NOTICE = "DEFAULT_NOTICE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    ACHIEVED = "ACHIEVED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DistributionStatus(str, Enum):
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class ComplianceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    SUBMITTED = "SUBMITTED"
    AGENCY_ACCEPTED = "AGENCY_ACCEPTED"


class Department(TypedDict):
    id: str
    name: str
    college_name: str
    distribution_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class Inventor(TypedDict):
    id: str
    full_name: str
    email: str
    department_id: str
    appointment_type: str
    created_at: str
    updated_at: str
    version: int


class InventionDisclosure(TypedDict):
    id: str
    title: str
    description: str
    funding_source: str
    federal_agency: Optional[str]
    grant_number: Optional[str]
    public_disclosure_date: Optional[str]
    submitter_inventor_id: str
    status: str
    patentability_rating: Optional[str]
    market_rating: Optional[str]
    unreimbursed_cost_cents: int
    written_off_cost_cents: int
    cost_writeoff_review_required: bool
    created_at: str
    updated_at: str
    version: int


class DisclosureInventor(TypedDict):
    id: str
    disclosure_id: str
    inventor_id: str
    share_bp: int
    confirmation_status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventorshipDispute(TypedDict):
    id: str
    disclosure_id: str
    entry_id: str
    raised_by_inventor_id: str
    reason: str
    status: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatentApplication(TypedDict):
    id: str
    disclosure_id: str
    docket_number: str
    application_type: str
    filed_date: str
    status: str
    total_cost_cents: int
    unreimbursed_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class PatentCost(TypedDict):
    id: str
    patent_application_id: str
    cost_type: str
    amount_cents: int
    incurred_date: str
    reimbursed_amount_cents: int
    reimbursement_status: str
    created_at: str
    updated_at: str
    version: int


class Startup(TypedDict):
    id: str
    disclosure_id: str
    name: str
    founded_date: str
    equity_model: str
    university_equity_bp: Optional[int]
    equity_issued: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConflictOfInterestPlan(TypedDict):
    id: str
    startup_id: str
    inventor_id: str
    coverage_start: str
    coverage_end: str
    management_plan_text: str
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict):
    id: str
    disclosure_id: str
    startup_id: Optional[str]
    licensee_name: str
    exclusivity: str
    effective_date: str
    expiration_date: str
    royalty_rate_bp: int
    minimum_annual_royalty_cents: int
    upfront_fee_cents: int
    status: str
    default_notice_date: Optional[str]
    cure_deadline: Optional[str]
    cumulative_sales_cents: int
    cumulative_royalty_cents: int
    created_at: str
    updated_at: str
    version: int


class LicenseMilestone(TypedDict):
    id: str
    license_id: str
    description: str
    due_date: str
    amount_cents: int
    waiver_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyReport(TypedDict):
    id: str
    license_id: str
    period_start: str
    period_end: str
    reported_sales_cents: int
    earned_royalty_cents: Optional[int]
    true_up_cents: Optional[int]
    accepted_royalty_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyDistribution(TypedDict):
    id: str
    royalty_report_id: str
    gross_cents: int
    cost_offset_cents: int
    net_cents: int
    admin_fee_cents: int
    inventor_pool_cents: int
    department_pool_cents: int
    university_pool_cents: int
    inventor_shares: List[Dict[str, Any]]
    department_shares: List[Dict[str, Any]]
    cost_applications: List[Dict[str, Any]]
    prepared_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FederalComplianceReport(TypedDict):
    id: str
    disclosure_id: str
    report_type: str
    due_date: str
    prepared_by_user_id: str
    certified_by_user_id: Optional[str]
    submitted_at: Optional[str]
    late_flag: Optional[bool]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
