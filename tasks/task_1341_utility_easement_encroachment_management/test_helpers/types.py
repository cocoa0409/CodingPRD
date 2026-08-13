"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    RIGHT_OF_WAY_AGENT = "RightOfWayAgent"
    TITLE_EXAMINER = "TitleExaminer"
    VEGETATION_INSPECTOR = "VegetationInspector"
    LITIGATION_COUNSEL = "LitigationCounsel"
    DEPARTMENT_DIRECTOR = "DepartmentDirector"


class EasementCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    MAPPING = "MAPPING"
    ACTIVE_MONITORING = "ACTIVE_MONITORING"
    RESOLUTION_PENDING = "RESOLUTION_PENDING"
    CLOSED_RESOLVED = "CLOSED_RESOLVED"
    CLOSED_CONDEMNED = "CLOSED_CONDEMNED"
    CLOSED_ABANDONED = "CLOSED_ABANDONED"


class DocumentKind(str, Enum):
    DEED = "DEED"
    PLAT = "PLAT"
    AMENDMENT = "AMENDMENT"
    JUDGMENT = "JUDGMENT"


class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED_DEFECTIVE = "REJECTED_DEFECTIVE"


class DiscoveredVia(str, Enum):
    AERIAL_SURVEY = "AERIAL_SURVEY"
    FIELD_INSPECTION = "FIELD_INSPECTION"
    THIRD_PARTY_REPORT = "THIRD_PARTY_REPORT"
    TITLE_SEARCH = "TITLE_SEARCH"


class EncroachmentType(str, Enum):
    STRUCTURE = "STRUCTURE"
    VEGETATION = "VEGETATION"
    FENCE = "FENCE"
    PAVEMENT = "PAVEMENT"
    UTILITY_CROSSING = "UTILITY_CROSSING"
    OTHER = "OTHER"


class SeverityTier(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


class EncroachmentStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    NOTIFIED = "NOTIFIED"
    NEGOTIATING = "NEGOTIATING"
    COUNTERED = "COUNTERED"
    REMOVAL_AGREED = "REMOVAL_AGREED"
    REMOVED = "REMOVED"
    ESCALATED_TO_LEGAL = "ESCALATED_TO_LEGAL"
    PERMITTED_RETROACTIVELY = "PERMITTED_RETROACTIVELY"
    WAIVED = "WAIVED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    TENDERED = "TENDERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_OWNER = "REJECTED_BY_OWNER"
    EXPIRED = "EXPIRED"
    CONDEMNATION_REFERRED = "CONDEMNATION_REFERRED"
    WITHDRAWN = "WITHDRAWN"


class PermitType(str, Enum):
    DRIVEWAY = "DRIVEWAY"
    LANDSCAPING = "LANDSCAPING"
    FENCE_RETENTION = "FENCE_RETENTION"
    STRUCTURE_RETENTION = "STRUCTURE_RETENTION"
    UTILITY_CROSSING = "UTILITY_CROSSING"


class PermitApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class FieldInspectionStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class VegetationZoneStatus(str, Enum):
    ACTIVE_MONITORING = "ACTIVE_MONITORING"
    VIOLATION_DETECTED = "VIOLATION_DETECTED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    CLEARED = "CLEARED"


class LocationWithinZone(str, Enum):
    WIRE_ZONE = "WIRE_ZONE"
    BORDER_ZONE = "BORDER_ZONE"


class ViolationStatus(str, Enum):
    DETECTED = "DETECTED"
    NOTIFIED = "NOTIFIED"
    REMEDIATED = "REMEDIATED"
    ESCALATED_TO_LEGAL = "ESCALATED_TO_LEGAL"
    EXEMPTED = "EXEMPTED"


class SearchScope(str, Enum):
    FULL_CHAIN = "FULL_CHAIN"
    CURRENT_OWNER = "CURRENT_OWNER"
    LIEN_ONLY = "LIEN_ONLY"


class TitleTaskStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED_CLEAN = "COMPLETED_CLEAN"
    COMPLETED_WITH_DEFECTS = "COMPLETED_WITH_DEFECTS"
    CANCELLED = "CANCELLED"


class ReferralReason(str, Enum):
    NEGOTIATION_FAILED = "NEGOTIATION_FAILED"
    VEGETATION_REMEDIATION_FAILED = "VEGETATION_REMEDIATION_FAILED"
    TITLE_DEFECT = "TITLE_DEFECT"
    CONDEMNATION = "CONDEMNATION"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    ACCEPTED = "ACCEPTED"
    FILED = "FILED"
    SETTLED = "SETTLED"
    JUDGMENT_OBTAINED = "JUDGMENT_OBTAINED"
    WITHDRAWN = "WITHDRAWN"


class EasementCase(TypedDict, total=False):
    id: str
    case_code: str
    utility_district: str
    county: str
    parcel_id: str
    easement_width_ft: float
    easement_area_sqft: float
    fair_market_value_per_sqft: float
    acquisition_budget_cents: int
    compensation_committed_cents: int
    compensation_balance_cents: int
    open_encroachment_count: int
    encroachment_pressure_score: float
    title_cleared: bool
    active_permit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EasementDocument(TypedDict, total=False):
    id: str
    case_id: str
    doc_kind: str
    instrument_number: str
    recording_date: str
    grantor_name: str
    grantee_name: str
    gis_polygon_wkt: str
    encumbrance_rank: Optional[int]
    width_ft: float
    supersedes_document_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Encroachment(TypedDict, total=False):
    id: str
    case_id: str
    discovered_via: str
    encroachment_type: str
    encroachment_area_sqft: float
    depth_into_easement_ft: float
    encroaches_document_id: str
    severity_tier: str
    estimated_removal_cost_cents: int
    owner_response_due_date: Optional[str]
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AcquisitionOffer(TypedDict, total=False):
    id: str
    case_id: str
    landowner_name: str
    landowner_contact: str
    offered_area_sqft: float
    base_compensation_cents: int
    negotiated_compensation_cents: int
    severance_damages_cents: int
    total_compensation_cents: int
    negotiation_round: int
    negotiation_deadline: Optional[str]
    requires_director_approval: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ThirdPartyPermit(TypedDict, total=False):
    id: str
    case_id: str
    encroachment_id: Optional[str]
    permittee_name: str
    permit_type: str
    requested_area_sqft: float
    requested_start_date: str
    requested_end_date: str
    annual_fee_cents: Optional[int]
    approval_status: str
    field_inspection_status: str
    insurance_certificate_on_file: bool
    created_at: str
    updated_at: str
    version: int


class VegetationZone(TypedDict, total=False):
    id: str
    case_id: str
    zone_label: str
    max_allowed_height_ft: float
    prohibited_species: List[str]
    wire_zone_width_ft: float
    border_zone_width_ft: float
    last_inspection_date: Optional[str]
    violation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VegetationViolation(TypedDict, total=False):
    id: str
    zone_id: str
    case_id: str
    species: str
    observed_height_ft: float
    location_within_zone: str
    excess_height_ft: float
    remediation_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleSearchTask(TypedDict, total=False):
    id: str
    case_id: str
    search_scope: str
    ordered_by: str
    completed_by: Optional[str]
    liens_found: int
    defects_found: int
    chain_of_title_json: Dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    version: int


class LitigationReferral(TypedDict, total=False):
    id: str
    case_id: str
    encroachment_id: Optional[str]
    referral_reason: str
    referred_by: str
    accepted_by: Optional[str]
    filing_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
