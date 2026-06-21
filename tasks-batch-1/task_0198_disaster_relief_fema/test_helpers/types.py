"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries the full set of common fields
(id, created_at, updated_at, version) per PRD §2.4, so every TypedDict
includes updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INSPECTOR = "Inspector"
    CASEWORKER = "Caseworker"


# ─── Status enums ─────────────────────────────────────────────────────────
class DeclarationStatus(str, Enum):
    OPEN = "OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    CLOSED = "CLOSED"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CaseworkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    INSPECTED = "INSPECTED"
    ELIGIBILITY_PENDING = "ELIGIBILITY_PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    WITHDRAWN = "WITHDRAWN"


class AssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INSPECTED = "INSPECTED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class Habitability(str, Enum):
    HABITABLE = "HABITABLE"
    UNINHABITABLE = "UNINHABITABLE"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ELIGIBILITY_PENDING = "ELIGIBILITY_PENDING"
    AWARD_APPROVED = "AWARD_APPROVED"
    DENIED = "DENIED"
    DISBURSING = "DISBURSING"
    UNDER_APPEAL = "UNDER_APPEAL"
    CLOSED = "CLOSED"


class LineItemCategory(str, Enum):
    RENTAL_ASSISTANCE = "RENTAL_ASSISTANCE"
    REPAIR_ASSISTANCE = "REPAIR_ASSISTANCE"
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"
    REPLACEMENT = "REPLACEMENT"


class LineItemStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class DobSourceType(str, Enum):
    INSURANCE = "INSURANCE"
    SBA_LOAN = "SBA_LOAN"
    CHARITY = "CHARITY"
    OTHER_FEDERAL = "OTHER_FEDERAL"


class DobStatus(str, Enum):
    RECORDED = "RECORDED"
    REVERSED = "REVERSED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class SbaReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    SBA_APPROVED = "SBA_APPROVED"
    SBA_DECLINED = "SBA_DECLINED"


class DisbursementStatus(str, Enum):
    PAID = "PAID"
    VOIDED = "VOIDED"


class RecoupmentOrigin(str, Enum):
    LATE_DOB = "LATE_DOB"
    APPEAL_REDUCTION = "APPEAL_REDUCTION"
    MANUAL = "MANUAL"


class RecoupmentStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"


class RentalPeriodStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


# ─── Entity TypedDicts (all common_fields: true) ───────────────────────────
class DisasterDeclaration(TypedDict):
    id: str
    title: str
    incident_start: str
    incident_end: str
    ihp_max_grant_cents: int
    registration_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    badge_number: str
    travel_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Caseworker(TypedDict):
    id: str
    full_name: str
    employee_id: str
    can_approve_awards: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    declaration_id: str
    household_name: str
    household_size: int
    annual_income_cents: int
    damage_date: str
    reported_repair_cost_cents: int
    reported_personal_property_cents: int
    reported_rental_months: int
    total_dob_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict):
    id: str
    applicant_id: str
    inspector_id: str
    scheduled_start: str
    scheduled_end: str
    habitability: Optional[str]
    verified_repair_cost_cents: Optional[int]
    verified_personal_property_cents: Optional[int]
    verified_rental_months: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class IhpCase(TypedDict):
    id: str
    applicant_id: str
    assessment_id: str
    monthly_fmr_cents: int
    gross_eligible_cents: int
    capped_eligible_cents: int
    net_eligible_cents: int
    dob_offset_cents: int
    total_approved_cents: int
    disbursed_total_cents: int
    remaining_obligation_cents: int
    determined_by_caseworker_id: Optional[str]
    pre_appeal_status: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AwardLineItem(TypedDict):
    id: str
    ihp_case_id: str
    category: str
    gross_amount_cents: int
    approved_amount_cents: int
    li_status: str
    created_at: str
    updated_at: str
    version: int


class DobRecord(TypedDict):
    id: str
    applicant_id: str
    source_type: str
    amount_cents: int
    received_at: str
    dob_status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    ihp_case_id: str
    expected_ihp_case_version: int
    reason: str
    requested_repair_cost_cents: Optional[int]
    decided_by_caseworker_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SbaReferral(TypedDict):
    id: str
    ihp_case_id: str
    referred_loss_cents: int
    sba_loan_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    ihp_case_id: str
    line_item_id: str
    expected_ihp_case_version: int
    amount_cents: int
    disb_status: str
    created_at: str
    updated_at: str
    version: int


class RentalAssistancePeriod(TypedDict):
    id: str
    ihp_case_id: str
    applicant_id: str
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recoupment(TypedDict):
    id: str
    ihp_case_id: str
    origin: str
    debt_amount_cents: int
    recovered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
