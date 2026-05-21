"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: resources of types Employer, Worksite, Employee, LeaveCase,
and PfLClaim carry the common envelope fields (id, created_at,
updated_at, version). Resources of types LeaveInstance,
MedicalCertification, BenefitInvoice, and AuditEvent are append-only or
mutated only through their parent's lifecycle and carry only id +
created_at. Their TypedDicts omit updated_at and version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    HR_SPECIALIST = "HRSpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ===========================================================================
# Employer.leave_year_basis — PRD §3.1
# ===========================================================================
class LeaveYearBasis(str, Enum):
    CALENDAR = "CALENDAR"
    ROLLING_BACKWARD = "ROLLING_BACKWARD"


# ===========================================================================
# Employer.state_pfl_program — PRD §3.1
# ===========================================================================
class StatePflProgram(str, Enum):
    NONE = "NONE"
    STATE_PFL_8WEEK = "STATE_PFL_8WEEK"


# ===========================================================================
# Employee.employment_status — PRD §3.1
# ===========================================================================
class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"
    RESTORED = "RESTORED"


# ===========================================================================
# LeaveCase.reason — PRD §3.3
# ===========================================================================
class LeaveReason(str, Enum):
    OWN_SERIOUS_HEALTH = "OWN_SERIOUS_HEALTH"
    FAMILY_SERIOUS_HEALTH = "FAMILY_SERIOUS_HEALTH"
    BABY_BONDING = "BABY_BONDING"
    MILITARY_EXIGENCY = "MILITARY_EXIGENCY"


