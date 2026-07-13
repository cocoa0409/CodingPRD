"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    REGISTRAR = "Registrar"
    ARTIST = "Artist"
    PANELIST = "Panelist"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    BUDGET_CERTIFIED = "BUDGET_CERTIFIED"


class CommissionStatus(str, Enum):
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    CONTRACTED = "CONTRACTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CallStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    TABULATED = "TABULATED"
    CANCELLED = "CANCELLED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SCORED = "SCORED"
    DISQUALIFIED = "DISQUALIFIED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"


class SiteStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"


class LocationStatus(str, Enum):
    FABRICATION = "FABRICATION"
    FABRICATED = "FABRICATED"
    INSTALLED = "INSTALLED"
    DEACCESSIONED = "DEACCESSIONED"


class ConditionStatus(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    NEEDS_TREATMENT = "NEEDS_TREATMENT"


class LoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class CallType(str, Enum):
    RFQ = "RFQ"
    RFP = "RFP"


class AcquisitionType(str, Enum):
    COMMISSION = "COMMISSION"
    DONATION = "DONATION"
    LOAN = "LOAN"


class DeaccessionMethod(str, Enum):
    SALE = "SALE"
    DONATION = "DONATION"
    DESTRUCTION = "DESTRUCTION"
    TRANSFER = "TRANSFER"


class RecordType(str, Enum):
    INSPECTION = "INSPECTION"
    TREATMENT = "TREATMENT"
    DAMAGE = "DAMAGE"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---

class CapitalProject(TypedDict):
    id: str
    name: str
    construction_budget_cents: int
    certified_construction_budget_cents: Optional[int]
    percent_rate: float
    art_budget_cents: int
    committed_cents: int
    uncommitted_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Commission(TypedDict):
    id: str
    project_id: str
    title: str
    allocation_cents: int
    awarded_submission_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ArtistCall(TypedDict):
    id: str
    commission_id: str
    call_type: str
    submission_deadline: str
    quorum_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    display_name: str
    email: str
    region: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    call_id: str
    artist_id: str
    proposed_budget_cents: int
    composite_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict):
    id: str
    call_id: str
    evaluator_name: str
    has_conflict: bool
    recused: bool
    created_at: str
    updated_at: str
    version: int


class Score(TypedDict):
    id: str
    submission_id: str
    panelist_id: str
    artistic_merit: int
    feasibility: int
    community_impact: int
    durability: int
    weighted_value: float
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    commission_id: str
    submission_id: str
    contract_amount_cents: int
    paid_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    contract_id: str
    sequence: int
    title: str
    pct: float
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    name: str
    address: str
    capacity: int
    current_artwork_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Artwork(TypedDict):
    id: str
    title: str
    acquisition_type: str
    contract_id: Optional[str]
    site_id: Optional[str]
    appraised_value_cents: Optional[int]
    install_date: Optional[str]
    location_status: str
    condition_status: str
    deaccession_method: Optional[str]
    deaccession_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    artwork_id: str
    borrower_name: str
    loan_start: str
    loan_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only event log; ONLY id + created_at
class ConservationRecord(TypedDict):
    id: str
    artwork_id: str
    record_type: str
    condition_after: str
    notes: Optional[str]
    performed_at: Optional[str]
    created_at: str
