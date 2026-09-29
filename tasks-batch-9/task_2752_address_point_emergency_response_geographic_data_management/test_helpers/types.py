"""TypedDict shapes and status enumerations for the GIS API entities.

Every entity except DiscrepancyProposal carries id, created_at, updated_at and
version. DiscrepancyProposal is an append-only log row and carries only id and
created_at.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

JURISDICTION_TYPES = ["COUNTY", "MUNICIPAL", "UNINCORPORATED"]
AGENCY_TYPES = ["LAW", "FIRE", "EMS"]
AGENCY_STATUSES = ["ACTIVE", "SUSPENDED"]

ROAD_STATUSES = ["DRAFT", "VALIDATED", "PUBLISHED", "RETIRED"]
PARITIES = ["EVEN", "ODD"]
SIDES = ["LEFT", "RIGHT"]

ADDRESS_POINT_STATUSES = ["PENDING", "ACTIVE", "RETIRED", "VOIDED"]
ADDRESS_SOURCES = ["PARCEL", "PERMIT", "POSTAL", "FIELD"]
UNIT_TYPES = ["UNIT", "APT", "STE", "BLDG"]
CONFIDENCE_BASES = ["PROVISIONAL", "CERTIFIED"]

REVIEW_STATUSES = ["PENDING_REVIEW", "GIS_APPROVED", "GIS_REJECTED"]
UTILITY_STATUSES = ["PENDING_UTILITY", "UTILITY_CLEARED", "UTILITY_HELD"]
FULFILLMENT_STATUSES = [
    "OPEN",
    "READY_TO_ASSIGN",
    "FULFILLED",
    "CLOSED_REJECTED",
    "VOIDED",
]

BOUNDARY_STATUSES = ["DRAFT", "PROPOSED", "ACTIVE", "RETIRED"]
CELL_ASSIGNMENT_STATUSES = ["PENDING", "ACTIVE", "RETIRED"]

QC_SCOPES = ["FULL", "JURISDICTION", "ROAD"]
QC_REPORT_STATUSES = ["GENERATED", "CERTIFIED", "REJECTED", "DECERTIFIED"]
QC_DEFECT_STATUSES = ["OPEN", "WAIVED"]
DEFECT_SEVERITIES = ["BLOCKING", "WARNING", "INFO"]
DEFECT_CATEGORIES = ["ADDRESS", "ROAD", "BOUNDARY"]
DEFECT_ENTITY_TYPES = ["ROAD_CENTERLINE", "ADDRESS_POINT", "COVERAGE_CELL"]
QUALITY_TIERS = ["A", "B", "C", "D"]

PACKAGE_CHANNELS = ["DISPATCH_E911", "MAPPING", "PUBLIC"]
PACKAGE_STATUSES = [
    "DRAFT",
    "SEALED",
    "PUBLISHED",
    "SUPERSEDED",
    "INVALIDATED",
    "ROLLED_BACK",
]
PACKAGE_RECORD_TYPES = [
    "ADDRESS_POINT",
    "ROAD_CENTERLINE",
    "EMERGENCY_SERVICE_BOUNDARY",
]
PIN_STATES = ["FRESH", "STALE"]
INVALIDATED_REASONS = ["PIN_STALE", "REPORT_DECERTIFIED"]

CASE_SUBJECT_TYPES = ["ROAD_NAME", "ADDRESS_RANGE", "BOUNDARY_CELL"]
CASE_STATUSES = [
    "OPEN",
    "PROPOSAL_PENDING",
    "COUNTERED",
    "CONCURRED",
    "ESCALATED",
    "ADOPTED",
    "ARBITRATED",
]
PROPOSAL_SIDES = ["OPENER", "COUNTERPARTY"]
PROPOSAL_PROJECTED_STATUSES = ["PENDING", "COUNTERED", "ADOPTED", "VOIDED"]
DECERTIFIED_REASONS = ["SUBJECT_RECORD_CHANGED"]


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(CommonFields):
    name: str
    code: str
    jurisdiction_type: str
    postal_city: str
    cell_count: int
    covered_cell_count: int
    gap_pair_count: int
    forward_gap_pair_count: int


class Agency(CommonFields):
    name: str
    agency_type: str
    jurisdiction_id: str
    contact_phone: Optional[str]
    status: str
    suspended_reason: Optional[str]


class CoverageCell(CommonFields):
    cell_code: str
    jurisdiction_id: str
    centroid_lat: Optional[float]
    centroid_lon: Optional[float]
    active_assignment_count: int


class RoadCenterline(CommonFields):
    primary_name: str
    normalized_name: str
    jurisdiction_id: str
    from_addr_left: int
    to_addr_left: int
    parity_left: str
    from_addr_right: int
    to_addr_right: int
    parity_right: str
    status: str
    qc_dirty: bool
    open_discrepancy_case_count: int
    assignable_slot_count_left: int
    assignable_slot_count_right: int
    retired_at: Optional[str]
    retire_reason: Optional[str]


class AddressPoint(CommonFields):
    house_number: int
    house_number_suffix: Optional[str]
    road_centerline_id: str
    jurisdiction_id: str
    side: str
    source: str
    postal_city: str
    cell_id: Optional[str]
    unit_type: Optional[str]
    unit_id: Optional[str]
    parent_address_point_id: Optional[str]
    unit_child_count: int
    geometry_verified: bool
    latitude: Optional[float]
    longitude: Optional[float]
    status: str
    confidence_score: float
    certified_confidence_score: Optional[float]
    confidence_basis: str
    retired_at: Optional[str]
    retire_reason: Optional[str]
    superseded_by_address_point_id: Optional[str]


class AddressAssignmentRequest(CommonFields):
    permit_number: str
    parcel_id: str
    road_centerline_id: str
    side: str
    requested_unit_count: int
    proposed_house_number: Optional[int]
    review_status: str
    utility_status: str
    fulfillment_status: str
    review_note: Optional[str]
    utility_note: Optional[str]
    assigned_house_number: Optional[int]
    assigned_address_point_id: Optional[str]
    minted_point_count: int
    void_reason: Optional[str]


class EmergencyServiceBoundary(CommonFields):
    agency_id: str
    service_type: str
    effective_start: str
    effective_end: Optional[str]
    status: str
    assigned_cell_count: int
    retired_at: Optional[str]
    retire_reason: Optional[str]


class BoundaryCellAssignment(CommonFields):
    boundary_id: str
    cell_id: str
    service_type: str
    effective_start: str
    effective_end: Optional[str]
    status: str


class QcValidationReport(CommonFields):
    scope: str
    jurisdiction_id: Optional[str]
    road_centerline_id: Optional[str]
    status: str
    generated_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    rejection_reason: Optional[str]
    decertified_reason: Optional[str]
    defect_count: int
    blocking_defect_count: int
    warning_defect_count: int
    info_defect_count: int
    open_blocking_defect_count: int
    waived_blocking_count: int
    quality_score: float
    advisory_quality_score: float
    quality_tier: str
    provisioning_eligibility_score: float
    is_provisioning_eligible: bool


class QcDefect(CommonFields):
    report_id: str
    defect_code: str
    severity: str
    defect_category: str
    entity_type: str
    entity_ref_id: str
    detail: str
    status: str
    waiver_reason: Optional[str]
    waived_by_user_id: Optional[str]
    waived_at: Optional[str]


class ProvisioningPackage(CommonFields):
    channel: str
    jurisdiction_id: str
    qc_report_id: str
    status: str
    package_version: Optional[int]
    record_count: int
    pinned_record_count: int
    fresh_pin_count: int
    stale_pin_count: int
    drift_detected: bool
    sealed_at: Optional[str]
    published_at: Optional[str]
    sealed_by_user_id: Optional[str]
    published_by_user_id: Optional[str]
    invalidated_reason: Optional[str]
    rollback_reason: Optional[str]


class PackageRecord(CommonFields):
    package_id: str
    record_type: str
    record_id: str
    pinned_version: int
    pin_state: str
    staled_at: Optional[str]


class DiscrepancyCase(CommonFields):
    subject_type: str
    subject_ref_id: str
    jurisdiction_id: str
    opened_by_agency_id: str
    counterparty_agency_id: str
    description: str
    status: str
    round_count: int
    current_proposal_id: Optional[str]
    concurred_by_side: Optional[str]
    resolved_value: Optional[str]
    escalated_at: Optional[str]
    adopted_at: Optional[str]


class DiscrepancyProposal(TypedDict):
    """Append-only log row: no updated_at and no version."""

    id: str
    created_at: str
    case_id: str
    round_number: int
    proposed_by_side: str
    proposed_value: str
    rationale: Optional[str]
    status: str


class CoverageStatus(TypedDict):
    cell_id: str
    evaluated_at: str
    covered_service_types: List[str]
    gap_service_types: List[str]
    proposed_conflict_service_types: List[str]
    responding_assignment_count: int
    forward_gap_service_types: List[str]


Payload = Dict[str, Any]
