"""Domain types: status enums, value enums and entity TypedDicts.

Every persisted record in this API carries id, created_at, updated_at and
version, so every TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PALLIATIVE_PHYSICIAN = "PalliativePhysician"
    PALLIATIVE_NURSE = "PalliativeNurse"
    SOCIAL_WORKER = "SocialWorker"
    CHAPLAIN = "Chaplain"
    HOSPICE_MEDICAL_DIRECTOR = "HospiceMedicalDirector"
    ON_CALL_CLINICIAN = "OnCallClinician"
    BILLING_SPECIALIST = "BillingSpecialist"
    PROGRAM_ADMIN = "ProgramAdmin"
    CAREGIVER = "Caregiver"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------
class PatientProgramStatus(str, Enum):
    REFERRED = "REFERRED"
    ACTIVE = "ACTIVE"
    HOSPICE_ELECTED = "HOSPICE_ELECTED"
    DECEASED = "DECEASED"


class CapacityStatus(str, Enum):
    HAS_CAPACITY = "HAS_CAPACITY"
    LACKS_CAPACITY = "LACKS_CAPACITY"


class CodeStatus(str, Enum):
    FULL_CODE = "FULL_CODE"
    DNR = "DNR"
    DNR_DNI = "DNR_DNI"
    COMFORT_MEASURES_ONLY = "COMFORT_MEASURES_ONLY"


class JurisdictionCode(str, Enum):
    JUR_TWO_WITNESS = "JUR_TWO_WITNESS"
    JUR_NOTARY = "JUR_NOTARY"


class OpioidStatus(str, Enum):
    OPIOID_NAIVE = "OPIOID_NAIVE"
    OPIOID_TOLERANT = "OPIOID_TOLERANT"


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    jurisdiction_code: str
    attending_clinician_user_id: str
    opioid_status: str
    program_status: str
    capacity_status: str
    code_status: str
    code_status_rank: int
    records_frozen: bool
    deceased_at: Optional[str]
    active_daily_mme: float
    acp_minutes_claimed: int
    acp_paid_cents_ytd: int
    open_symptom_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------
class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ReferralSource(str, Enum):
    HOSPITAL_DISCHARGE = "HOSPITAL_DISCHARGE"
    ONCOLOGY = "ONCOLOGY"
    PRIMARY_CARE = "PRIMARY_CARE"
    SELF = "SELF"
    PAYER = "PAYER"


class TriageVariant(str, Enum):
    PAYER_SOURCED = "PAYER_SOURCED"
    CLINICIAN_SOURCED = "CLINICIAN_SOURCED"


class Referral(TypedDict, total=False):
    id: str
    patient_id: str
    source: str
    prognosis_months: int
    serious_illness_criteria_count: int
    triage_variant: str
    triage_score: int
    status: str
    decline_reason_code: Optional[str]
    re_referral_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Surrogate designation
# ---------------------------------------------------------------------------
class SurrogateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SurrogateRelationship(str, Enum):
    HEALTHCARE_AGENT = "HEALTHCARE_AGENT"
    SPOUSE = "SPOUSE"
    ADULT_CHILD = "ADULT_CHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"


# ---------------------------------------------------------------------------
# Advance care document
# ---------------------------------------------------------------------------
class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_EXECUTION = "PENDING_EXECUTION"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class DocumentType(str, Enum):
    LIVING_WILL = "LIVING_WILL"
    HEALTHCARE_PROXY = "HEALTHCARE_PROXY"
    POLST = "POLST"


class SignatureType(str, Enum):
    WITNESS = "WITNESS"
    NOTARY = "NOTARY"
    SIGNING_PHYSICIAN = "SIGNING_PHYSICIAN"
    PATIENT_OR_SURROGATE = "PATIENT_OR_SURROGATE"


class AdvanceCareDocument(TypedDict, total=False):
    id: str
    patient_id: str
    document_type: str
    stated_code_status: str
    supersedes_document_id: Optional[str]
    status: str
    witness_signature_count: int
    notary_signature_count: int
    physician_signature_count: int
    patient_or_surrogate_signature_count: int
    execution_ready: bool
    signature_log: List[dict]
    executed_at: Optional[str]
    reattest_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Code-status order
# ---------------------------------------------------------------------------
class CodeStatusOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ATTESTED = "ATTESTED"
    CONFLICT_HOLD = "CONFLICT_HOLD"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class LadderDirection(str, Enum):
    DE_ESCALATION = "DE_ESCALATION"
    RE_ESCALATION = "RE_ESCALATION"
    NO_CHANGE = "NO_CHANGE"


class AttestationRole(str, Enum):
    CLINICIAN = "CLINICIAN"
    PATIENT_OR_SURROGATE = "PATIENT_OR_SURROGATE"


# ---------------------------------------------------------------------------
# Care plan and symptom assessment
# ---------------------------------------------------------------------------
class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    CLOSED = "CLOSED"


class CarePlanClosedReason(str, Enum):
    PATIENT_DEATH = "PATIENT_DEATH"
    GOALS_MET = "GOALS_MET"
    TRANSFERRED = "TRANSFERRED"


class TriageStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class EscalationAxisStatus(str, Enum):
    NONE = "NONE"
    ESCALATED = "ESCALATED"
    DISPOSITIONED = "DISPOSITIONED"


class SeverityTier(str, Enum):
    MINIMAL = "MINIMAL"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ResolutionReason(str, Enum):
    SYMPTOM_CONTROLLED = "SYMPTOM_CONTROLLED"
    ESCALATION_DISPOSITIONED = "ESCALATION_DISPOSITIONED"
    PLAN_CLOSED = "PLAN_CLOSED"


class ReporterType(str, Enum):
    SELF = "SELF"
    PROXY = "PROXY"


# ---------------------------------------------------------------------------
# Care conference
# ---------------------------------------------------------------------------
class ConferenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    QUORUM_FAILED = "QUORUM_FAILED"
    ATTESTED = "ATTESTED"
    CONSENT_INVALIDATED = "CONSENT_INVALIDATED"


class ConferenceType(str, Enum):
    IDT = "IDT"
    FAMILY = "FAMILY"


class Modality(str, Enum):
    TELEHEALTH = "TELEHEALTH"
    IN_PERSON = "IN_PERSON"


class DecisionMakerKind(str, Enum):
    PATIENT = "PATIENT"
    SURROGATE = "SURROGATE"


# ---------------------------------------------------------------------------
# Medication order
# ---------------------------------------------------------------------------
class MedicationOrderStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DISCONTINUED = "DISCONTINUED"


class Drug(str, Enum):
    MORPHINE_PO = "MORPHINE_PO"
    OXYCODONE_PO = "OXYCODONE_PO"
    HYDROMORPHONE_PO = "HYDROMORPHONE_PO"
    FENTANYL_TD = "FENTANYL_TD"


class MmeVariant(str, Enum):
    TOLERANT = "TOLERANT"
    NAIVE = "NAIVE"


class MedicationAttestationType(str, Enum):
    VERIFICATION = "VERIFICATION"
    MME_REVIEW = "MME_REVIEW"


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
class DeviceType(str, Enum):
    OXYGEN_CONCENTRATOR = "OXYGEN_CONCENTRATOR"
    HOSPITAL_BED = "HOSPITAL_BED"
    WHEELCHAIR = "WHEELCHAIR"
    SUCTION_MACHINE = "SUCTION_MACHINE"


class DmeOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PENDING_AUTH = "PENDING_AUTH"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


class DmeClosedReason(str, Enum):
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"
    PICKED_UP_ON_DISCHARGE = "PICKED_UP_ON_DISCHARGE"


class DmeInventoryItem(TypedDict, total=False):
    id: str
    device_type: str
    total_units: int
    available_units: int
    reserved_units: int
    delivered_units: int
    prior_auth_required: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Hospice election
# ---------------------------------------------------------------------------
class HospiceElectionStatus(str, Enum):
    PENDING_CERT = "PENDING_CERT"
    CERTIFIED = "CERTIFIED"
    ELECTED = "ELECTED"
    REVOKED = "REVOKED"
    CLOSED_ON_DEATH = "CLOSED_ON_DEATH"


# ---------------------------------------------------------------------------
# On-call escalation
# ---------------------------------------------------------------------------
class EscalationStatus(str, Enum):
    TIER_NOTIFIED = "TIER_NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPOSITIONED = "DISPOSITIONED"
    CLOSED = "CLOSED"


class Disposition(str, Enum):
    ADVICE = "ADVICE"
    URGENT_TELEHEALTH_VISIT = "URGENT_TELEHEALTH_VISIT"
    DISPATCH = "DISPATCH"
    ED_REFERRAL = "ED_REFERRAL"
    ADMINISTRATIVE_CLOSE = "ADMINISTRATIVE_CLOSE"


class EscalationResponseType(str, Enum):
    ACKNOWLEDGE = "ACKNOWLEDGE"
    DISPOSITION = "DISPOSITION"


# ---------------------------------------------------------------------------
# Billing claim
# ---------------------------------------------------------------------------
class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    ATTESTED = "ATTESTED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    DOCUMENTATION_INSUFFICIENT = "DOCUMENTATION_INSUFFICIENT"
    DUPLICATE_SERVICE = "DUPLICATE_SERVICE"
    NON_COVERED = "NON_COVERED"


class AcpBillingClaim(TypedDict, total=False):
    id: str
    patient_id: str
    conference_id: Optional[str]
    service_date: str
    documented_minutes: int
    modality: str
    modifier_code: Optional[str]
    billable_units: int
    allowed_amount_cents: int
    coinsurance_pct: float
    patient_responsibility_cents: int
    net_payable_cents: int
    concurrent_care_carve_out: bool
    documentation_attested: bool
    attested_by_user_id: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
