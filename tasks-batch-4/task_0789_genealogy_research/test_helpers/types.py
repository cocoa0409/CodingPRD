"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the Genealogy Research API contract. Every entity carries the
four common properties (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CLIENT = "Client"
    RESEARCHER = "Researcher"
    PROJECT_MANAGER = "ProjectManager"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ResearchStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    RESEARCH_COMPLETE = "RESEARCH_COMPLETE"


class RecordSearchStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    NO_RESULTS = "NO_RESULTS"
    CANCELLED = "CANCELLED"


class CitationVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class SourceType(str, Enum):
    VITAL_RECORD = "VITAL_RECORD"
    CENSUS = "CENSUS"
    CHURCH = "CHURCH"
    DNA = "DNA"
    OTHER = "OTHER"


class CitationQuality(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    INDIRECT = "INDIRECT"


class PersonVerificationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"


class DnaStatus(str, Enum):
    ORDERED = "ORDERED"
    INTERPRETED = "INTERPRETED"
    CANCELLED = "CANCELLED"


class PredictedRelationship(str, Enum):
    PARENT_CHILD = "PARENT_CHILD"
    FULL_SIBLING = "FULL_SIBLING"
    CLOSE_FAMILY = "CLOSE_FAMILY"
    COUSIN = "COUSIN"
    UNRELATED = "UNRELATED"


class RetrievalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RETRIEVED = "RETRIEVED"
    UNAVAILABLE = "UNAVAILABLE"


class TranslationStatus(str, Enum):
    NOT_NEEDED = "NOT_NEEDED"
    PENDING = "PENDING"
    TRANSLATED = "TRANSLATED"


class HeirloomStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CATALOGUED = "CATALOGUED"
    DIGITIZED = "DIGITIZED"
    RETURNED = "RETURNED"


class HeirloomCategory(str, Enum):
    PHOTO = "PHOTO"
    DOCUMENT = "DOCUMENT"
    ARTIFACT = "ARTIFACT"
    TEXTILE = "TEXTILE"
    OTHER = "OTHER"


class DeliverableStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class DeliverableType(str, Enum):
    RESEARCH_REPORT = "RESEARCH_REPORT"
    FAMILY_TREE = "FAMILY_TREE"
    DNA_SUMMARY = "DNA_SUMMARY"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class TimeEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ActivityType(str, Enum):
    RESEARCH = "RESEARCH"
    WRITING = "WRITING"
    TRANSLATION = "TRANSLATION"
    ADMIN = "ADMIN"
    TRAVEL = "TRAVEL"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PackageType(str, Enum):
    HOURLY = "HOURLY"
    BASIC_PACKAGE = "BASIC_PACKAGE"
    PREMIUM_PACKAGE = "PREMIUM_PACKAGE"


class Priority(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class ClientTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


# --------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    name: str
    email: str
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Researcher(TypedDict):
    id: str
    name: str
    email: str
    hourly_rate_cents: int
    specialties: List[str]
    created_at: str
    updated_at: str
    version: int


class Repository(TypedDict):
    id: str
    name: str
    location: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class ResearchProject(TypedDict):
    id: str
    client_id: str
    lead_researcher_id: str
    title: str
    objective: str
    scope_note: str
    package_type: str
    package_price_cents: int
    budget_hours: float
    priority: str
    target_person_count: int
    status: str
    research_status: str
    consumed_hours: float
    verified_person_count: int
    accepted_deliverable_count: int
    ready_milestone_amount_cents: int
    estimated_cost_cents: int
    actual_cost_cents: int
    invoiced_total_cents: int
    credited_total_cents: int
    paid_total_cents: int
    outstanding_balance_cents: int
    billable_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class RecordSearch(TypedDict):
    id: str
    project_id: str
    performed_by_id: str
    repository_name: str
    search_terms: str
    estimated_hours: float
    result_summary: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SourceCitation(TypedDict):
    id: str
    project_id: str
    record_search_id: str
    person_id: str
    citation_text: str
    source_type: str
    quality: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class Person(TypedDict):
    id: str
    project_id: str
    father_id: Optional[str]
    mother_id: Optional[str]
    full_name: str
    birth_year: Optional[int]
    death_year: Optional[int]
    verification_status: str
    citation_count: int
    verified_citation_count: int
    provisional_confidence: float
    confidence_score: float
    created_at: str
    updated_at: str
    version: int


class DnaInterpretation(TypedDict):
    id: str
    project_id: str
    subject_person_id: str
    match_person_id: Optional[str]
    test_provider: str
    cm_shared: Optional[int]
    predicted_relationship: Optional[str]
    addon_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DocumentRequest(TypedDict):
    id: str
    project_id: str
    repository_id: str
    document_type: str
    source_language: str
    pages: int
    retrieval_status: str
    translation_status: str
    created_at: str
    updated_at: str
    version: int


class HeirloomItem(TypedDict):
    id: str
    project_id: str
    related_person_id: Optional[str]
    description: str
    category: str
    storage_location: str
    archive_status: str
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    project_id: str
    milestone_id: Optional[str]
    deliverable_type: str
    page_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    project_id: str
    deliverable_id: Optional[str]
    title: str
    amount_cents: int
    sequence_no: int
    invoiced_amount_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    project_id: str
    researcher_id: str
    record_search_id: Optional[str]
    hours: float
    activity_type: str
    billable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RepositoryAppointment(TypedDict):
    id: str
    repository_id: str
    project_id: str
    researcher_id: str
    start_utc: str
    end_utc: str
    purpose: str
    status: str
    created_at: str
    updated_at: str
    version: int
