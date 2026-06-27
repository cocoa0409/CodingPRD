"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Federal Acquisition PRD (§3 workflows and §2.4 common properties).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────
class UserRole(str, Enum):
    CONTRACTING_OFFICER = "ContractingOfficer"
    VENDOR = "Vendor"
    AUDITOR = "Auditor"


# ─── Status enums (PRD §3 state machines) ──────────────────────────
class SamStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXCLUDED = "EXCLUDED"


class SolicitationStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    AMENDED = "AMENDED"
    CLOSED = "CLOSED"
    EVALUATED = "EVALUATED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    ACCEPTABLE = "ACCEPTABLE"
    UNACCEPTABLE = "UNACCEPTABLE"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AwardStatus(str, Enum):
    AWARDED = "AWARDED"
    PROTESTED = "PROTESTED"
    VACATED = "VACATED"


class ContractLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class FundingPosture(str, Enum):
    WITHIN_CEILING = "WITHIN_CEILING"
    CEILING_REACHED = "CEILING_REACHED"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ModificationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


# ─── Value enums ───────────────────────────────────────────────────
class VehicleType(str, Enum):
    RFP = "RFP"
    RFQ = "RFQ"
    IFB = "IFB"


class EvaluationMethod(str, Enum):
    TRADEOFF = "TRADEOFF"
    LPTA = "LPTA"


class SetAsideType(str, Enum):
    NONE = "NONE"
    SMALL_BUSINESS = "SMALL_BUSINESS"
    EIGHT_A = "EIGHT_A"
    SDVOSB = "SDVOSB"
    WOSB = "WOSB"
    HUBZONE = "HUBZONE"


class FactorKind(str, Enum):
    TECHNICAL = "TECHNICAL"
    PAST_PERFORMANCE = "PAST_PERFORMANCE"
    PRICE = "PRICE"


class ContractType(str, Enum):
    FFP = "FFP"
    CPFF = "CPFF"


class ModType(str, Enum):
    FUNDING = "FUNDING"
    OPTION_EXERCISE = "OPTION_EXERCISE"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class CparsRating(str, Enum):
    EXCEPTIONAL = "EXCEPTIONAL"
    VERY_GOOD = "VERY_GOOD"
    SATISFACTORY = "SATISFACTORY"
    MARGINAL = "MARGINAL"
    UNSATISFACTORY = "UNSATISFACTORY"


# ─── Entity TypedDicts ─────────────────────────────────────────────
# Entities carrying the full common-field set: id, created_at, updated_at, version.

class VendorRegistration(TypedDict):
    id: str
    legal_name: str
    uei: str
    employee_count: int
    set_aside_certifications: List[str]
    sam_status: str
    registration_expires_at: str
    performance_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Solicitation(TypedDict):
    id: str
    title: str
    vehicle_type: str
    set_aside_type: str
    naics_size_threshold: int
    evaluation_method: Optional[str]
    open_at: str
    close_at: str
    status: str
    amendment_count: int
    winning_proposal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    solicitation_id: str
    vendor_id: str
    total_price_cents: int
    pinned_vendor_version: Optional[int]
    status: str
    merit_score: Optional[float]
    value_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class FactorScore(TypedDict):
    id: str
    proposal_id: str
    factor_id: str
    raw_score: int
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    solicitation_id: str
    proposal_id: str
    awarded_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    award_id: str
    vendor_id: str
    contract_type: str
    total_estimated_cost_cents: Optional[int]
    fixed_fee_cents: Optional[int]
    base_value_cents: int
    obligated_amount_cents: int
    lifecycle_status: str
    funding_posture: str
    cumulative_invoiced_cents: int
    created_at: str
    updated_at: str
    version: int


class ContractLineItem(TypedDict):
    id: str
    contract_id: str
    clin_number: str
    unit_price_cents: Optional[int]
    funded_qty: int
    delivered_qty: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    contract_id: str
    clin_id: Optional[str]
    invoiced_qty: Optional[int]
    allowable_cost_cents: Optional[int]
    amount_cents: int
    fee_portion_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Modification(TypedDict):
    id: str
    contract_id: str
    mod_type: str
    delta_cents: int
    option_value_cents: int
    option_window_close_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    award_id: str
    protester_vendor_id: str
    grounds: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CparsReport(TypedDict):
    id: str
    contract_id: str
    rating: str
    rating_value: int
    created_at: str
    updated_at: str
    version: int


# EvaluationFactor carries ONLY id + created_at (PRD §2.4: "a factor carries only
# id and created_at. It has neither an updated_at field nor a version field").
class EvaluationFactor(TypedDict):
    id: str
    solicitation_id: str
    name: str
    kind: str
    weight: float
    created_at: str
