"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PRODUCER = "Producer"
    COUNTY_SPECIALIST = "CountySpecialist"
    COUNTY_EXECUTIVE_DIRECTOR = "CountyExecutiveDirector"
    COUNTY_COMMITTEE = "CountyCommittee"


class FarmStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECONSTITUTION_PENDING = "RECONSTITUTION_PENDING"
    RECONSTITUTED = "RECONSTITUTED"
    RETIRED = "RETIRED"


class ArcCoIcIndicator(str, Enum):
    COUNTY = "COUNTY"
    INDIVIDUAL = "INDIVIDUAL"


class EntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    CORPORATION = "CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"
    TRUST = "TRUST"
    LLC = "LLC"


class AgiAttestationStatus(str, Enum):
    NOT_FILED = "NOT_FILED"
    FILED = "FILED"
    VERIFIED = "VERIFIED"
    NONCOMPLIANT = "NONCOMPLIANT"


class ConservationStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    PENDING = "PENDING"
    VIOLATION = "VIOLATION"
    EXEMPT = "EXEMPT"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class TractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DIVIDED = "DIVIDED"
    COMBINED = "COMBINED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    CERTIFIED = "CERTIFIED"
    LATE_FILED = "LATE_FILED"
    REJECTED = "REJECTED"


class IntendedUse(str, Enum):
    GRAIN = "GRAIN"
    SILAGE = "SILAGE"
    HAY = "HAY"
    GRAZE = "GRAZE"
    COVER = "COVER"


class ElectionCode(str, Enum):
    PLC = "PLC"
    ARC_CO = "ARC_CO"
    ARC_IC = "ARC_IC"


class ElectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    LOCKED = "LOCKED"


class YieldStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    UPDATED = "UPDATED"
    CERTIFIED = "CERTIFIED"
    LOCKED = "LOCKED"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CED_APPROVED = "CED_APPROVED"
    CERTIFIED = "CERTIFIED"
    PAYMENT_COMPUTED = "PAYMENT_COMPUTED"
    PAYMENT_ISSUED = "PAYMENT_ISSUED"
    ON_APPEAL = "ON_APPEAL"
    REMANDED = "REMANDED"
    VOID = "VOID"


class DisasterType(str, Enum):
    DROUGHT = "DROUGHT"
    FLOOD = "FLOOD"
    HAIL = "HAIL"
    FREEZE = "FREEZE"
    WILDFIRE = "WILDFIRE"
    EXCESS_MOISTURE = "EXCESS_MOISTURE"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AppealStatus(str, Enum):
    FILED = "FILED"
    CED_REVIEW = "CED_REVIEW"
    COMMITTEE_HEARING = "COMMITTEE_HEARING"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"
    CLOSED = "CLOSED"


class GroundCode(str, Enum):
    FACTUAL_ERROR = "FACTUAL_ERROR"
    PROCEDURAL_ERROR = "PROCEDURAL_ERROR"
    MISAPPLICATION_OF_RULE = "MISAPPLICATION_OF_RULE"
    NEW_EVIDENCE = "NEW_EVIDENCE"


class ReconstitutionMethod(str, Enum):
    DIVIDE = "DIVIDE"
    COMBINE = "COMBINE"


# --- Entity TypedDicts (full common-fields set: id, created_at, updated_at, version) ---


class Farm(TypedDict):
    id: str
    farm_number: str
    county_code: str
    program_year: int
    farm_status: str
    total_base_acres: float
    arc_co_ic_indicator: str
    created_at: str
    updated_at: str
    version: int


class Producer(TypedDict):
    id: str
    producer_name: str
    tax_id_last4: str
    entity_type: str
    agi_attestation_status: str
    adjusted_gross_income: Optional[int]
    payment_limitation_cap_cents: int
    conservation_status: str
    created_at: str
    updated_at: str
    version: int


class FarmMembership(TypedDict):
    id: str
    farm_id: str
    producer_id: str
    share_percent: float
    is_spouse_pair: bool
    membership_status: str
    created_at: str
    updated_at: str
    version: int


class Tract(TypedDict):
    id: str
    farm_id: str
    tract_number: str
    base_acres: float
    cropland_acres: float
    tract_status: str
    reconstituted_from_tract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict):
    id: str
    tract_id: str
    field_number: str
    acres: float
    created_at: str
    updated_at: str
    version: int


class AcreageReport(TypedDict):
    id: str
    farm_id: str
    program_year: int
    report_status: str
    reported_acres: float
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcreageReportLine(TypedDict):
    id: str
    acreage_report_id: str
    field_id: str
    crop_code: str
    planted_acres: float
    prevented_planted_acres: float
    intended_use: str
    created_at: str
    updated_at: str
    version: int


class ProgramElection(TypedDict):
    id: str
    farm_id: str
    program_year: int
    commodity: str
    election_code: str
    election_status: str
    effective_from_version: int
    created_at: str
    updated_at: str
    version: int


class YieldRecord(TypedDict):
    id: str
    farm_id: str
    commodity: str
    aph_yield_bu_per_acre: float
    yield_status: str
    update_window_open: bool
    created_at: str
    updated_at: str
    version: int


class YieldObservation(TypedDict):
    # Append-only entity (PRD §2.4): carries ONLY id + created_at.
    id: str
    created_at: str
    yield_record_id: str
    crop_year: int
    actual_yield_bu_per_acre: Optional[float]
    is_disaster_substituted: bool


class Enrollment(TypedDict):
    id: str
    farm_id: str
    program_year: int
    commodity: str
    enrollment_status: str
    pinned_election_id: Optional[str]
    pinned_yield_record_id: Optional[str]
    computed_payment_cents: Optional[int]
    sequestration_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DisasterApplication(TypedDict):
    id: str
    farm_id: str
    program_year: int
    disaster_type: str
    application_status: str
    loss_acres: float
    qualifying_commodity: str
    documentation_complete: bool
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    farm_id: str
    enrollment_id: str
    appeal_status: str
    ground_code: str
    remands_appeal_id: Optional[str]
    filed_by_producer_id: str
    assigned_reviewer_producer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
