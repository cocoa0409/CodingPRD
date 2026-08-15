"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    SUSTAINABILITY_MANAGER = "SustainabilityManager"
    VENDOR_USER = "VendorUser"
    DATA_STEWARD = "DataSteward"
    WASTE_AUDITOR = "WasteAuditor"
    CERTIFICATION_OFFICER = "CertificationOfficer"


class CertificationTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    ZERO_WASTE = "ZERO_WASTE"


class ProgramStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class VendorType(str, Enum):
    HAULER = "HAULER"
    RECYCLER = "RECYCLER"
    PROCESSOR = "PROCESSOR"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MaterialStream(str, Enum):
    MIXED_RECYCLABLES = "MIXED_RECYCLABLES"
    CARDBOARD = "CARDBOARD"
    COMPOST_ORGANICS = "COMPOST_ORGANICS"
    MIXED_SOLID_WASTE = "MIXED_SOLID_WASTE"
    E_WASTE = "E_WASTE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class DisposalRoute(str, Enum):
    RECYCLING = "RECYCLING"
    COMPOSTING = "COMPOSTING"
    REUSE = "REUSE"
    LANDFILL = "LANDFILL"
    ENERGY_RECOVERY = "ENERGY_RECOVERY"


class TicketStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class EventSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    TRAINING_ASSIGNED = "TRAINING_ASSIGNED"
    TRAINING_COMPLETED = "TRAINING_COMPLETED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    DISMISSED = "DISMISSED"


class GoalMetric(str, Enum):
    DIVERSION_RATE = "DIVERSION_RATE"
    COST_AVOIDANCE = "COST_AVOIDANCE"
    CONTAMINATION_EVENTS = "CONTAMINATION_EVENTS"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"
    LAPSED = "LAPSED"


class ApplicationLevel(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    ZERO_WASTE = "ZERO_WASTE"


# --- Entity TypedDicts ---

class Site(TypedDict, total=False):
    id: str
    name: str
    landfill_tip_fee_per_ton_cents: int
    max_rebate_rate_per_ton_cents: int
    certification_tier: str
    program_standing: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    vendor_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict, total=False):
    id: str
    site_id: str
    vendor_id: str
    material_stream: str
    rebate_per_ton_cents: int
    contamination_penalty_per_ton_cents: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WeightTicket(TypedDict, total=False):
    id: str
    site_id: str
    vendor_id: str
    contract_id: str
    material_stream: str
    disposal_route: str
    gross_weight_lbs: int
    tare_weight_lbs: int
    net_weight_lbs: int
    contamination_pct: Optional[float]
    ticket_date: str
    external_ticket_ref: str
    validation_status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WasteAudit(TypedDict, total=False):
    # Immutable measurement log: only id + created_at are system-managed.
    id: str
    created_at: str
    site_id: str
    audit_date: str
    auditor_name: str
    stream_findings: List[Any]


class ContaminationEvent(TypedDict, total=False):
    id: str
    site_id: str
    ticket_id: Optional[str]
    audit_id: Optional[str]
    event_date: str
    material_stream: str
    contamination_pct: float
    severity: str
    status: str
    trainee_name: Optional[str]
    training_due_date: Optional[str]
    dismiss_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteGoal(TypedDict, total=False):
    id: str
    site_id: str
    metric: str
    target_value: float
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScorecardPeriod(TypedDict, total=False):
    id: str
    site_id: str
    period_start: str
    period_end: str
    status: str
    total_waste_lbs_validated: int
    diverted_lbs_validated: int
    diversion_rate_certified_pct: float
    total_waste_lbs_provisional: int
    diverted_lbs_provisional: int
    diversion_rate_provisional_pct: float
    rebate_estimate_cents: int
    rebate_settled_cents: Optional[int]
    cost_avoided_cents: Optional[int]
    contamination_event_count: int
    created_at: str
    updated_at: str
    version: int


class CertificationApplication(TypedDict, total=False):
    id: str
    site_id: str
    reporting_period_id: str
    level_requested: str
    status: str
    submitted_by: Optional[str]
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
