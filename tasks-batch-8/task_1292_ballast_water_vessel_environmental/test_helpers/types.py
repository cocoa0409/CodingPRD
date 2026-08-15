"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity and lifecycle descriptions. Entities described in
PRD section 2.4 as append-only ledger records (BallastWaterEvent,
RecordBookEntry) carry only ``id`` and ``created_at``; every other entity also
carries ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SHORE_COMPLIANCE_OFFICER = "ShoreComplianceOfficer"
    VESSEL_MASTER = "VesselMaster"
    FLAG_SURVEYOR = "FlagSurveyor"
    PSC_OFFICER = "PSCOfficer"


# ---------------------------------------------------------------------------
# Field-level enums
# ---------------------------------------------------------------------------

class BwmsType(str, Enum):
    NONE = "NONE"
    EXCHANGE_ONLY = "EXCHANGE_ONLY"
    TREATMENT_USCG_TYPE_APPROVED = "TREATMENT_USCG_TYPE_APPROVED"
    TREATMENT_ALTERNATIVE = "TREATMENT_ALTERNATIVE"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ApprovalAuthority(str, Enum):
    USCG = "USCG"
    CLASS_SOCIETY_ON_BEHALF = "CLASS_SOCIETY_ON_BEHALF"


class VoyageComplianceStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"
    EXEMPT = "EXEMPT"


class VoyageReportingStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERDUE = "OVERDUE"


class BallastEventKind(str, Enum):
    UPTAKE = "UPTAKE"
    DISCHARGE = "DISCHARGE"
    EXCHANGE_START = "EXCHANGE_START"
    EXCHANGE_COMPLETE = "EXCHANGE_COMPLETE"
    TREATMENT_START = "TREATMENT_START"
    TREATMENT_COMPLETE = "TREATMENT_COMPLETE"
    TANK_FLUSH = "TANK_FLUSH"
    SEDIMENT_DISPOSAL = "SEDIMENT_DISPOSAL"


class DeterminationBasis(str, Enum):
    EXCHANGE_COMPLIANT = "EXCHANGE_COMPLIANT"
    TREATMENT_COMPLIANT = "TREATMENT_COMPLIANT"
    EXEMPT_SAME_COTP = "EXEMPT_SAME_COTP"
    EXEMPT_NO_US_EEZ = "EXEMPT_NO_US_EEZ"
    NONCOMPLIANT_MIXED = "NONCOMPLIANT_MIXED"
    NONCOMPLIANT_NO_METHOD = "NONCOMPLIANT_NO_METHOD"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class TriggerReason(str, Enum):
    VOYAGE_DEPARTURE = "VOYAGE_DEPARTURE"
    BALLAST_EVENT_RECORDED = "BALLAST_EVENT_RECORDED"
    VOYAGE_ARRIVAL = "VOYAGE_ARRIVAL"
    MANUAL_RECOMPUTE = "MANUAL_RECOMPUTE"
    PLAN_AMENDMENT = "PLAN_AMENDMENT"


class ReportType(str, Enum):
    PRE_ARRIVAL = "PRE_ARRIVAL"
    POST_DISCHARGE = "POST_DISCHARGE"
    ANNUAL_SUMMARY = "ANNUAL_SUMMARY"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"


class InspectionKind(str, Enum):
    PORT_STATE_CONTROL = "PORT_STATE_CONTROL"
    FLAG_STATE = "FLAG_STATE"
    CLASS_SOCIETY = "CLASS_SOCIETY"
    COMPANY_INTERNAL = "COMPANY_INTERNAL"


class SampledByRole(str, Enum):
    PSC_OFFICER = "PSC_OFFICER"
    FLAG_SURVEYOR = "FLAG_SURVEYOR"
    COMPANY_AUDITOR = "COMPANY_AUDITOR"


