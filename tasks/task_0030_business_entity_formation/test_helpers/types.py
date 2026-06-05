"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3.1 (entities), §3.2-§3.12 (state machines), §2.1 (roles).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ─── Status enums ─────────────────────────────────────────────


class BusinessEntityStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class CompliancePosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class EntityType(str, Enum):
    LLC = "LLC"
    CORP = "CORP"
    LP = "LP"


class RevenueBand(str, Enum):
    ZERO = "ZERO"
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class StateCode(str, Enum):
    CA = "CA"
    DE = "DE"
    NY = "NY"
    TX = "TX"
    FL = "FL"
    WY = "WY"


class OperatingAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"


class OperatingAgreementTemplateType(str, Enum):
    MEMBER_MANAGED = "MEMBER_MANAGED"
    MANAGER_MANAGED = "MANAGER_MANAGED"
    LP_GENERAL_LIMITED = "LP_GENERAL_LIMITED"


class EINApplicationStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"


class RegisteredAgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"


class RegisteredAgentType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    COMMERCIAL = "COMMERCIAL"


class AnnualReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    DELINQUENT = "DELINQUENT"
    VOIDED = "VOIDED"


class ForeignQualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    WITHDRAWN = "WITHDRAWN"


class BOIDisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AMENDED = "AMENDED"


class BOITriggeringEvent(str, Enum):
    FORMATION = "FORMATION"
    AMENDMENT = "AMENDMENT"
    ANNUAL_REFRESH = "ANNUAL_REFRESH"


class BOIControlRole(str, Enum):
    OWNER = "OWNER"
    CONTROLLER = "CONTROLLER"
    BOTH = "BOTH"


class ComplianceEventType(str, Enum):
    POSTURE_CHANGED = "POSTURE_CHANGED"
    STATUS_CHANGED = "STATUS_CHANGED"
    REPORT_FILED = "REPORT_FILED"
    AGENT_REPLACED = "AGENT_REPLACED"
    BOI_SUBMITTED = "BOI_SUBMITTED"
    FQ_QUALIFIED = "FQ_QUALIFIED"
    FQ_WITHDRAWN = "FQ_WITHDRAWN"
    REPORT_VOIDED = "REPORT_VOIDED"
    REINSTATED = "REINSTATED"
    DELINQUENT_AUTO = "DELINQUENT_AUTO"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    FILER = "Filer"
    STATE_ADMIN = "StateAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Entity TypedDicts ────────────────────────────────────────
# Entities with common_fields (id + created_at + updated_at + version):
#   BusinessEntity, OperatingAgreement, EINApplication, RegisteredAgent,
#   AnnualReport, ForeignQualification, BOIDisclosure.
# Append-only (id + created_at only): ComplianceEvent.


class BusinessEntity(TypedDict, total=False):
    id: str
    legal_name: str
    entity_type: str
    formation_state_code: str
    revenue_band: str
    formed_at: str
    status: str
    compliance_posture: str
    franchise_tax_paid_through_year: int
    cumulative_franchise_tax_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class OperatingAgreement(TypedDict, total=False):
    id: str
    business_entity_id: str
    template_type: str
    members_json: Any
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EINApplication(TypedDict, total=False):
    id: str
    business_entity_id: str
    responsible_party_name: str
    responsible_party_ssn_last4: str
    ein: Optional[str]
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegisteredAgent(TypedDict, total=False):
    id: str
    business_entity_id: str
    agent_name: str
    agent_type: str
    agent_state_code: str
    status: str
    resigned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict, total=False):
    id: str
    business_entity_id: str
    period_year: int
    status: str
    franchise_tax_amount_cents: int
    late_fee_cents: int
    filed_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForeignQualification(TypedDict, total=False):
    id: str
    business_entity_id: str
    foreign_state_code: str
    foreign_registered_agent_id: str
    status: str
    qualified_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BOIDisclosure(TypedDict, total=False):
    id: str
    business_entity_id: str
    beneficial_owners_json: Any
    triggering_event: str
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — NO updated_at, NO version.
class ComplianceEvent(TypedDict, total=False):
    id: str
    business_entity_id: str
    event_type: str
    event_payload: Any
    event_at: str
    created_at: str
