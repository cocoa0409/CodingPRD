"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the full set of common system fields
(id, created_at, updated_at, version) per PRD §2.4 — there are no
append-only resources that omit updated_at or version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ADMIN = "Admin"
    ARRANGER = "Arranger"
    TRUST_OFFICER = "TrustOfficer"
    CEMETERY_CLERK = "CemeteryClerk"
    REGISTRAR = "Registrar"


# --------------------------------------------------------------------------
# Status enums (PRD §3)
# --------------------------------------------------------------------------
class CaseArrangementStatus(str, Enum):
    INTAKE = "INTAKE"
    DISCLOSED = "DISCLOSED"
    ARRANGED = "ARRANGED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CaseIntermentStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    INTERRED = "INTERRED"


class GplCategory(str, Enum):
    SERVICE = "SERVICE"
    MERCHANDISE = "MERCHANDISE"


class CaseMode(str, Enum):
    AT_NEED = "AT_NEED"
    PRENEED = "PRENEED"


class StatementLineStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SELECTED = "SELECTED"
    REMOVED = "REMOVED"


class FundingType(str, Enum):
    PRENEED_TRUST = "PRENEED_TRUST"
    AT_NEED_DIRECT = "AT_NEED_DIRECT"
    INSURANCE_ASSIGNMENT = "INSURANCE_ASSIGNMENT"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_FUNDING = "PENDING_FUNDING"
    FUNDED = "FUNDED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class TrustDepositKind(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    EARNINGS = "EARNINGS"
    REFUND = "REFUND"


class TrustDepositStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"


class InsuranceAssignmentStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"
    DECLINED = "DECLINED"


class PlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    INTERRED = "INTERRED"


class EventResourceKind(str, Enum):
    CHAPEL = "CHAPEL"
    GRAVESIDE = "GRAVESIDE"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class PermitType(str, Enum):
    DEATH_CERTIFICATE = "DEATH_CERTIFICATE"
    BURIAL_TRANSIT = "BURIAL_TRANSIT"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4, §3)
# --------------------------------------------------------------------------
class FuneralHome(TypedDict):
    id: str
    name: str
    sales_tax_pct: float
    state_trust_pct: float
    trust_admin_retention_cents: int
    chapel_buffer_minutes: int
    trust_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class GplItem(TypedDict):
    id: str
    funeral_home_id: str
    code: str
    name: str
    category: str
    taxable: bool
    non_declinable: bool
    preneed_trustable: bool
    unit_price_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    funeral_home_id: str
    decedent_name: str
    case_mode: str
    date_of_death: Optional[str]
    arrangement_status: str
    interment_status: str
    disclosure_acknowledged: bool
    disclosure_officer_id: Optional[str]
    statement_total_provisional_cents: int
    statement_total_final_cents: int
    gfs_issued: bool
    created_at: str
    updated_at: str
    version: int


class StatementLine(TypedDict):
    id: str
    case_id: str
    gpl_item_id: str
    description: str
    category: str
    taxable: bool
    non_declinable: bool
    preneed_trustable: bool
    unit_price_cents: int
    quantity: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    case_id: str
    funding_type: str
    status: str
    contract_amount_cents: int
    trust_required_cents: int
    trust_principal_cents: int
    credited_earnings_cents: int
    funded_amount_cents: int
    projected_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class TrustDeposit(TypedDict):
    id: str
    contract_id: str
    kind: str
    amount_cents: int
    status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


class InsuranceAssignment(TypedDict):
    id: str
    contract_id: str
    policy_number: str
    carrier: str
    assigned_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Plot(TypedDict):
    id: str
    funeral_home_id: str
    section: str
    plot_code: str
    current_price_cents: int
    status: str
    reserved_case_id: Optional[str]
    locked_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    funeral_home_id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    case_id: str
    resource_kind: str
    resource_id: str
    starts_at: str
    ends_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    case_id: str
    permit_type: str
    reference_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
