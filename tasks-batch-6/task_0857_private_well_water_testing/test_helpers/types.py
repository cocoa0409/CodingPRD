"""Domain types: entity TypedDicts, status enums, role enum.

All names follow the Private Well Water Testing PRD terminology.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    DRILLER = "Driller"
    LAB_ANALYST = "LabAnalyst"
    HEALTH_OFFICER = "HealthOfficer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class WellRegistryStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PERMITTED = "PERMITTED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class WellPotabilityStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    POTABLE = "POTABLE"
    ADVISORY = "ADVISORY"
    UNSAFE = "UNSAFE"


class DrillerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ConstructionPermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class WaterSampleStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    IN_ANALYSIS = "IN_ANALYSIS"
    RESULTED = "RESULTED"
    INVALIDATED = "INVALIDATED"


class AdvisoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ContaminationCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATION = "MITIGATION"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class AbandonmentPermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    COMPLETED = "COMPLETED"


class RequirementStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class AdvisoryLevel(str, Enum):
    SAFE = "SAFE"
    ADVISORY = "ADVISORY"
    UNSAFE = "UNSAFE"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true — carry id + created_at + updated_at + version
class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    mailing_state: str
    net_fees_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Driller(TypedDict):
    id: str
    license_number: str
    license_state: str
    license_expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable config: id + created_at only
class Aquifer(TypedDict):
    id: str
    name: str
    sensitivity: str
    min_setback_septic_ft: int
    min_setback_property_line_ft: int
    min_well_depth_ft: int
    created_at: str


class Well(TypedDict):
    id: str
    applicant_id: str
    aquifer_id: str
    latitude: float
    longitude: float
    parcel_apn: str
    intended_use: str
    registry_status: str
    potability_status: str
    depth_ft: Optional[int]
    active_advisory_count: int
    created_at: str
    updated_at: str
    version: int


class ConstructionPermit(TypedDict):
    id: str
    well_id: str
    applicant_id: str
    driller_id: str
    proposed_depth_ft: int
    setback_septic_ft: int
    setback_property_line_ft: int
    scheduled_start: str
    scheduled_end: str
    expedite: bool
    fee_estimate_cents: int
    fee_final_cents: Optional[int]
    fee_charged_cents: int
    fee_refunded_cents: int
    fee_paid: bool
    issued_on: Optional[str]
    expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DrillerLog(TypedDict):
    id: str
    construction_permit_id: str
    driller_id: str
    total_depth_ft: int
    static_water_level_ft: int
    casing_depth_ft: int
    grout_type: str
    completed_on: str
    created_at: str
    updated_at: str
    version: int


class WaterSample(TypedDict):
    id: str
    well_id: str
    submitted_by_applicant_id: str
    sample_type: str
    requested_analytes: List[str]
    collected_on: str
    chain_of_custody_id: str
    panel_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only lab record: id + created_at only
class SampleResult(TypedDict):
    id: str
    water_sample_id: str
    bacteria_coliform: str
    ecoli: str
    nitrate_mg_l: float
    lead_ppb: float
    analyzed_on: str
    advisory_level_provisional: str
    advisory_level_confirmed: str
    exceedances: List[str]
    created_at: str


class Advisory(TypedDict):
    id: str
    well_id: str
    source_case_id: Optional[str]
    advisory_type: str
    effective_from: str
    effective_to: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContaminationCase(TypedDict):
    id: str
    well_id: str
    source_sample_id: Optional[str]
    severity: str
    opened_by_officer_id: str
    closed_by_officer_id: Optional[str]
    resolution_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AbandonmentPermit(TypedDict):
    id: str
    well_id: str
    applicant_id: str
    driller_id: str
    reason: str
    method: str
    completed_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RealEstateTestRequirement(TypedDict):
    id: str
    well_id: str
    applicant_id: str
    transaction_type: str
    closing_date: str
    required_analytes: List[str]
    linked_sample_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
