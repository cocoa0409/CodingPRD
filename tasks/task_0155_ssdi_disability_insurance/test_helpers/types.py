"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 splits entities into two shapes:

    common-fields (Claimant, MedicalEvidence, Application, HearingSlot,
    ChildAuxiliary, SSISupplement, CDRReview):
        id, created_at, updated_at, version

    append-only (QuarterCredit, Determination):
        "Two entities are ledger-style and intentionally immutable after
        creation: QuarterCredit and Determination. They carry only id
        and created_at — updated_at and version are absent."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CLAIMANT = "Claimant"
    DDS_EXAMINER = "DDS_Examiner"
    ALJ = "ALJ"
    APPEALS_COUNCIL = "AppealsCouncil"
    CDR_REVIEWER = "CDR_Reviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class ClaimantInsuredStatus(str, Enum):
    INSURED = "INSURED"
    NOT_INSURED = "NOT_INSURED"


class MedicalEvidenceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class MedicalEvidenceSourceType(str, Enum):
    LISTING_MATCH = "LISTING_MATCH"
    RFC_ASSESSMENT = "RFC_ASSESSMENT"


class RFCExertionalLevel(str, Enum):
    SEDENTARY = "SEDENTARY"
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    HEAVY = "HEAVY"


class RFCSkillLevel(str, Enum):
    UNSKILLED = "UNSKILLED"
    SEMI_SKILLED = "SEMI_SKILLED"
    SKILLED = "SKILLED"


class AgeCategoryAtDecision(str, Enum):
    YOUNGER = "YOUNGER"
    CLOSELY_APPROACHING = "CLOSELY_APPROACHING"
    ADVANCED = "ADVANCED"


class EducationLevel(str, Enum):
    ILLITERATE = "ILLITERATE"
    LIMITED = "LIMITED"
    HIGH_SCHOOL_OR_MORE = "HIGH_SCHOOL_OR_MORE"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    INITIAL_REVIEW = "INITIAL_REVIEW"
    INITIAL_DENIED = "INITIAL_DENIED"
    RECONSIDERATION = "RECONSIDERATION"
    RECON_DENIED = "RECON_DENIED"
    ALJ_PENDING = "ALJ_PENDING"
    ALJ_APPROVED = "ALJ_APPROVED"
    ALJ_DENIED = "ALJ_DENIED"
    APPEALS_COUNCIL = "APPEALS_COUNCIL"
    APPROVED = "APPROVED"
    CLOSED_DENIED = "CLOSED_DENIED"


class MedicalBasis(str, Enum):
    MEETS_LISTING = "MEETS_LISTING"
    EQUALS_LISTING = "EQUALS_LISTING"
    DISABLED_BY_RFC = "DISABLED_BY_RFC"
    NOT_DISABLED = "NOT_DISABLED"
    NOT_REACHED = "NOT_REACHED"


class CDRDiary(str, Enum):
    MIE = "MIE"
    MIP = "MIP"
    MINE = "MINE"


class DeterminationLevel(str, Enum):
    INITIAL = "INITIAL"
    RECONSIDERATION = "RECONSIDERATION"
    ALJ = "ALJ"
    APPEALS_COUNCIL = "APPEALS_COUNCIL"


class DeterminationDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REMAND = "REMAND"


class HearingSlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class ChildAuxiliaryStatus(str, Enum):
    PENDING = "PENDING"
    ENTITLED = "ENTITLED"
    TERMINATED = "TERMINATED"


class ChildRelationship(str, Enum):
    BIOLOGICAL = "BIOLOGICAL"
    ADOPTED = "ADOPTED"
    STEPCHILD = "STEPCHILD"
    DEPENDENT_GRANDCHILD = "DEPENDENT_GRANDCHILD"


class ChildTerminationReason(str, Enum):
    AGE_OUT = "AGE_OUT"
    NO_LONGER_DISABLED = "NO_LONGER_DISABLED"
    PARENT_BENEFIT_ENDED = "PARENT_BENEFIT_ENDED"


class SSISupplementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED_RESOURCES = "TERMINATED_RESOURCES"
    TERMINATED_INCOME = "TERMINATED_INCOME"
    TERMINATED_DIB_OFFSET = "TERMINATED_DIB_OFFSET"


class LivingArrangement(str, Enum):
    OWN_HOUSEHOLD = "OWN_HOUSEHOLD"
    ANOTHER_HOUSEHOLD = "ANOTHER_HOUSEHOLD"
    INSTITUTION = "INSTITUTION"


class CDRReviewStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class CDROutcome(str, Enum):
    CONTINUE = "CONTINUE"
    CEASE = "CEASE"


# ---------------------------------------------------------------------------
# Common-fields entities — PRD §2.4
# ---------------------------------------------------------------------------
class Claimant(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    filing_date: str
    alleged_onset_date: str
    established_onset_date: Optional[str]
    total_qc_earned: int
    qc_required: int
    qc_recent_window: int
    qc_recent_required: int
    insured_status: str
    ssn_last4: str
    created_at: str
    updated_at: str
    version: int


class MedicalEvidence(TypedDict, total=False):
    id: str
    claimant_id: str
    source_type: str
    listing_code: Optional[str]
    rfc_exertional_level: Optional[str]
    rfc_skill_level: Optional[str]
    age_category_at_decision: Optional[str]
    education_level: Optional[str]
    medical_findings: str
    evidence_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    claimant_id: str
    status: str
    medical_decision: Optional[str]
    last_initial_examiner_id: Optional[str]
    pia_cents: int
    aime_cents: int
    family_max_cents: int
    monthly_benefit_cents: int
    entitlement_date: Optional[str]
    back_pay_cents: int
    approval_date: Optional[str]
    next_cdr_due_date: Optional[str]
    cdr_diary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HearingSlot(TypedDict, total=False):
    id: str
    alj_id: str
    hearing_office: str
    start_at: str
    end_at: str
    application_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChildAuxiliary(TypedDict, total=False):
    id: str
    application_id: str
    child_name: str
    child_date_of_birth: str
    child_relationship: str
    is_full_time_student: bool
    is_disabled_before_22: bool
    status: str
    termination_reason: Optional[str]
    monthly_benefit_cents: int
    created_at: str
    updated_at: str
    version: int


class SSISupplement(TypedDict, total=False):
    id: str
    claimant_id: str
    countable_income_cents: int
    countable_resources_cents: int
    living_arrangement: str
    ssi_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CDRReview(TypedDict, total=False):
    id: str
    application_id: str
    review_due_date: str
    scheduled_at: Optional[str]
    completed_at: Optional[str]
    outcome: Optional[str]
    medical_improvement_found: bool
    working_at_sga: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — PRD §2.4: id + created_at only
# ---------------------------------------------------------------------------
class QuarterCredit(TypedDict, total=False):
    id: str
    claimant_id: str
    year: int
    quarter: int
    earnings_cents: int
    qc_count: int
    credited: bool
    created_at: str


class Determination(TypedDict, total=False):
    id: str
    application_id: str
    level: str
    examiner_id: str
    examiner_role: str
    decision: str
    medical_basis: Optional[str]
    established_onset_date: Optional[str]
    rationale: str
    created_at: str


__all__ = [
    "UserRole",
    "ClaimantInsuredStatus",
    "MedicalEvidenceStatus",
    "MedicalEvidenceSourceType",
    "RFCExertionalLevel",
    "RFCSkillLevel",
    "AgeCategoryAtDecision",
    "EducationLevel",
    "ApplicationStatus",
    "MedicalBasis",
    "CDRDiary",
    "DeterminationLevel",
    "DeterminationDecision",
    "HearingSlotStatus",
    "ChildAuxiliaryStatus",
    "ChildRelationship",
    "ChildTerminationReason",
    "SSISupplementStatus",
    "LivingArrangement",
    "CDRReviewStatus",
    "CDROutcome",
    "Claimant",
    "MedicalEvidence",
    "Application",
    "HearingSlot",
    "ChildAuxiliary",
    "SSISupplement",
    "CDRReview",
    "QuarterCredit",
    "Determination",
]