class InspectionStatus(str, Enum):
    RECORDED = "RECORDED"
    EVALUATED = "EVALUATED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class NoncomplianceSourceType(str, Enum):
    SAMPLING_EXCEEDANCE = "SAMPLING_EXCEEDANCE"
    REPORT_OVERDUE = "REPORT_OVERDUE"
    MISSING_METHOD = "MISSING_METHOD"
    PSC_DEFICIENCY = "PSC_DEFICIENCY"
    DETERMINATION_NONCOMPLIANT = "DETERMINATION_NONCOMPLIANT"


class NoncomplianceSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class NoncomplianceResponseStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class PscActionCode(str, Enum):
    A10 = "A10"
    A15 = "A15"
    A16 = "A16"
    A17 = "A17"
    A99 = "A99"


class RectificationStatus(str, Enum):
    OPEN = "OPEN"
    RECTIFYING = "RECTIFYING"
    RECTIFIED = "RECTIFIED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"


class BookKind(str, Enum):
    BALLAST_WATER = "BALLAST_WATER"
    GARBAGE = "GARBAGE"
    SEWAGE = "SEWAGE"
    OILY_WATER = "OILY_WATER"


class RecordBookStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"


class EntryKind(str, Enum):
    UPTAKE = "UPTAKE"
    DISCHARGE = "DISCHARGE"
    EXCHANGE = "EXCHANGE"
    TREATMENT = "TREATMENT"
    TANK_FLUSH = "TANK_FLUSH"
    DISCHARGE_SEA = "DISCHARGE_SEA"
    DISCHARGE_RECEPTION = "DISCHARGE_RECEPTION"
    INCINERATION = "INCINERATION"
    DISCHARGE_TREATED = "DISCHARGE_TREATED"
    DISCHARGE_UNTREATED = "DISCHARGE_UNTREATED"
    BILGE_DISCHARGE = "BILGE_DISCHARGE"
    SLUDGE_DISPOSAL = "SLUDGE_DISPOSAL"
    ODM_FLUSH = "ODM_FLUSH"


class FuelType(str, Enum):
    HFO = "HFO"
    VLSFO = "VLSFO"
    MGO = "MGO"
    MDO = "MDO"
    LNG = "LNG"
    BIOFUEL_BLEND = "BIOFUEL_BLEND"


class EmissionsComplianceStatus(str, Enum):
    PENDING_EVAL = "PENDING_EVAL"
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"
    EXEMPT_SCRUBBER = "EXEMPT_SCRUBBER"


class DrillKind(str, Enum):
    BWMS_OPERATION = "BWMS_OPERATION"
    EMERGENCY_BALLAST_EXCHANGE = "EMERGENCY_BALLAST_EXCHANGE"
    OIL_SPILL_RESPONSE = "OIL_SPILL_RESPONSE"
    SEWAGE_SYSTEM = "SEWAGE_SYSTEM"
    GARBAGE_MANAGEMENT = "GARBAGE_MANAGEMENT"
    MARPOL_AWARENESS = "MARPOL_AWARENESS"


class DrillCompletionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class CaseSeverity(str, Enum):
    NOTICE_OF_VIOLATION = "NOTICE_OF_VIOLATION"
    CIVIL_PENALTY = "CIVIL_PENALTY"
    DETENTION_ORDER = "DETENTION_ORDER"


class CaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED_COMPLIANT = "CLOSED_COMPLIANT"
    CLOSED_PENALTY = "CLOSED_PENALTY"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Vessel(TypedDict, total=False):
    id: str
    imo_number: str
    vessel_name: str
    flag_state: str
    bwms_type: str
    bwms_installation_date: Optional[str]
    gross_tonnage: int
    keel_laid_date: str
    ballast_capacity_m3: float
    compliance_posture: str
    active_enforcement_case_id: Optional[str]
    last_psc_inspection_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BallastWaterManagementPlan(TypedDict, total=False):
    id: str
    vessel_id: str
    plan_revision: int
    approval_authority: str
    approved_at: str
    status: str
    exchange_distance_nm: float
    sediment_management_included: bool
    created_at: str
    updated_at: str
    version: int