# ===========================================================================
# LeaveCase.leave_pattern — PRD §3.3
# ===========================================================================
class LeavePattern(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    INTERMITTENT = "INTERMITTENT"
    REDUCED_SCHEDULE = "REDUCED_SCHEDULE"


# ===========================================================================
# LeaveCase.case_status — PRD §3.3, §3.6, §3.10, §3.11
# ===========================================================================
class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    JOB_RESTORED = "JOB_RESTORED"
    CANCELLED = "CANCELLED"


# ===========================================================================
# LeaveCase.certification_status — PRD §3.5
# ===========================================================================
class CertificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    AWAITING_DOC = "AWAITING_DOC"
    RECEIVED = "RECEIVED"
    INSUFFICIENT = "INSUFFICIENT"
    COMPLETE = "COMPLETE"
    RECERTIFICATION_DUE = "RECERTIFICATION_DUE"


# ===========================================================================
# LeaveCase.job_restoration_status — PRD §3.10
# ===========================================================================
class JobRestorationStatus(str, Enum):
    PROTECTED = "PROTECTED"
    FORFEITED = "FORFEITED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ===========================================================================
# LeaveInstance.instance_status — PRD §3.4
# ===========================================================================
class InstanceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


# ===========================================================================
# MedicalCertification.review_outcome — PRD §3.5
# ===========================================================================
class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    INSUFFICIENT = "INSUFFICIENT"
    REJECTED = "REJECTED"


# ===========================================================================
# PfLClaim.claim_type — PRD §3.8
# ===========================================================================
class PflClaimType(str, Enum):
    FAMILY_CARE = "FAMILY_CARE"
    BABY_BONDING = "BABY_BONDING"


# ===========================================================================
# PfLClaim.claim_status — PRD §3.8
# ===========================================================================
class PflClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAYING = "PAYING"
    EXHAUSTED = "EXHAUSTED"
    DENIED = "DENIED"


# ===========================================================================
# BenefitInvoice.invoice_status — PRD §3.9
# ===========================================================================
class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    GRACE = "GRACE"
    FORFEITED = "FORFEITED"


# ===========================================================================
# AuditEvent.event_kind — PRD §2.9
# ===========================================================================
class AuditEventKind(str, Enum):
    ELIGIBILITY_CHECKED = "ELIGIBILITY_CHECKED"
    CASE_CREATED = "CASE_CREATED"
    CERTIFICATION_SUBMITTED = "CERTIFICATION_SUBMITTED"
    CERTIFICATION_REVIEWED = "CERTIFICATION_REVIEWED"
    INSTANCE_LOGGED = "INSTANCE_LOGGED"
    INSTANCE_VOIDED = "INSTANCE_VOIDED"
    QUOTA_RECOMPUTED = "QUOTA_RECOMPUTED"
    PFL_LINKED = "PFL_LINKED"
    JOB_RESTORATION_REQUESTED = "JOB_RESTORATION_REQUESTED"
    JOB_RESTORATION_FORFEITED = "JOB_RESTORATION_FORFEITED"
    BENEFIT_INVOICE_ISSUED = "BENEFIT_INVOICE_ISSUED"
    BENEFIT_INVOICE_FORFEITED = "BENEFIT_INVOICE_FORFEITED"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================

# common_fields: true — carries id + created_at + updated_at + version
class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    leave_year_basis: str
    state_pfl_program: str
    benefit_premium_share_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Worksite(TypedDict, total=False):
    id: str
    employer_id: str
    address_line: str
    employee_count_within_75_miles: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Employee(TypedDict, total=False):
    id: str
    employer_id: str
    worksite_id: str
    full_name: str
    hire_date: str
    hours_worked_trailing_12mo: int
    monthly_wage_cents: int
    employment_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LeaveCase(TypedDict, total=False):
    id: str
    employee_id: str
    reason: str
    leave_pattern: str
    case_status: str
    certification_status: str
    requested_start_date: str
    expected_end_date: str
    leave_year_anchor: str
    pfl_claim_id: Optional[str]
    cert_deadline: str
    hours_charged: int
    job_restoration_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only / leaf record (PRD §2.4)
class LeaveInstance(TypedDict, total=False):
    id: str
    leave_case_id: str
    instance_date: str
    hours_used: int
    instance_status: str
    created_at: str


# common_fields: false — append-only / leaf record (PRD §2.4)
class MedicalCertification(TypedDict, total=False):
    id: str
    leave_case_id: str
    submitted_at: str
    serious_health_condition: bool
    estimated_frequency_per_month: int
    estimated_duration_hours: int
    review_outcome: str
    created_at: str


# common_fields: true
class PfLClaim(TypedDict, total=False):
    id: str
    employee_id: str
    claim_type: str
    claim_status: str
    weeks_authorized: int
    weeks_paid: int
    weekly_benefit_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only / leaf record (PRD §2.4)
class BenefitInvoice(TypedDict, total=False):
    id: str
    leave_case_id: str
    period_month: str
    amount_due_cents: int
    invoice_status: str
    created_at: str


# common_fields: false — append-only audit row (PRD §2.4, §2.9)
class AuditEvent(TypedDict, total=False):
    id: str
    leave_case_id: str
    event_kind: str
    actor_role: str
    detail_json: dict
    created_at: str


# Eligibility-snapshot response — PRD §3.2
class EligibilitySnapshot(TypedDict, total=False):
    eligible: bool
    reason_code: Optional[str]
    months_of_service: int
    hours_trailing: int
    worksite_headcount: int


# Quota-balance response — PRD §3.7
class QuotaBalance(TypedDict, total=False):
    basis: str
    window_start: str
    window_end: str
    consumed_hours: int
    remaining_hours: int


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "LeaveYearBasis",
    "StatePflProgram",
    "EmploymentStatus",
    "LeaveReason",
    "LeavePattern",
    "CaseStatus",
    "CertificationStatus",
    "JobRestorationStatus",
    "InstanceStatus",
    "ReviewOutcome",
    "PflClaimType",
    "PflClaimStatus",
    "InvoiceStatus",
    "AuditEventKind",
    # Entities
    "Employer",
    "Worksite",
    "Employee",
    "LeaveCase",
    "LeaveInstance",
    "MedicalCertification",
    "PfLClaim",
    "BenefitInvoice",
    "AuditEvent",
    # Response wrappers
    "EligibilitySnapshot",
    "QuotaBalance",
]
