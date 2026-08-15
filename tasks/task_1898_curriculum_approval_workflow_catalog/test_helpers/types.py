"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the PRD: departments, terms, courses,
proposals, decision records, requisite links, cross-listings, teach-out
plans, catalog editions, and catalog entries.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FACULTY_PROPOSER = "FacultyProposer"
    DEPARTMENT_CHAIR = "DepartmentChair"
    CURRICULUM_COMMITTEE = "CurriculumCommittee"
    FACULTY_SENATE = "FacultySenate"
    REGISTRAR = "Registrar"


class TermStatus(str, Enum):
    OPEN_FOR_PROPOSALS = "OPEN_FOR_PROPOSALS"
    PROPOSAL_FROZEN = "PROPOSAL_FROZEN"
    CATALOG_FROZEN = "CATALOG_FROZEN"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATING = "DEACTIVATING"
    INACTIVE = "INACTIVE"


class ProposalType(str, Enum):
    NEW_COURSE = "NEW_COURSE"
    COURSE_CHANGE = "COURSE_CHANGE"
    DEACTIVATION = "DEACTIVATION"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    DEPT_REVIEW = "DEPT_REVIEW"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    SENATE_REVIEW = "SENATE_REVIEW"
    REGISTRAR_REVIEW = "REGISTRAR_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DecisionAction(str, Enum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    REJECT = "REJECT"
    WITHDRAW = "WITHDRAW"
    NOTIFY = "NOTIFY"
    REASSIGN_TERM = "REASSIGN_TERM"
    ACTIVATE = "ACTIVATE"


class RequisiteType(str, Enum):
    PREREQUISITE = "PREREQUISITE"
    COREQUISITE = "COREQUISITE"


class RequisiteLinkStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class CrossListingStatus(str, Enum):
    PENDING = "PENDING"
    HOME_APPROVED = "HOME_APPROVED"
    PARTNER_APPROVED = "PARTNER_APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"


class TeachOutPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class CatalogEditionStatus(str, Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class CatalogEntryStatus(str, Enum):
    STAGED = "STAGED"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class Department(TypedDict, total=False):
    id: str
    dept_name: str
    subject_codes: List[str]
    college: str
    created_at: str
    updated_at: str
    version: int


class Term(TypedDict, total=False):
    id: str
    term_code: str
    academic_year: str
    sequence_index: int
    classes_start_date: str
    classes_end_date: str
    proposal_freeze_at: str
    catalog_freeze_at: str
    scheduled_proposal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    subject_code: str
    course_number: str
    title: str
    credit_hours: float
    contact_hours_per_week: float
    out_of_class_hours_per_week: float
    learning_outcomes: List[str]
    owning_department_id: str
    introduced_in_term_id: str
    prerequisite_summary: str
    last_published_edition_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict, total=False):
    id: str
    proposal_type: str
    proposer_id: str
    proposer_department_id: str
    target_course_id: Optional[str]
    proposed_subject_code: Optional[str]
    proposed_course_number: Optional[str]
    proposed_title: Optional[str]
    proposed_credit_hours: Optional[float]
    contact_hours_per_week: Optional[float]
    out_of_class_hours_per_week: Optional[float]
    learning_outcomes: Optional[List[str]]
    justification: Optional[str]
    proposed_requisites: List[dict]
    declared_remaining_cohorts: Optional[int]
    requested_effective_term_id: str
    effective_term_id: Optional[str]
    substantive_change_score: Optional[int]
    accreditor_notification_required: Optional[bool]
    notification_sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DecisionRecord(TypedDict, total=False):
    # Append-only audit entry: carries only id + created_at from the common
    # set; updated_at and version are absent on decision records (PRD §2.4).
    id: str
    created_at: str
    proposal_id: str
    action: str
    from_status: str
    to_status: str
    actor_role: str
    actor_id: str
    rationale: Optional[str]
    recorded_term_id: Optional[str]


class RequisiteLink(TypedDict, total=False):
    id: str
    course_id: Optional[str]
    requisite_course_id: str
    requisite_type: str
    proposal_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrossListing(TypedDict, total=False):
    id: str
    home_course_id: str
    partner_course_id: str
    home_department_id: str
    partner_department_id: str
    home_approved_by: Optional[str]
    partner_approved_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TeachOutPlan(TypedDict, total=False):
    id: str
    proposal_id: str
    course_id: str
    enrolled_cohort_count: int
    cohort_sizes: List[int]
    last_enrolled_term_id: str
    provisional_completion_sequence: Optional[int]
    committed_completion_sequence: Optional[int]
    resource_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogEdition(TypedDict, total=False):
    id: str
    edition_label: str
    academic_year: str
    year_start_date: str
    year_end_date: str
    included_entry_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogEntry(TypedDict, total=False):
    id: str
    edition_id: str
    course_id: str
    proposal_id: str
    subject_code: str
    course_number: str
    title: str
    credit_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int
