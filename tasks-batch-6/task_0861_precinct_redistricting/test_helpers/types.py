"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CARTOGRAPHER = "Cartographer"
    DEMOGRAPHER = "Demographer"
    COMMISSION_CHAIR = "CommissionChair"
    ELECTION_CLERK = "ElectionClerk"
    PUBLIC_PARTICIPANT = "PublicParticipant"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMMENT_OPEN = "COMMENT_OPEN"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PrecinctStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SPLIT = "SPLIT"
    MERGED = "MERGED"
    RETIRED = "RETIRED"


class VoterCountBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class CommentDisposition(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INCORPORATED = "INCORPORATED"
    DISMISSED = "DISMISSED"


class BlockAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REMOVED = "REMOVED"


class PollingAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PollingPlaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ComplianceCheckType(str, Enum):
    POPULATION_DEVIATION = "POPULATION_DEVIATION"
    VRA_MINORITY = "VRA_MINORITY"
    CONTIGUITY = "CONTIGUITY"


class ComplianceResultStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class ExportFormat(str, Enum):
    GEOJSON = "GEOJSON"
    SHAPEFILE = "SHAPEFILE"


class ExportStatus(str, Enum):
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


# --- Entity TypedDicts (common_fields: true unless noted) ---

class Jurisdiction(TypedDict):
    id: str
    name: str
    state_code: str
    target_district_count: int
    required_majority_minority_districts: int
    total_population: int
    voting_age_population_total: int
    ideal_district_population: float
    created_at: str
    updated_at: str
    version: int


class CensusBlock(TypedDict):
    id: str
    jurisdiction_id: str
    geoid: str
    population: int
    voting_age_population: int
    minority_vap: int
    registered_voters: int
    precinct_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedistrictingPlan(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    parent_plan_id: Optional[str]
    created_by_user_id: str
    status: str
    max_abs_deviation_pct: float
    overall_deviation_range_pct: float
    majority_minority_district_count: int
    is_compliant: bool
    comment_opened_at: Optional[str]
    adopted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class District(TypedDict):
    id: str
    plan_id: str
    district_number: int
    name: Optional[str]
    is_contiguous: bool
    incumbent_name: Optional[str]
    incumbent_home_geoid: Optional[str]
    target_population: float
    assigned_population: int
    deviation: int
    deviation_pct: float
    minority_vap_pct: float
    is_majority_minority: bool
    incumbent_retained: bool
    created_at: str
    updated_at: str
    version: int


class BlockAssignment(TypedDict):
    id: str
    plan_id: str
    district_id: str
    census_block_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Precinct(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    parent_precinct_id: Optional[str]
    status: str
    voter_count_basis: str
    registered_voters: int
    created_at: str
    updated_at: str
    version: int


class PollingPlace(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    address: str
    capacity: int
    status: str
    assigned_registered_voters: int
    utilization_pct: float
    is_over_capacity: bool
    created_at: str
    updated_at: str
    version: int


class PollingAssignment(TypedDict):
    id: str
    precinct_id: str
    polling_place_id: str
    ev_start_date: str
    ev_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    plan_id: str
    venue_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    plan_id: str
    commenter_name: str
    comment_text: str
    disposition: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable snapshot: only id + created_at
class ComplianceCheck(TypedDict):
    id: str
    plan_id: str
    check_type: str
    result_status: str
    max_abs_deviation_pct: float
    overall_deviation_range_pct: float
    majority_minority_district_count: int
    detail: str
    created_at: str


class GISExport(TypedDict):
    id: str
    plan_id: str
    export_format: str
    status: str
    block_count: int
    district_count: int
    checksum: str
    created_at: str
    updated_at: str
    version: int
