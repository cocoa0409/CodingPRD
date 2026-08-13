"""Domain types: entity TypedDicts, status enums, role enum.

All nine resources carry the full common-field set (id, created_at,
updated_at, version) per PRD section 2.4 — there are no reduced-schema
resources.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LICENSING_ANALYST = "LicensingAnalyst"
    LICENSEE = "Licensee"
    LEGAL_COUNSEL = "LegalCounsel"
    FINANCE_OFFICER = "FinanceOfficer"
    IP_ADMIN = "IPAdmin"


class LicenseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    ACHIEVED = "ACHIEVED"


class MilestoneTriggerType(str, Enum):
    CUMULATIVE_SALES = "CUMULATIVE_SALES"
    DATE = "DATE"


class SublicenseGrantStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class RoyaltyReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    FLAGGED = "FLAGGED"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_ADJUSTMENT = "ACCEPTED_WITH_ADJUSTMENT"
    AUDIT_REFERRED = "AUDIT_REFERRED"
    VOIDED = "VOIDED"


class RoyaltyAuditStatus(str, Enum):
    INITIATED = "INITIATED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    WAIVED = "WAIVED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class FindingType(str, Enum):
    UNDERREPORTED_BASE = "UNDERREPORTED_BASE"
    RATE_MISAPPLICATION = "RATE_MISAPPLICATION"
    DEDUCTION_ABUSE = "DEDUCTION_ABUSE"
    MISSING_PASS_THROUGH = "MISSING_PASS_THROUGH"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    NEGOTIATION = "NEGOTIATION"
    COUNTERED = "COUNTERED"
    RATIFICATION_PENDING = "RATIFICATION_PENDING"
    SETTLED = "SETTLED"
    ARBITRATED = "ARBITRATED"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    SUPERSEDED = "SUPERSEDED"
    ACCEPTED = "ACCEPTED"


class DistributionRunStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class RoyaltyBaseDefinition(str, Enum):
    NET_SALES = "NET_SALES"
    GROSS_SALES = "GROSS_SALES"


class MflMode(str, Enum):
    RETROACTIVE = "RETROACTIVE"
    PROSPECTIVE = "PROSPECTIVE"


class InventorShare(TypedDict):
    inventor_name: str
    share_bp: int


class Licensee(TypedDict):
    id: str
    legal_name: str
    tax_id: str
    contact_email: str
    status: str
    outstanding_balance_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict):
    id: str
    licensee_id: str
    patent_reference: str
    title: str
    royalty_base_definition: str
    base_rate_bp: int
    minimum_period_royalty_cents: int
    sublicense_allowed: bool
    sublicense_passthrough_rate_bp: int
    mfl_clause: bool
    mfl_mode: str
    mfl_lookback_quarters: int
    audit_window_months: int
    underreport_tolerance_bp: int
    inventor_shares: List[InventorShare]
    effective_date: str
    expiration_date: str
    status: str
    cumulative_accepted_base_cents: int
    cumulative_recognized_revenue_cents: int
    undistributed_pool_cents: int
    mfl_adjusted_rate_bp: Optional[int]
    last_mfl_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    agreement_id: str
    name: str
    trigger_type: str
    threshold_cents: Optional[int]
    trigger_date: Optional[str]
    fee_cents: int
    status: str
    achieved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SublicenseGrant(TypedDict):
    id: str
    agreement_id: str
    sublicensee_name: str
    territory: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportLine(TypedDict):
    product_label: str
    units_sold: int
    gross_sales_cents: int
    deductions_cents: int
    is_sublicense_revenue: bool


class RoyaltyReport(TypedDict):
    id: str
    agreement_id: str
    licensee_id: str
    period_start: str
    period_end: str
    lines: List[ReportLine]
    reported_gross_sales_cents: int
    reported_net_sales_cents: int
    royalty_base_cents: int
    sublicense_net_sales_cents: int
    provisional_royalty_cents: int
    benchmark_net_sales_cents: Optional[int]
    adjusted_base_cents: Optional[int]
    final_royalty_cents: Optional[int]
    accepted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyAudit(TypedDict):
    id: str
    agreement_id: str
    scope_period_start: str
    scope_period_end: str
    opened_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_id: str
    report_id: str
    finding_type: str
    audited_base_cents: int
    shortfall_cents: int
    recorded_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    amount_cents: int
    offered_by_role: str
    offered_by_user_id: str
    status: str
    created_at: str


class Dispute(TypedDict):
    id: str
    finding_id: str
    agreement_id: str
    licensee_id: str
    offers: List[Offer]
    settlement_amount_cents: Optional[int]
    awarded_amount_cents: Optional[int]
    ratified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict):
    inventor_name: str
    share_bp: int
    amount_cents: int


class DistributionRun(TypedDict):
    id: str
    agreement_id: str
    period_start: str
    period_end: str
    pool_cents: int
    lines: List[DistributionLine]
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
