"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — common-fields entities (id, created_at, updated_at, version):
    BusinessEntity, RegisteredAgent, EINApplication, AnnualReport,
    FranchiseTaxAssessment, ForeignQualification, BOIReport,
    BeneficialOwner.

PRD §2.4 — append-only / join entities (only id + created_at; NO
updated_at, NO version):
    OperatingAgreement, BOIOwnership, ComplianceEvent.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FILER = "Filer"
    STATE_REGISTRAR = "StateRegistrar"
    TAX_OFFICER = "TaxOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REGISTERED_AGENT_SERVICE = "RegisteredAgentService"
    TEST_HARNESS = "TestHarness"


# ---------------------------------------------------------------------------
# Entity enums — PRD §3
# ---------------------------------------------------------------------------
class EntityType(str, Enum):
    LLC = "LLC"
    CORP = "CORP"
    LP = "LP"


class FormationStatus(str, Enum):
    PENDING_FORMATION = "PENDING_FORMATION"
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"
    ADMINISTRATIVELY_DISSOLVED = "ADMINISTRATIVELY_DISSOLVED"


class ComplianceStatusValue(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    NOT_IN_GOOD_STANDING = "NOT_IN_GOOD_STANDING"
    DELINQUENT = "DELINQUENT"


class RegisteredAgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"


class OperatingAgreementTemplateCode(str, Enum):
    LLC_MM = "LLC_MM"
    LLC_MGR = "LLC_MGR"
    CORP_BYLAWS = "CORP_BYLAWS"
    LP_AGREEMENT = "LP_AGREEMENT"


class EINApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AnnualReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CalculationMethod(str, Enum):
    FLAT = "FLAT"
    AUTHORIZED_SHARES = "AUTHORIZED_SHARES"
    ASSUMED_PAR_VALUE = "ASSUMED_PAR_VALUE"


class FranchiseTaxStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DELINQUENT = "DELINQUENT"


class ForeignQualificationStatus(str, Enum):
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    QUALIFIED = "QUALIFIED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"


class BOIFilingType(str, Enum):
    INITIAL = "INITIAL"
    UPDATE = "UPDATE"
    CORRECTION = "CORRECTION"


class BOIReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    CURRENT = "CURRENT"
    STALE = "STALE"
    CORRECTED = "CORRECTED"


class IdentifyingDocumentType(str, Enum):
    US_PASSPORT = "US_PASSPORT"
    STATE_DRIVERS_LICENSE = "STATE_DRIVERS_LICENSE"
    STATE_ID = "STATE_ID"
    FOREIGN_PASSPORT = "FOREIGN_PASSPORT"


class ComplianceEventType(str, Enum):
    FORMED = "FORMED"
    ANNUAL_REPORT_ACCEPTED = "ANNUAL_REPORT_ACCEPTED"
    ANNUAL_REPORT_REJECTED = "ANNUAL_REPORT_REJECTED"
    TAX_ASSESSED = "TAX_ASSESSED"
    TAX_PAID = "TAX_PAID"
    TAX_OVERDUE = "TAX_OVERDUE"
    TAX_DELINQUENT = "TAX_DELINQUENT"
    BOI_FILED = "BOI_FILED"
    BOI_STALE = "BOI_STALE"
    BOI_CORRECTED = "BOI_CORRECTED"
    FOREIGN_QUALIFIED = "FOREIGN_QUALIFIED"
    FOREIGN_REVOKED = "FOREIGN_REVOKED"
    ADMIN_DISSOLVED = "ADMIN_DISSOLVED"
    VOLUNTARILY_DISSOLVED = "VOLUNTARILY_DISSOLVED"
    AGENT_RESIGNED = "AGENT_RESIGNED"
    COMPLIANCE_STATUS_CHANGED = "COMPLIANCE_STATUS_CHANGED"


# ---------------------------------------------------------------------------
# Common-fields entities — PRD §2.4
# ---------------------------------------------------------------------------
class BusinessEntity(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    entity_type: str
    home_state: str
    formation_date: Optional[str]
    registered_agent_id: str
    authorized_shares: Optional[int]
    total_gross_assets_cents: int
    total_issued_shares: int
    formation_status: str
    compliance_status: Optional[str]
    next_annual_report_due_date: Optional[str]
    ein: Optional[str]
    dissolution_date: Optional[str]
    credit_balance_cents: int


class RegisteredAgent(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agent_name: str
    physical_address: str
    service_state: str
    status: str
    resignation_effective_at: Optional[str]


class EINApplication(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_entity_id: str
    responsible_party_name: str
    responsible_party_ssn_last4: str
    status: str
    assigned_ein: Optional[str]


class AnnualReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_entity_id: str
    report_year: int
    principal_office_address: str
    officer_director_count: int
    status: str
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    rejection_reason: Optional[str]


class FranchiseTaxAssessment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_entity_id: str
    tax_year: int
    calculation_method: str
    base_tax_cents: int
    late_fee_cents: int
    total_due_cents: int
    due_date: str
    paid_at: Optional[str]
    status: str


class ForeignQualification(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_entity_id: str
    foreign_state: str
    foreign_registered_agent_id: str
    certificate_of_good_standing_date: str
    status: str
    qualified_at: Optional[str]
    revoked_at: Optional[str]


class BOIReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_entity_id: str
    filing_type: str
    status: str
    filed_at: Optional[str]
    stale_at: Optional[str]
    penalty_cents: int
    days_stale_at_filing: int


class BeneficialOwner(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_legal_name: str
    date_of_birth: str
    residential_address: str
    identifying_document_type: str
    identifying_document_number: str


# ---------------------------------------------------------------------------
# Append-only / join entities — PRD §2.4 (id + created_at only;
# NO updated_at, NO version)
# ---------------------------------------------------------------------------
class OperatingAgreement(TypedDict, total=False):
    id: str
    created_at: str
    business_entity_id: str
    template_code: str
    template_version: str
    locked_template_hash: str
    attached_at: str
    # PRD §3.3: "An OperatingAgreement row carries only id and created_at —
    # it has neither updated_at nor version."


class BOIOwnership(TypedDict, total=False):
    id: str
    created_at: str
    business_entity_id: str
    beneficial_owner_id: str
    ownership_percent_basis_points: int
    effective_at: str
    terminated_at: Optional[str]
    # PRD §2.4: BOIOwnership is mutated only by soft-delete which writes
    # terminated_at; no updated_at, no version.


class ComplianceEvent(TypedDict, total=False):
    id: str
    created_at: str
    business_entity_id: str
    event_type: str
    payload: Dict[str, Any]
    occurred_at: str
    # PRD §2.4: compliance events are append-only; no updated_at, no version.


__all__ = [
    "UserRole",
    "EntityType",
    "FormationStatus",
    "ComplianceStatusValue",
    "RegisteredAgentStatus",
    "OperatingAgreementTemplateCode",
    "EINApplicationStatus",
    "AnnualReportStatus",
    "CalculationMethod",
    "FranchiseTaxStatus",
    "ForeignQualificationStatus",
    "BOIFilingType",
    "BOIReportStatus",
    "IdentifyingDocumentType",
    "ComplianceEventType",
    "BusinessEntity",
    "RegisteredAgent",
    "EINApplication",
    "AnnualReport",
    "FranchiseTaxAssessment",
    "ForeignQualification",
    "BOIReport",
    "BeneficialOwner",
    "OperatingAgreement",
    "BOIOwnership",
    "ComplianceEvent",
]
