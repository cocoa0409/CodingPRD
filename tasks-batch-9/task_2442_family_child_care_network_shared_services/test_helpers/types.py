"""Role and status vocabularies declared by the PRD."""

from enum import Enum


class UserRole(str, Enum):
    """The six roles, spelled exactly as the PRD spells them."""

    ANONYMOUS = "Anonymous"
    NETWORK_ADMIN = "NetworkAdmin"
    FISCAL_OFFICER = "FiscalOfficer"
    QUALITY_COACH = "QualityCoach"
    PROVIDER = "Provider"
    SUBSTITUTE = "Substitute"


class ProviderStatus(str, Enum):
    APPLICANT = "APPLICANT"
    PENDING_AGREEMENT = "PENDING_AGREEMENT"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    EXITING = "EXITING"
    EXITED = "EXITED"


class NetworkPosture(str, Enum):
    FROZEN = "FROZEN"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class CountyTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH_NEED = "HIGH_NEED"


class QualityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    UNRATED = "UNRATED"


class QualityBasis(str, Enum):
    COACHING_WEIGHTED = "COACHING_WEIGHTED"
    COMPLIANCE_ANCHORED = "COMPLIANCE_ANCHORED"
    NONE = "NONE"


class ExitReason(str, Enum):
    RETIREMENT = "RETIREMENT"
    RELOCATION = "RELOCATION"
    LICENSE_LOSS = "LICENSE_LOSS"
    VOLUNTARY = "VOLUNTARY"


class AgreementStatus(str, Enum):
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class SharedService(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    BILLING = "BILLING"
    FOOD_PROGRAM = "FOOD_PROGRAM"
    SUBSTITUTE_POOL = "SUBSTITUTE_POOL"
    GROUP_PURCHASING = "GROUP_PURCHASING"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    TRANSITION_PENDING = "TRANSITION_PENDING"
    TRANSFERRED = "TRANSFERRED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_FOR_QUALITY = "SUSPENDED_FOR_QUALITY"
    TERMINATED = "TERMINATED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADVANCE_PAID = "ADVANCE_PAID"
    RECONCILED = "RECONCILED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    HELD = "HELD"


class ClaimVariant(str, Enum):
    PROVISIONAL_ADVANCE = "PROVISIONAL_ADVANCE"
    FINAL_RECONCILED = "FINAL_RECONCILED"


class RemittanceStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class FoodClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    APPROVED_WITH_DISALLOWANCE = "APPROVED_WITH_DISALLOWANCE"


class FoodTier(str, Enum):
    TIER_I = "TIER_I"
    TIER_II = "TIER_II"


class PoolStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class CredentialLevel(str, Enum):
    NONE = "NONE"
    CDA = "CDA"
    CHILD_DEV_TEACHER = "CHILD_DEV_TEACHER"


class AssignmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    UNFILLED = "UNFILLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"


class CoverageReason(str, Enum):
    ILLNESS = "ILLNESS"
    VACATION = "VACATION"
    TRAINING = "TRAINING"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FocusArea(str, Enum):
    ENVIRONMENT = "ENVIRONMENT"
    CURRICULUM = "CURRICULUM"
    BUSINESS_PRACTICE = "BUSINESS_PRACTICE"
    HEALTH_SAFETY = "HEALTH_SAFETY"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    CAP_SUBMITTED = "CAP_SUBMITTED"
    CAP_REJECTED = "CAP_REJECTED"
    CLOSED_COMPLIANT = "CLOSED_COMPLIANT"
    ESCALATED_TO_LICENSING = "ESCALATED_TO_LICENSING"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"


class OrderCategory(str, Enum):
    SUPPLIES = "SUPPLIES"
    CURRICULUM = "CURRICULUM"
    INSURANCE = "INSURANCE"


class Sustainability(str, Enum):
    SUSTAINABLE = "SUSTAINABLE"
    THIN = "THIN"
    AT_RISK = "AT_RISK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ReviewOrigin(str, Enum):
    SCHEDULED_AUDIT = "SCHEDULED_AUDIT"
    COACHING_CRITICAL_FINDING = "COACHING_CRITICAL_FINDING"


class HoldReason(str, Enum):
    CONTRACT_SUSPENDED_FOR_QUALITY = "CONTRACT_SUSPENDED_FOR_QUALITY"


SUPERSEDED_BY_NEWER_AGREEMENT = "SUPERSEDED_BY_NEWER_AGREEMENT"
