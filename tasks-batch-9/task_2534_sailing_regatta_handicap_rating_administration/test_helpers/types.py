"""Domain types: entity TypedDicts, status enums and the role enum.

Field names and status vocabularies are taken verbatim from the PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Roles (PRD 2.1) ────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CLUB_ADMIN = "ClubAdmin"
    REGATTA_CHAIR = "RegattaChair"
    MEASURER = "Measurer"
    RACE_OFFICER = "RaceOfficer"
    JURY_CHAIR = "JuryChair"
    COMPETITOR = "Competitor"


# ── Status vocabularies ────────────────────────────────────────────────────
class JudgeCertificationLevel(str, Enum):
    NONE = "NONE"
    CLUB = "CLUB"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"
    INTERNATIONAL = "INTERNATIONAL"


class BoatType(str, Enum):
    MONOHULL = "MONOHULL"
    MULTIHULL = "MULTIHULL"
    KEELBOAT_SPORT = "KEELBOAT_SPORT"


class RuleCode(str, Enum):
    TOD_PHRF = "TOD_PHRF"
    TOT_ORC = "TOT_ORC"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


class RegattaStatus(str, Enum):
    DRAFT = "DRAFT"
    NOR_PUBLISHED = "NOR_PUBLISHED"
    SI_PUBLISHED = "SI_PUBLISHED"
    RACING = "RACING"
    SCORED = "SCORED"


class ScoringSystem(str, Enum):
    LOW_POINT = "LOW_POINT"
    BONUS_POINT = "BONUS_POINT"


class DiscardPolicy(str, Enum):
    NONE = "NONE"
    ONE_PER_FIVE = "ONE_PER_FIVE"
    ONE_PER_FOUR = "ONE_PER_FOUR"


class HandicapBasis(str, Enum):
    PER_CERTIFICATE = "PER_CERTIFICATE"
    UNIFIED_TOD = "UNIFIED_TOD"


class SafetyCategory(str, Enum):
    CAT_4 = "CAT_4"
    CAT_3 = "CAT_3"
    CAT_2 = "CAT_2"


class DocType(str, Enum):
    NOR = "NOR"
    SI = "SI"


class DocumentStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class BoatTypeFilter(str, Enum):
    MONOHULL = "MONOHULL"
    MULTIHULL = "MULTIHULL"
    KEELBOAT_SPORT = "KEELBOAT_SPORT"
    ANY = "ANY"


class DivisionStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    MERGED = "MERGED"


class RegistrationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RATING_INVALID = "RATING_INVALID"
    WITHDRAWN = "WITHDRAWN"


class InspectionStatus(str, Enum):
    NOT_INSPECTED = "NOT_INSPECTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CrewPosition(str, Enum):
    HELM = "HELM"
    TACTICIAN = "TACTICIAN"
    TRIM = "TRIM"
    BOW = "BOW"
    FLOATER = "FLOATER"


class DutyPosition(str, Enum):
    PRO = "PRO"
    TIMEKEEPER = "TIMEKEEPER"
    SIGNALS = "SIGNALS"
    MARK_BOAT_DRIVER = "MARK_BOAT_DRIVER"
    SAFETY_BOAT = "SAFETY_BOAT"


class DutyStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class CourseCode(str, Enum):
    WINDWARD_LEEWARD = "WINDWARD_LEEWARD"
    TRIANGLE = "TRIANGLE"
    DISTANCE_COASTAL = "DISTANCE_COASTAL"


class StartStatus(str, Enum):
    PENDING = "PENDING"
    SEQUENCE_STARTED = "SEQUENCE_STARTED"
    GENERAL_RECALLED = "GENERAL_RECALLED"
    STARTED = "STARTED"
    ABANDONED = "ABANDONED"


class ScoringStatus(str, Enum):
    NOT_SCORED = "NOT_SCORED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StartBlockedReason(str, Enum):
    DIVISION_UNDER_MINIMUM = "DIVISION_UNDER_MINIMUM"


class FinishStatus(str, Enum):
    FINISHED = "FINISHED"
    DNF = "DNF"
    DNS = "DNS"
    RET = "RET"
    DNC = "DNC"
    OCS = "OCS"
    DSQ = "DSQ"
    RDG = "RDG"


RECORDABLE_FINISH_STATUSES = ["FINISHED", "DNF", "DNS", "RET", "DNC"]
DERIVED_ONLY_FINISH_STATUSES = ["OCS", "DSQ", "RDG"]


class RecallType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GENERAL = "GENERAL"


class PanelStatus(str, Enum):
    FORMING = "FORMING"
    SEATED = "SEATED"


class SeatRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARD = "HEARD"
    DECIDED = "DECIDED"
    REOPENED = "REOPENED"
    INVALID = "INVALID"


class ProtestDecision(str, Enum):
    NONE = "NONE"
    PENALTY_DSQ = "PENALTY_DSQ"
    PENALTY_SCORING_20 = "PENALTY_SCORING_20"
    DISMISSED = "DISMISSED"
    REDRESS_GRANTED = "REDRESS_GRANTED"


class EvidenceKind(str, Enum):
    WRITTEN_STATEMENT = "WRITTEN_STATEMENT"
    WITNESS = "WITNESS"
    GPS_TRACK = "GPS_TRACK"
    PHOTO = "PHOTO"


# ── Entities (PRD 2.4, 3.1 – 3.10) ─────────────────────────────────────────
class ClubMember(TypedDict):
    id: str
    full_name: str
    email: str
    measurer_license_id: Optional[str]
    judge_certification_level: str
    safety_course_expiry_utc: Optional[str]
    assigned_duty_minutes: int
    created_at: str
    updated_at: str
    version: int


class Boat(TypedDict):
    id: str
    sail_number: str
    boat_name: str
    owner_member_id: str
    boat_type: str
    loa_meters: float
    created_at: str
    updated_at: str
    version: int


class RatingCertificate(TypedDict):
    id: str
    boat_id: str
    rule_code: str
    sail_area_m2: float
    hull_length_m: float
    displacement_kg: float
    draft_m: float
    raw_speed_index: float
    rating_value: float
    band_key_spm: float
    status: str
    measured_by_member_id: str
    valid_from: str
    valid_until: str
    suspension_reason_code: Optional[str]
    supersedes_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Regatta(TypedDict):
    id: str
    name: str
    host_club_name: str
    status: str
    scoring_system: str
    discard_policy: str
    handicap_basis: str
    safety_category: str
    planned_race_count: int
    fleet_minimum: int
    protest_time_limit_minutes: int
    jury_quorum_required: int
    series_start_utc: str
    nor_revision: int
    si_revision: int
    confirmed_division_count: int
    final_race_count: int
    created_at: str
    updated_at: str
    version: int


class RaceDocument(TypedDict):
    id: str
    regatta_id: str
    doc_type: str
    revision: int
    body_summary: str
    effective_utc: str
    amends_document_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Division(TypedDict):
    id: str
    regatta_id: str
    code: str
    boat_type_filter: str
    rating_band_low: float
    rating_band_high: float
    min_entries: int
    status: str
    assigned_entry_count: int
    accepted_entry_count: int
    merged_into_division_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewManifestElement(TypedDict):
    member_id: str
    position: str
    weight_kg: float


class Entry(TypedDict):
    id: str
    regatta_id: str
    boat_id: str
    certificate_id: str
    helm_member_id: str
    declared_crew_count: int
    registration_status: str
    inspection_status: str
    crew_manifest: List[CrewManifestElement]
    registered_crew_count: int
    crew_weight_kg: float
    division_id: Optional[str]
    equipment_deficiency_code: Optional[str]
    series_points_gross: float
    series_points_net: float
    discarded_race_numbers: List[int]
    series_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MarkBoat(TypedDict):
    id: str
    regatta_id: str
    call_sign: str
    crew_capacity: int
    concurrent_assignment_limit: int
    turnaround_buffer_minutes: int
    committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class DutyAssignment(TypedDict):
    id: str
    regatta_id: str
    race_id: Optional[str]
    member_id: str
    mark_boat_id: Optional[str]
    position: str
    window_start_utc: str
    window_end_utc: str
    duty_minutes: int
    status: str
    release_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Race(TypedDict):
    id: str
    regatta_id: str
    race_number: int
    course_code: str
    course_distance_nm: float
    scheduled_start_utc: str
    actual_start_utc: Optional[str]
    start_status: str
    scoring_status: str
    general_recall_count: int
    black_flag_active: bool
    start_blocked_reason: Optional[str]
    staffing_ready: bool
    staffed_position_codes: List[str]
    points_pool_total: float
    results_closed_utc: Optional[str]
    rescore_count: int
    abandon_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RaceResult(TypedDict):
    id: str
    race_id: str
    entry_id: str
    finish_status: str
    elapsed_seconds: Optional[float]
    corrected_seconds: Optional[float]
    penalty_percent: int
    place: Optional[int]
    points: float
    discardable: bool
    voided: bool
    created_at: str
    updated_at: str
    version: int


class RecallEvent(TypedDict):
    """Append-only signal record: carries only `id` and `created_at`
    as audit columns — no `updated_at` and no `version` (PRD 2.4)."""

    id: str
    race_id: str
    recall_type: str
    entry_id: Optional[str]
    signal_utc: str
    reason_code: str
    recorded_by_member_id: str
    resulting_start_status: str
    black_flag_applied: bool
    created_at: str


class JurySeat(TypedDict):
    member_id: str
    seat_role: str
    recused: bool
    seated_utc: str


class JuryPanel(TypedDict):
    id: str
    regatta_id: str
    chair_member_id: str
    seats: List[JurySeat]
    seated_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceLogElement(TypedDict):
    kind: str
    summary: str
    submitted_by_entry_id: str
    recorded_utc: str


class Protest(TypedDict):
    id: str
    regatta_id: str
    race_id: str
    protestor_entry_id: str
    protestee_entry_id: str
    rule_cited: str
    incident_utc: str
    filed_utc: str
    status: str
    jury_panel_id: Optional[str]
    hearing_utc: Optional[str]
    evidence_log: List[EvidenceLogElement]
    evidence_count: int
    decision: str
    penalty_target_entry_id: Optional[str]
    redress_race_number: Optional[int]
    reopen_count: int
    invalid_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeriesStanding(TypedDict):
    entry_id: str
    division_id: Optional[str]
    gross_points: float
    net_points: float
    discarded_race_numbers: List[int]
    races_counted: int
    rank: Optional[int]
    tie_break_trace: str


class StaffingReadout(TypedDict):
    race_id: str
    staffing_ready: bool
    staffed_position_codes: List[str]
    missing_position_codes: List[str]
    coverage_window_start_utc: str
    coverage_window_end_utc: str
