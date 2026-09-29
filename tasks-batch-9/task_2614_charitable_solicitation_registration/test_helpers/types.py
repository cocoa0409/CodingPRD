"""Domain types for the Charitable Solicitation Registration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CERTIFYING_OFFICER = "CertifyingOfficer"
    STATE_REGULATOR = "StateRegulator"
    FUNDRAISER_AGENT = "FundraiserAgent"
    SYSTEM_ADMIN = "SystemAdmin"


ALL_ROLES: List[str] = [
    UserRole.COMPLIANCE_OFFICER.value,
    UserRole.CERTIFYING_OFFICER.value,
    UserRole.STATE_REGULATOR.value,
    UserRole.FUNDRAISER_AGENT.value,
    UserRole.SYSTEM_ADMIN.value,
]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class OrganizationLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class SolicitationPosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    HALTED = "HALTED"


class FilingPosture(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class RenewalDueRule(str, Enum):
    FYE_PLUS_4M_15D = "FYE_PLUS_4M_15D"
    FYE_PLUS_6M = "FYE_PLUS_6M"
    CALENDAR_MAY_15 = "CALENDAR_MAY_15"


class AssuranceBasis(str, Enum):
    CONTRIBUTIONS_ONLY = "CONTRIBUTIONS_ONLY"
    GROSS_REVENUE = "GROSS_REVENUE"


class AssuranceLevel(str, Enum):
    NONE = "NONE"
    REVIEW = "REVIEW"
    AUDIT = "AUDIT"


class StatementStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class OfficerTitle(str, Enum):
    PRESIDENT = "PRESIDENT"
    TREASURER = "TREASURER"
    SECRETARY = "SECRETARY"
    EXECUTIVE_DIRECTOR = "EXECUTIVE_DIRECTOR"
    BOARD_CHAIR = "BOARD_CHAIR"


class OfficerDisclosureStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class RegistrationType(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    DEFICIENT = "DEFICIENT"
    EXPIRED = "EXPIRED"
    DELINQUENT = "DELINQUENT"
    CEASED = "CEASED"
    WITHDRAWN = "WITHDRAWN"


class DocType(str, Enum):
    GOVERNING_DOCUMENT = "GOVERNING_DOCUMENT"
    IRS_DETERMINATION_LETTER = "IRS_DETERMINATION_LETTER"
    FINANCIAL_STATEMENT = "FINANCIAL_STATEMENT"
    OFFICER_DISCLOSURE_FORM = "OFFICER_DISCLOSURE_FORM"
    REVIEW_REPORT = "REVIEW_REPORT"
    AUDIT_OPINION = "AUDIT_OPINION"


class DocumentReviewStatus(str, Enum):
    ATTACHED = "ATTACHED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ExtensionBasis(str, Enum):
    IRS_990_EXTENSION = "IRS_990_EXTENSION"
    STATE_HARDSHIP = "STATE_HARDSHIP"


class ExtensionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class FundraiserType(str, Enum):
    PROFESSIONAL_SOLICITOR = "PROFESSIONAL_SOLICITOR"
    FUNDRAISING_COUNSEL = "FUNDRAISING_COUNSEL"
    COMMERCIAL_COVENTURER = "COMMERCIAL_COVENTURER"


class RegistryStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"


class FundraiserRegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class CompensationType(str, Enum):
    FLAT_FEE = "FLAT_FEE"
    PERCENT_OF_GROSS = "PERCENT_OF_GROSS"
    HOURLY = "HOURLY"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    LATE_FILED = "LATE_FILED"
    VOIDED = "VOIDED"


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    DEFICIENT_REMITTANCE = "DEFICIENT_REMITTANCE"
    HALTED = "HALTED"


class MaterialType(str, Enum):
    WEB = "WEB"
    PRINT = "PRINT"
    PHONE_SCRIPT = "PHONE_SCRIPT"
    EMAIL = "EMAIL"


class DisclosureClause(str, Enum):
    REGISTRATION_DISCLOSURE = "REGISTRATION_DISCLOSURE"
    FINANCIAL_STATEMENT_AVAILABILITY = "FINANCIAL_STATEMENT_AVAILABILITY"
    PAID_SOLICITOR_IDENTITY = "PAID_SOLICITOR_IDENTITY"
    TAX_DEDUCTIBILITY = "TAX_DEDUCTIBILITY"
    PERCENT_TO_CHARITY = "PERCENT_TO_CHARITY"


class DisclosureComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class ActionType(str, Enum):
    DELINQUENCY_NOTICE = "DELINQUENCY_NOTICE"
    PENALTY_ASSESSMENT = "PENALTY_ASSESSMENT"
    CEASE_SOLICITATION_ORDER = "CEASE_SOLICITATION_ORDER"


class EnforcementStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    ESCALATED = "ESCALATED"
    CURED = "CURED"
    VACATED = "VACATED"


class SolicitationChannel(str, Enum):
    MAIL = "MAIL"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    WEB_PASSIVE = "WEB_PASSIVE"
    WEB_TARGETED = "WEB_TARGETED"
    EVENT = "EVENT"
    GRANT_REQUEST = "GRANT_REQUEST"


class TriggerReason(str, Enum):
    DONOR_COUNT = "DONOR_COUNT"
    CONTRIBUTION_TOTAL = "CONTRIBUTION_TOTAL"
    TARGETED_ONLINE_PRESENCE = "TARGETED_ONLINE_PRESENCE"


# --------------------------------------------------------------------------
# Canonical ordered lists
# --------------------------------------------------------------------------

# The canonical clause list, in the order every derived clause array is emitted.
CANONICAL_CLAUSE_ORDER: List[str] = [
    DisclosureClause.REGISTRATION_DISCLOSURE.value,
    DisclosureClause.FINANCIAL_STATEMENT_AVAILABILITY.value,
    DisclosureClause.PAID_SOLICITOR_IDENTITY.value,
    DisclosureClause.TAX_DEDUCTIBILITY.value,
    DisclosureClause.PERCENT_TO_CHARITY.value,
]

# The canonical trigger-reason order.
CANONICAL_TRIGGER_REASON_ORDER: List[str] = [
    TriggerReason.DONOR_COUNT.value,
    TriggerReason.CONTRIBUTION_TOTAL.value,
    TriggerReason.TARGETED_ONLINE_PRESENCE.value,
]

# NONE is weakest, REVIEW sits above it and AUDIT is strongest.
ASSURANCE_SCALE: List[str] = [
    AssuranceLevel.NONE.value,
    AssuranceLevel.REVIEW.value,
    AssuranceLevel.AUDIT.value,
]


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------


class Organization(TypedDict):
    id: str
    legal_name: str
    ein: str
    domicile_state_code: str
    fiscal_year_end_month: int
    has_online_donation_page: bool
    lifecycle_status: str
    solicitation_posture: str
    filing_posture: str
    registered_state_count: int
    delinquent_registration_count: int
    ceased_state_codes: List[str]
    penalty_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class StateProfile(TypedDict):
    id: str
    state_code: str
    registration_required: bool
    renewal_due_rule: str
    assurance_basis: str
    review_threshold_cents: int
    audit_threshold_cents: int
    donor_count_trigger: int
    contribution_trigger_cents: int
    online_presence_counts: bool
    extension_allowed: bool
    extension_max_days: int
    disclosure_required_clauses: List[str]
    fundraiser_contract_filing_days: int
    fundraiser_bond_minimum_cents: int
    coventure_filing_required: bool
    coventure_buffer_days: int
    base_filing_fee_cents: int
    online_surcharge_cents: int
    per_contract_fee_cents: int
    filing_fee_cap_cents: int
    late_fee_base_cents: int
    late_fee_escalation_pct: float
    late_fee_cap_cents: int
    cure_period_days: int
    reinstatement_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class SolicitationActivity(TypedDict):
    """Immutable event record: it carries id and created_at only."""

    id: str
    organization_id: str
    state_code: str
    fiscal_year: int
    donor_count: int
    contributions_cents: int
    channels: List[str]
    triggers_registration: bool
    trigger_reasons: List[str]
    created_at: str


class FinancialStatement(TypedDict):
    id: str
    organization_id: str
    fiscal_year: int
    total_revenue_cents: int
    contributions_cents: int
    government_grant_cents: int
    program_expense_cents: int
    fundraising_expense_cents: int
    management_expense_cents: int
    assurance_level: str
    statement_status: str
    functional_expense_total_cents: int
    program_ratio: float
    created_at: str
    updated_at: str
    version: int


class OfficerDisclosure(TypedDict):
    id: str
    organization_id: str
    officer_name: str
    title: str
    is_certifying_officer: bool
    annual_compensation_cents: int
    criminal_conviction_disclosed: bool
    conviction_explanation: Optional[str]
    disclosure_status: str
    created_at: str
    updated_at: str
    version: int


class StateRegistration(TypedDict):
    id: str
    organization_id: str
    state_code: str
    registration_type: str
    fiscal_year: int
    coverage_start: str
    coverage_end: str
    financial_statement_id: str
    supersedes_registration_id: Optional[str]
    certified_by_officer_id: Optional[str]
    status: str
    renewal_due_date: str
    extended_due_date: Optional[str]
    effective_due_date: str
    required_financial_attestation: str
    filing_fee_cents: int
    deficiency_round_count: int
    deficiency_reasons: List[str]
    submitted_at: Optional[str]
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistrationDocument(TypedDict):
    id: str
    registration_id: str
    doc_type: str
    prepared_by_officer_id: str
    page_count: int
    review_status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict):
    id: str
    registration_id: str
    basis: str
    requested_days: int
    status: str
    granted_days: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProfessionalFundraiser(TypedDict):
    id: str
    legal_name: str
    fundraiser_type: str
    bond_amount_cents: int
    bond_expires_at: str
    registry_status: str
    created_at: str
    updated_at: str
    version: int


class FundraiserRegistration(TypedDict):
    id: str
    fundraiser_id: str
    state_code: str
    bond_on_file_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FundraisingContract(TypedDict):
    id: str
    organization_id: str
    fundraiser_id: str
    state_codes: List[str]
    contract_start: str
    contract_end: str
    compensation_type: str
    percent_of_gross: float
    flat_fee_cents: int
    status: str
    filing_due_date: str
    filed_at: Optional[str]
    late_filing_surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class CoventurePromotion(TypedDict):
    id: str
    organization_id: str
    coventurer_id: str
    state_codes: List[str]
    promo_start: str
    promo_end: str
    guaranteed_minimum_cents: int
    per_unit_cents: int
    projected_units: int
    status: str
    projected_benefit_cents: int
    actual_units: int
    remitted_cents: int
    final_benefit_cents: int
    shortfall_cents: int
    disclosure_clause_required: bool
    created_at: str
    updated_at: str
    version: int


class DisclosureStatement(TypedDict):
    id: str
    organization_id: str
    state_code: str
    material_type: str
    included_clauses: List[str]
    required_clauses: List[str]
    missing_clauses: List[str]
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    organization_id: str
    registration_id: str
    state_code: str
    action_type: str
    penalty_cents: int
    status: str
    issued_at: str
    cure_deadline: str
    settlement_total_cents: int
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
