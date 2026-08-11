"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REVISED = "REVISED"
    SUPERSEDED = "SUPERSEDED"


class DeviceUnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    DEPLOYED = "DEPLOYED"
    ON_LOAN = "ON_LOAN"
    IN_REPAIR = "IN_REPAIR"
    RETIRED = "RETIRED"


class DeviceOrderStatus(str, Enum):
    PLACED = "PLACED"
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"


class LoanAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"


class TrainingPlanStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class FundingAuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class RepairTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    DIAGNOSED = "DIAGNOSED"
    IN_REPAIR = "IN_REPAIR"
    QA_CHECK = "QA_CHECK"
    RESOLVED = "RESOLVED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class OutcomeAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SCORED = "SCORED"


class DeviceCategory(str, Enum):
    MAGNIFIER = "MAGNIFIER"
    CCTV = "CCTV"
    SCREEN_READER = "SCREEN_READER"


class UnitCondition(str, Enum):
    NEW = "NEW"
    REFURB = "REFURB"
    LOANER = "LOANER"


class FulfillmentType(str, Enum):
    PURCHASE = "PURCHASE"
    TRIAL = "TRIAL"
    LOANER = "LOANER"


class PayerType(str, Enum):
    VR = "VR"
    INSURANCE = "INSURANCE"


class CopayTier(str, Enum):
    STANDARD = "STANDARD"
    LOW_INCOME = "LOW_INCOME"


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    VISION_SPECIALIST = "VisionSpecialist"
    FUNDING_COORDINATOR = "FundingCoordinator"
    PAYER_ADJUDICATOR = "PayerAdjudicator"
    BILLING_SPECIALIST = "BillingSpecialist"
    REPAIR_TECHNICIAN = "RepairTechnician"
    CLINIC_ADMIN = "ClinicAdmin"


# All entities carry common fields: id, created_at, updated_at, version.


class Client(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    copay_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    client_id: str
    source_type: str
    referring_party: str
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    id: str
    client_id: str
    referral_id: str
    evaluator_user_id: str
    acuity_score: Optional[int]
    contrast_score: Optional[int]
    field_loss_pct: Optional[int]
    recommended_category: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviceModel(TypedDict, total=False):
    id: str
    name: str
    category: str
    list_price_cents: int
    subscription_monthly_cents: int
    successor_model_id: Optional[str]
    in_stock_count: int
    total_count: int
    created_at: str
    updated_at: str
    version: int


class DeviceUnit(TypedDict, total=False):
    id: str
    device_model_id: str
    serial_no: str
    condition: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviceOrder(TypedDict, total=False):
    id: str
    client_id: str
    evaluation_id: str
    device_model_id: str
    fulfillment_type: str
    trial_days: Optional[int]
    warranty_cents: int
    device_unit_id: Optional[str]
    dispensed_at: Optional[str]
    trial_ends_at: Optional[str]
    conversion_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanAgreement(TypedDict, total=False):
    id: str
    client_id: Optional[str]
    device_unit_id: str
    device_order_id: Optional[str]
    repair_ticket_id: Optional[str]
    loaned_at: str
    due_at: str
    returned_at: Optional[str]
    overdue_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingPlan(TypedDict, total=False):
    id: str
    client_id: str
    device_order_id: str
    total_sessions: int
    completed_sessions: int
    no_show_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    training_plan_id: str
    instructor_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAuthorization(TypedDict, total=False):
    id: str
    client_id: str
    payer_type: str
    payer_ref: str
    authorized_amount_cents: int
    remaining_amount_cents: int
    valid_from: str
    valid_until: str
    submitted_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    funding_authorization_id: str
    device_order_id: str
    service_date: str
    lines: List[dict]
    provisional_total_cents: int
    final_amount_cents: Optional[int]
    payer_pays_cents: Optional[int]
    client_pays_cents: Optional[int]
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict, total=False):
    id: str
    device_unit_id: str
    issue_description: str
    technician_user_id: str
    loan_agreement_id: Optional[str]
    rework_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    client_id: str
    device_model_id: str
    period_start: str
    period_end: str
    auto_renew: bool
    total_paid_cents: int
    last_fee_cents: int
    credit_cents: Optional[int]
    past_due_since: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeAssessment(TypedDict, total=False):
    id: str
    client_id: str
    kind: str
    task_score: int
    satisfaction_score: int
    acuity_delta: Optional[int]
    provisional_composite: int
    final_composite: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