class Voyage(TypedDict, total=False):
    id: str
    vessel_id: str
    voyage_number: str
    departure_port: str
    arrival_port: str
    departed_at: str
    arrived_at: Optional[str]
    crosses_captain_of_port_zones: bool
    enters_us_eez: bool
    compliance_status: str
    reporting_status: str
    determination_id: Optional[str]
    bw_record_book_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger record (PRD section 2.4): carries ONLY id + created_at.
class BallastWaterEvent(TypedDict, total=False):
    id: str
    voyage_id: str
    event_kind: str
    occurred_at: str
    tank_id: str
    volume_m3: float
    latitude: Optional[float]
    longitude: Optional[float]
    distance_from_shore_nm: Optional[float]
    salinity_ppt: Optional[float]
    source_port_locode: Optional[str]
    created_at: str


class ComplianceDetermination(TypedDict, total=False):
    id: str
    voyage_id: str
    determination_basis: str
    exchange_compliant_volume_m3: float
    treatment_compliant_volume_m3: float
    noncompliant_volume_m3: float
    total_discharged_volume_m3: float
    computed_at: str
    is_current: bool
    trigger_reason: str
    created_at: str
    updated_at: str
    version: int


class BallastWaterReport(TypedDict, total=False):
    id: str
    voyage_id: str
    report_type: str
    due_at: Optional[str]
    submitted_at: Optional[str]
    status: str
    payload_summary: Optional[dict]
    rejection_reason: Optional[str]
    is_overdue: bool
    created_at: str
    updated_at: str
    version: int


class SamplingInspection(TypedDict, total=False):
    id: str
    voyage_id: str
    inspection_kind: str
    sampled_at: str
    sampled_by_role: str
    indicator_organism_concentration: float
    tss_mg_per_l: float
    findings: List[str]
    status: str
    exceeded: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class NoncomplianceRecord(TypedDict, total=False):
    id: str
    voyage_id: str
    source_type: str
    source_id: str
    severity: str
    detected_at: str
    response_status: str
    response_due_at: str
    escalated_to_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortStateControlDeficiency(TypedDict, total=False):
    id: str
    vessel_id: str
    voyage_id: str
    psc_inspection_id: str
    deficiency_code: str
    action_code: str
    rectification_deadline: str
    identified_at: str
    rectification_status: str
    rectified_at: Optional[str]
    verified_at: Optional[str]
    is_priority_one: bool
    created_at: str
    updated_at: str
    version: int


class RecordBook(TypedDict, total=False):
    id: str
    vessel_id: str
    book_kind: str
    voyage_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger record (PRD section 2.4): carries ONLY id + created_at.
class RecordBookEntry(TypedDict, total=False):
    id: str
    record_book_id: str
    entry_kind: str
    occurred_at: str
    quantity: float
    position_lat: Optional[float]
    position_lon: Optional[float]
    distance_from_shore_nm: Optional[float]
    signed_by: str
    countersigned_by: Optional[str]
    created_at: str


class EmissionsFuelRecord(TypedDict, total=False):
    id: str
    voyage_id: str
    fuel_type: str
    sulfur_content_pct: float
    consumed_volume_mt: float
    inside_eca_hours: float
    outside_eca_hours: float
    compliance_status: str
    scrubber_installed: bool
    created_at: str
    updated_at: str
    version: int


class CrewTrainingDrill(TypedDict, total=False):
    id: str
    vessel_id: str
    drill_kind: str
    scheduled_for: str
    completed_at: Optional[str]
    completion_status: str
    attendees: List[str]
    officer_present: Optional[bool]
    next_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementCase(TypedDict, total=False):
    id: str
    vessel_id: str
    opened_at: str
    opened_reason: Optional[str]
    severity: str
    status: str
    hold_flag: bool
    linked_noncompliance_ids: List[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
