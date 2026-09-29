"""Domain types: entity TypedDicts, status enums and the operator role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    SCHOOL_LIAISON = "SchoolLiaison"
    SITE_COORDINATOR = "SiteCoordinator"
    WAREHOUSE_LEAD = "WarehouseLead"
    DONOR_RELATIONS = "DonorRelations"


class GradeBand(str, Enum):
    K_2 = "K_2"
    G3_5 = "G3_5"
    G6_8 = "G6_8"
    G9_12 = "G9_12"


class ItemCategory(str, Enum):
    WRITING = "WRITING"
    PAPER = "PAPER"
    BINDER = "BINDER"
    HYGIENE = "HYGIENE"
    BACKPACK = "BACKPACK"


class SiteType(str, Enum):
    RETAIL = "RETAIL"
    CORPORATE = "CORPORATE"
    SCHOOL = "SCHOOL"
    LIBRARY = "LIBRARY"


class BatchCondition(str, Enum):
    NEW = "NEW"
    GENTLY_USED = "GENTLY_USED"
    DAMAGED = "DAMAGED"


class RestrictionType(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    ITEM_RESTRICTED = "ITEM_RESTRICTED"
    SCHOOL_RESTRICTED = "SCHOOL_RESTRICTED"


class VolunteerSessionType(str, Enum):
    SORTING = "SORTING"
    ASSEMBLY = "ASSEMBLY"


class Cadence(str, Enum):
    BACK_TO_SCHOOL = "BACK_TO_SCHOOL"
    YEAR_ROUND = "YEAR_ROUND"


class PartnershipStatus(str, Enum):
    PROSPECT = "PROSPECT"
    MOU_PENDING = "MOU_PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class KitSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class CyclePhase(str, Enum):
    DRAFT = "DRAFT"
    COLLECTING = "COLLECTING"
    SORTING = "SORTING"
    DISTRIBUTION = "DISTRIBUTION"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class SiteOperationalStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class SitePledgeStatus(str, Enum):
    NONE = "NONE"
    PLEDGED = "PLEDGED"
    PLEDGE_ACTIVE = "PLEDGE_ACTIVE"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REMEDIATED = "REMEDIATED"
    DISCARDED = "DISCARDED"


class CashDonationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class VolunteerEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DistributionEventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    FULFILLED = "FULFILLED"
    NO_SHOW = "NO_SHOW"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class TeacherRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"


# --- Entity shapes.  Every persisted resource carries id/created_at/updated_at/version.


class School(TypedDict):
    id: str
    name: str
    district_code: str
    title_i_pct: float
    enrollment_count: int
    max_concurrent_seats: int
    partnership_status: str
    target_student_count: int
    students_served_interim_count: int
    students_served_audited_count: int
    no_show_count: int
    kits_delivered_count: int
    impact_index_interim: float
    impact_index_audited: float
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_cost_cents: int
    bulk_pack_size: int
    hygiene_sealed_required: bool
    catalog_active: bool
    created_at: str
    updated_at: str
    version: int


class GradeKitSpec(TypedDict):
    id: str
    school_id: str
    grade_band: str
    student_target_count: int
    status: str
    kit_unit_cost_cents: int
    line_count: int
    created_at: str
    updated_at: str
    version: int


class KitSpecLine(TypedDict):
    id: str
    grade_kit_spec_id: str
    supply_item_id: str
    qty_per_student: int
    substitutable: bool
    created_at: str
    updated_at: str
    version: int


class DriveCycle(TypedDict):
    id: str
    name: str
    cadence: str
    window_start: str
    window_end: str
    status: str
    cash_received_cents: int
    cash_allocated_cents: int
    cash_available_cents: int
    unrestricted_gross_cents: int
    supplemental_cap_cents: int
    total_items_on_hand: int
    created_at: str
    updated_at: str
    version: int


class CollectionSite(TypedDict):
    id: str
    drive_cycle_id: str
    name: str
    site_type: str
    bin_capacity: int
    operational_status: str
    pledge_status: str
    pledged_item_count: int
    accepted_item_count: int
    created_at: str
    updated_at: str
    version: int


class DonationBatch(TypedDict):
    id: str
    collection_site_id: str
    supply_item_id: str
    qty_declared: int
    condition: str
    sealed: bool
    status: str
    qty_accepted: int
    qty_rejected: int
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryPosition(TypedDict):
    id: str
    drive_cycle_id: str
    supply_item_id: str
    on_hand_qty: int
    reserved_qty: int
    distributed_qty: int
    damaged_qty: int
    accepted_donated_qty: int
    purchased_received_qty: int
    adjustment_qty: int
    in_transit_qty: int
    created_at: str
    updated_at: str
    version: int


class CashDonation(TypedDict):
    id: str
    drive_cycle_id: str
    donor_name: str
    amount_cents: int
    restriction_type: str
    restricted_supply_item_id: Optional[str]
    restricted_school_id: Optional[str]
    allocated_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    drive_cycle_id: str
    supply_item_id: str
    requested_unit_gap: int
    ordered_qty: int
    line_subtotal_cents: int
    admin_fee_cents: int
    total_cost_cents: int
    funding_allocations: List[dict]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerEvent(TypedDict):
    id: str
    collection_site_id: str
    event_type: str
    window_start: str
    window_end: str
    volunteer_count: int
    minor_volunteer_count: int
    adult_supervisor_count: int
    status: str
    planned_kit_capacity: int
    assembled_kit_count: int
    created_at: str
    updated_at: str
    version: int


class DistributionEvent(TypedDict):
    id: str
    school_id: str
    drive_cycle_id: str
    grade_band: str
    window_start: str
    window_end: str
    seat_capacity: int
    status: str
    provisional_fill_pct: float
    final_fill_pct: float
    confirmed_count: int
    waitlist_count: int
    served_student_count: int
    created_at: str
    updated_at: str
    version: int


class StudentRegistration(TypedDict):
    id: str
    distribution_event_id: str
    student_reference: str
    grade_band: str
    guardian_name: str
    free_lunch_eligible: bool
    income_verified: bool
    eligibility_status: str
    verified_at: Optional[str]
    reserved_unit_count: int
    created_at: str
    updated_at: str
    version: int


class TeacherRequest(TypedDict):
    id: str
    school_id: str
    drive_cycle_id: str
    supply_item_id: str
    teacher_name: str
    qty_requested: int
    justification: str
    request_cost_cents: int
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
