"""Domain types: entity TypedDicts, status enums, role enum.

Every type here mirrors the resource shapes described in the PRD. Entities that
carry the four common system fields (id, created_at, updated_at, version) list
them explicitly; the Label resource is immutable once printed and therefore
carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    RECEIVER = "Receiver"
    GRADER = "Grader"
    AUTHENTICATOR = "Authenticator"
    LAB_ADMIN = "LabAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECEIVING = "RECEIVING"
    IN_GRADING = "IN_GRADING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"


class SubmissionItemStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INTAKE_LOGGED = "INTAKE_LOGGED"
    GRADING = "GRADING"
    AUTHENTICATED = "AUTHENTICATED"
    ENCAPSULATED = "ENCAPSULATED"
    CRACK_PENDING = "CRACK_PENDING"
    REJECTED_RETURNED = "REJECTED_RETURNED"
    SHIPPED = "SHIPPED"


class AuthVerdict(str, Enum):
    GENUINE = "GENUINE"
    ALTERED = "ALTERED"
    COUNTERFEIT = "COUNTERFEIT"


class ClaimStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    PAID = "PAID"


class RegradeRequestStatus(str, Enum):
    OPEN = "OPEN"
    CRACKED = "CRACKED"
    COMPLETED = "COMPLETED"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"


class Carrier(str, Enum):
    UPS = "UPS"
    FEDEX = "FEDEX"
    USPS = "USPS"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceLevel(TypedDict):
    id: str
    code: str
    turnaround_business_days: int
    base_fee_cents: int
    max_declared_value_cents: int
    insurance_rate_bps: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class GradingStandard(TypedDict):
    id: str
    code: str
    max_grade: float
    authentic_min_grade: float
    centering_weight_bps: int
    corners_weight_bps: int
    edges_weight_bps: int
    surface_weight_bps: int
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    customer_id: str
    service_level_id: str
    status: str
    item_count: int
    total_estimated_fee_cents: int
    total_final_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class SubmissionItem(TypedDict):
    id: str
    submission_id: str
    grading_standard_id: str
    title: str
    declared_value_cents: int
    status: str
    estimated_fee_cents: int
    final_fee_cents: int
    regrade_count: int
    current_grade: Optional[float]
    created_at: str
    updated_at: str
    version: int


class IntakeRecord(TypedDict):
    id: str
    item_id: str
    received_by_user_id: str
    condition_note: str
    matches_declaration: bool
    received_at: str
    created_at: str
    updated_at: str
    version: int


class GradeAssessment(TypedDict):
    id: str
    item_id: str
    grading_standard_id: str
    centering_subgrade: float
    corners_subgrade: float
    edges_subgrade: float
    surface_subgrade: float
    provisional_overall: Optional[float]
    final_overall: Optional[float]
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class AuthenticationCheck(TypedDict):
    id: str
    item_id: str
    authenticator_user_id: str
    verdict: str
    alteration_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Slab(TypedDict):
    id: str
    item_id: str
    cert_number: str
    assessment_id: str
    label_grade_text: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class PopulationReport(TypedDict):
    id: str
    grading_standard_id: str
    title_key: str
    grade_value: float
    pop_count: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    submission_id: str
    covered_value_cents: int
    premium_cents: int
    claim_status: str
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


class RegradeRequest(TypedDict):
    id: str
    item_id: str
    prior_slab_id: str
    expected_item_version: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    submission_id: str
    carrier: str
    tracking_number: str
    insured_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> immutable once printed, carries ONLY id + created_at
class Label(TypedDict):
    id: str
    slab_id: str
    population_report_id: str
    printed_pop_count: int
    printed_at: str
    created_at: str
