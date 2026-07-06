"""Domain types: entity TypedDicts, status enums, role enum for the National Cemetery API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    NCA_ADMIN = "NCA_Admin"
    ELIGIBILITY_OFFICER = "EligibilityOfficer"
    SCHEDULING_CLERK = "SchedulingClerk"
    MARKER_CLERK = "MarkerClerk"
    HONORS_COORDINATOR = "HonorsCoordinator"


class SectionKind(str, Enum):
    IN_GROUND = "IN_GROUND"
    COLUMBARIUM = "COLUMBARIUM"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    DECOMMISSIONED = "DECOMMISSIONED"


class GravesiteClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZE = "OVERSIZE"
    CREMATION = "CREMATION"


class CaseType(str, Enum):
    AT_NEED = "AT_NEED"
    PRE_NEED = "PRE_NEED"


class ApplicantRole(str, Enum):
    VETERAN = "VETERAN"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"


class DischargeCharacter(str, Enum):
    HONORABLE = "HONORABLE"
    GENERAL = "GENERAL"
    OTHER_THAN_HONORABLE = "OTHER_THAN_HONORABLE"
    DISHONORABLE = "DISHONORABLE"


class RequestedClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZE = "OVERSIZE"
    CREMATION = "CREMATION"


class AssignedUnitType(str, Enum):
    GRAVESITE = "GRAVESITE"
    NICHE = "NICHE"


class BurialCaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ASSIGNED = "ASSIGNED"
    SCHEDULED = "SCHEDULED"
    INTERRED = "INTERRED"
    CANCELLED = "CANCELLED"


class EligibilityDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class EligibilityBasis(str, Enum):
    VETERAN_SERVICE = "VETERAN_SERVICE"
    DERIVED_SPONSOR = "DERIVED_SPONSOR"
    DIED_IN_SERVICE = "DIED_IN_SERVICE"
    OVERSEAS_ONLY = "OVERSEAS_ONLY"


class DenialReason(str, Enum):
    DISCHARGE_BAR = "DISCHARGE_BAR"
    INSUFFICIENT_SERVICE = "INSUFFICIENT_SERVICE"
    SPONSOR_NOT_ELIGIBLE = "SPONSOR_NOT_ELIGIBLE"
    CEMETERY_MISMATCH = "CEMETERY_MISMATCH"


class PreNeedStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESERVED = "RESERVED"
    EXPIRED = "EXPIRED"


class IntermentScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MarkerType(str, Enum):
    UPRIGHT_MARBLE = "UPRIGHT_MARBLE"
    FLAT_GRANITE = "FLAT_GRANITE"
    FLAT_BRONZE = "FLAT_BRONZE"
    NICHE_COVER = "NICHE_COVER"


class MarkerOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ENGRAVED = "ENGRAVED"
    CANCELLED = "CANCELLED"


class DetailSize(str, Enum):
    TWO_PERSON = "TWO_PERSON"
    FULL_SQUAD = "FULL_SQUAD"


class MilitaryHonorsStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    RENDERED = "RENDERED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ---

# common_fields: true
class Cemetery(TypedDict):
    id: str
    name: str
    country_code: str
    is_overseas: bool
    honors_squad_capacity: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Section(TypedDict):
    id: str
    cemetery_id: str
    code: str
    kind: str
    capacity_units: int
    available_units: int
    interred_units: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Gravesite(TypedDict):
    id: str
    section_id: str
    grid_ref: str
    gravesite_class: str
    depth_capacity: int
    interment_count: int
    status: str
    reserved_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Niche(TypedDict):
    id: str
    section_id: str
    niche_ref: str
    urn_capacity: int
    inurnment_count: int
    status: str
    reserved_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class BurialCase(TypedDict):
    id: str
    cemetery_id: str
    case_type: str
    applicant_role: str
    reserving_case_id: Optional[str]
    is_overseas_case: bool
    character_of_discharge: Optional[str]
    service_days: int
    died_on_active_duty: bool
    requested_class: str
    entitlement_score: Optional[int]
    assigned_unit_type: Optional[str]
    assigned_gravesite_id: Optional[str]
    assigned_niche_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable audit record: id + created_at only, NO updated_at, NO version
class EligibilityDetermination(TypedDict):
    id: str
    burial_case_id: str
    decision: str
    basis: Optional[str]
    denial_reason: Optional[str]
    decided_by_user_id: str
    created_at: str


# common_fields: true
class PreNeedDetermination(TypedDict):
    id: str
    burial_case_id: str
    pmc_number: Optional[str]
    status: str
    expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class IntermentSchedule(TypedDict):
    id: str
    burial_case_id: str
    gravesite_id: Optional[str]
    niche_id: Optional[str]
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class MarkerOrder(TypedDict):
    id: str
    burial_case_id: str
    marker_type: str
    inscription_lines: List[str]
    emblem_of_belief: Optional[str]
    billable_characters: Optional[int]
    marker_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class MilitaryHonors(TypedDict):
    id: str
    interment_schedule_id: str
    detail_size: str
    flag_issued: bool
    honors_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
