"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DEVELOPER = "Developer"
    QUEUE_ADMINISTRATOR = "QueueAdministrator"
    STUDY_ENGINEER = "StudyEngineer"
    REGULATOR = "Regulator"


class DeveloperType(str, Enum):
    IPP = "IPP"
    UTILITY_SCALE = "UTILITY_SCALE"
    COMMUNITY = "COMMUNITY"


class ClusterGroupStatus(str, Enum):
    FORMING = "FORMING"
    STUDY_UNDERWAY = "STUDY_UNDERWAY"
    STUDY_COMPLETE = "STUDY_COMPLETE"
    CLOSED = "CLOSED"


class ProjectStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    READY = "READY"
    IN_STUDY = "IN_STUDY"
    STUDY_COMPLETE = "STUDY_COMPLETE"
    RESTUDY_REQUIRED = "RESTUDY_REQUIRED"
    AGREEMENT_PENDING = "AGREEMENT_PENDING"
    AGREEMENT_EXECUTED = "AGREEMENT_EXECUTED"
    COMMERCIAL_OPERATION = "COMMERCIAL_OPERATION"
    WITHDRAWN = "WITHDRAWN"


class Technology(str, Enum):
    SOLAR = "SOLAR"
    WIND = "WIND"
    STORAGE = "STORAGE"
    HYBRID = "HYBRID"


class ServiceType(str, Enum):
    ENERGY_ONLY = "ENERGY_ONLY"
    CAPACITY = "CAPACITY"


class TxType(str, Enum):
    DEPOSIT = "DEPOSIT"
    REFUND = "REFUND"
    FORFEIT = "FORFEIT"


class MilestoneType(str, Enum):
    SITE_CONTROL = "SITE_CONTROL"
    TECHNICAL_DATA = "TECHNICAL_DATA"


class MilestoneStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class StudyStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    RESULTS_PUBLISHED = "RESULTS_PUBLISHED"
    FINALIZED = "FINALIZED"


class CostShareBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AgreementStatus(str, Enum):
    ISSUED = "ISSUED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class LimitType(str, Enum):
    SEASONAL = "SEASONAL"
    EMERGENCY = "EMERGENCY"
    ECONOMIC = "ECONOMIC"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------

class Developer(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    developer_type: str
    created_at: str
    updated_at: str
    version: int


class ClusterGroup(TypedDict):
    id: str
    name: str
    region: str
    application_window_open: str
    application_window_close: str
    capacity_mw: float
    committed_mw: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    developer_id: str
    cluster_group_id: str
    project_name: str
    technology: str
    capacity_mw: float
    service_type: str
    point_of_interconnection: str
    queue_position: Optional[int]
    deposit_required_cents: int
    deposit_posted_cents: int
    readiness_satisfied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MilestoneSubmission(TypedDict):
    id: str
    project_id: str
    milestone_type: str
    evidence_uri: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Study(TypedDict):
    id: str
    cluster_group_id: str
    total_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CostShare(TypedDict):
    id: str
    study_id: str
    project_id: str
    basis: str
    allocated_cents: int
    created_at: str
    updated_at: str
    version: int


class InterconnectionAgreement(TypedDict):
    id: str
    project_id: str
    issued_at: str
    execution_deadline: str
    target_cod: str
    extension_count: int
    max_injection_mw: float
    curtailment_hours_cap: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / immutable resources: id + created_at only (PRD §2.4) —
# updated_at and version are absent from them entirely.
# ---------------------------------------------------------------------------

class DepositTransaction(TypedDict):
    id: str
    created_at: str
    project_id: str
    tx_type: str
    amount_cents: int
    balance_after_cents: int


class CurtailmentLimit(TypedDict):
    id: str
    created_at: str
    project_id: str
    limit_type: str
    max_output_mw: float
    effective_start: str
    effective_end: str
    curtailment_hours_per_year: int


class TransparencyReport(TypedDict):
    id: str
    created_at: str
    reporting_period: str
    queued_project_count: int
    queued_mw: float
    withdrawn_project_count: int
    commercial_operation_project_count: int
