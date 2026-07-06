"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ADMIN = "Admin"
    INVESTIGATOR = "Investigator"
    PATHOLOGIST = "Pathologist"
    MEDICAL_EXAMINER = "MedicalExaminer"
    LAB_TECH = "LabTech"
    ANONYMOUS = "Anonymous"


class CaseStatus(str, Enum):
    REPORTED = "REPORTED"
    ACCEPTED = "ACCEPTED"
    INVESTIGATING = "INVESTIGATING"
    CERTIFIED = "CERTIFIED"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"


class JurisdictionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class CaseType(str, Enum):
    NATURAL = "NATURAL"
    ACCIDENT = "ACCIDENT"
    HOMICIDE = "HOMICIDE"
    PENDING = "PENDING"


class BodyStatus(str, Enum):
    INTAKE = "INTAKE"
    STORED = "STORED"
    RELEASED = "RELEASED"


class ExamStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SpecimenType(str, Enum):
    BLOOD = "BLOOD"
    URINE = "URINE"
    VITREOUS = "VITREOUS"
    TISSUE = "TISSUE"


class ChainStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SENT_TO_LAB = "SENT_TO_LAB"
    CONSUMED = "CONSUMED"
    DISCARDED = "DISCARDED"


class ToxPanel(str, Enum):
    BASIC = "BASIC"
    EXPANDED = "EXPANDED"
    CONFIRMATORY = "CONFIRMATORY"


class ToxResultStatus(str, Enum):
    ORDERED = "ORDERED"
    RESULTED = "RESULTED"
    AMENDED = "AMENDED"


class ToxInterpretation(str, Enum):
    PENDING = "PENDING"
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class MannerOfDeath(str, Enum):
    NATURAL = "NATURAL"
    ACCIDENT = "ACCIDENT"
    HOMICIDE = "HOMICIDE"
    UNDETERMINED = "UNDETERMINED"


class CertStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    AMENDED = "AMENDED"
    VOID = "VOID"


class KinRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"
    OTHER = "OTHER"


class PropertyItemStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    ESCHEATED = "ESCHEATED"


class ReleaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DispositionStatus(str, Enum):
    DECLARED = "DECLARED"
    APPROVED = "APPROVED"
    BURIED = "BURIED"


# All entities carry the full common-field set (id, created_at, updated_at, version).

class Case(TypedDict):
    id: str
    decedent_name: str
    reported_death_at: str
    death_location_county: str
    jurisdiction_status: Optional[str]
    case_type: str
    status: str
    investigator_user_id: str
    served_county: Optional[bool]
    autopsy_required: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investigator(TypedDict):
    id: str
    full_name: str
    badge_no: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Pathologist(TypedDict):
    id: str
    full_name: str
    license_no: str
    is_medical_examiner: bool
    created_at: str
    updated_at: str
    version: int


class CoolerUnit(TypedDict):
    id: str
    label: str
    slot_capacity: int
    temperature_c: float
    occupied_slots: int
    out_of_service: bool
    created_at: str
    updated_at: str
    version: int


class Body(TypedDict):
    id: str
    case_id: str
    tag_no: str
    cooler_unit_id: Optional[str]
    storage_status: str
    intake_at: Optional[str]
    released_at: Optional[str]
    release_blocked: bool
    created_at: str
    updated_at: str
    version: int


class AutopsyExam(TypedDict):
    id: str
    case_id: str
    pathologist_user_id: str
    scheduled_for: str
    duration_minutes: int
    exam_status: str
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    primary_finding: Optional[str]
    cause_of_death: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    body_id: str
    specimen_type: str
    collected_at: str
    chain_status: str
    created_at: str
    updated_at: str
    version: int


class ToxScreen(TypedDict):
    id: str
    specimen_id: str
    panel: str
    result_status: str
    ethanol_mg_dl: float
    interpretation: str
    created_at: str
    updated_at: str
    version: int


class DeathCertificate(TypedDict):
    id: str
    case_id: str
    certifying_me_user_id: Optional[str]
    cause_of_death: str
    manner_of_death: str
    cert_status: str
    amendment_count: int
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NextOfKin(TypedDict):
    id: str
    case_id: str
    full_name: str
    relationship: str
    verified: bool
    contacted_at: str
    created_at: str
    updated_at: str
    version: int


class PropertyItem(TypedDict):
    id: str
    case_id: str
    description: str
    valuation_cents: int
    item_status: str
    created_at: str
    updated_at: str
    version: int


class PropertyRelease(TypedDict):
    id: str
    case_id: str
    next_of_kin_id: str
    approver_user_id: Optional[str]
    release_status: str
    released_item_count: int
    created_at: str
    updated_at: str
    version: int


class IndigentDisposition(TypedDict):
    id: str
    case_id: str
    statutory_allowance_cents: int
    itemized_cost_cents: int
    county_payable_cents: int
    disposition_status: str
    created_at: str
    updated_at: str
    version: int
