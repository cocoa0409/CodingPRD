"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4, most resources carry id/created_at/updated_at/version.
FloorPlanVersion, SafetyInspection, and AuditLogEntry are append-only —
they carry only id and created_at; no updated_at and no version on
those entities.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    VENUE_ADMIN = "VenueAdmin"
    VENUE_OPS = "VenueOps"
    EXHIBITOR = "Exhibitor"
    SERVICE_PROVIDER = "ServiceProvider"
    GATE_OPERATOR = "GateOperator"
    TEST_HARNESS = "TestHarness"


# ---------------------------------------------------------------------------
# Exhibition (PRD §3.1)
# ---------------------------------------------------------------------------
class ExhibitionStatus(str, Enum):
    DRAFT = "DRAFT"
    INTAKE_OPEN = "INTAKE_OPEN"
    ALLOCATION_PUBLISHED = "ALLOCATION_PUBLISHED"
    SETUP = "SETUP"
    OPEN = "OPEN"
    TEARDOWN = "TEARDOWN"
    CLOSED = "CLOSED"


class ExhibitionPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


# ---------------------------------------------------------------------------
# FloorPlanVersion (PRD §3.2)
# ---------------------------------------------------------------------------
class FloorPlanVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class FloorPlanCellKind(str, Enum):
    FIXED = "FIXED"
    MODULAR = "MODULAR"
    FIRE_SAFETY = "FIRE_SAFETY"


# ---------------------------------------------------------------------------
# Booth (PRD §3.2)
# ---------------------------------------------------------------------------
class BoothTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ISLAND = "ISLAND"


class BoothStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ALLOCATED = "ALLOCATED"
    RELOCATING = "RELOCATING"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# ExhibitorApplication (PRD §3.3)
# ---------------------------------------------------------------------------
class SponsorshipLevel(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    ALLOCATED = "ALLOCATED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# BoothAllocation (PRD §3.4)
# ---------------------------------------------------------------------------
class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    OBJECTED = "OBJECTED"
    RELOCATING = "RELOCATING"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# DockSlot (PRD §3.5)
# ---------------------------------------------------------------------------
class DockSlotWindowKind(str, Enum):
    MOVE_IN = "MOVE_IN"
    MOVE_OUT = "MOVE_OUT"


class DockSlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# SafetyInspection (PRD §3.5)
# ---------------------------------------------------------------------------
class SafetyInspectionKind(str, Enum):
    BOOTH_MOVE_IN = "BOOTH_MOVE_IN"
    PRE_OPEN = "PRE_OPEN"
    OVERNIGHT = "OVERNIGHT"


class SafetyInspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# WorkOrder (PRD §3.6)
# ---------------------------------------------------------------------------
class WorkOrderServiceCode(str, Enum):
    EXTRA_POWER = "EXTRA_POWER"
    FURNITURE = "FURNITURE"
    NETWORK = "NETWORK"
    CLEANING = "CLEANING"
    SECURITY = "SECURITY"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPATCHED = "DISPATCHED"
    EXECUTED = "EXECUTED"
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Ticket (PRD §3.7)
# ---------------------------------------------------------------------------
class TicketKind(str, Enum):
    VISITOR = "VISITOR"
    PROFESSIONAL_BUYER = "PROFESSIONAL_BUYER"
    STUDENT = "STUDENT"
    VIP = "VIP"


class TicketChannel(str, Enum):
    ONLINE_PRESALE = "ONLINE_PRESALE"
    ONSITE = "ONSITE"


class TicketStatus(str, Enum):
    ISSUED = "ISSUED"
    SCANNED_IN = "SCANNED_IN"
    SCANNED_OUT = "SCANNED_OUT"
    VOID = "VOID"
    REFUNDED = "REFUNDED"


# ---------------------------------------------------------------------------
# SponsorEntitlement (PRD §3.8)
# ---------------------------------------------------------------------------
class EntitlementCode(str, Enum):
    SIGNAGE = "SIGNAGE"
    PROGRAM_AD = "PROGRAM_AD"
    LOUNGE = "LOUNGE"
    SPEAKING_SLOT = "SPEAKING_SLOT"
    BRANDED_GIFT = "BRANDED_GIFT"


class SponsorTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class EntitlementStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    MISSED = "MISSED"
    MAKE_GOOD_OFFERED = "MAKE_GOOD_OFFERED"
    MAKE_GOOD_ACCEPTED = "MAKE_GOOD_ACCEPTED"
    WAIVED = "WAIVED"


# ---------------------------------------------------------------------------
# AuditLogEntry (PRD §2.11)
# ---------------------------------------------------------------------------
class AuditSubjectKind(str, Enum):
    ALLOCATION = "ALLOCATION"
    ENTITLEMENT = "ENTITLEMENT"


# ===========================================================================
# Entity TypedDicts — common_fields: true → id/created_at/updated_at/version
# ===========================================================================
class Exhibition(TypedDict, total=False):
    id: str
    name: str
    theme_code: str
    open_date: str
    close_date: str
    capacity_max: int
    status: str
    posture: str
    live_occupancy: int
    objection_window_hours: int
    allocation_published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hall(TypedDict, total=False):
    id: str
    exhibition_id: str
    hall_code: str
    zone_label: str
    aisle_label: str
    grid_rows: int
    grid_cols: int
    fire_safety_zone_cells: List[dict]
    floor_plan_active_version: int
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict, total=False):
    id: str
    hall_id: str
    floor_plan_version_id: str
    code: str
    cells: List[dict]
    tier: str
    is_corner: bool
    base_price_cents: int
    power_kw_capacity: float
    water_lpm_capacity: float
    network_mbps_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExhibitorApplication(TypedDict, total=False):
    id: str
    exhibition_id: str
    exhibitor_id: str
    theme_tags: List[str]
    requested_tier: str
    sponsorship_level: str
    seniority_years: int
    lottery_token: int
    priority_score: float
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoothAllocation(TypedDict, total=False):
    id: str
    application_id: str
    booth_id: str
    exhibition_id: str
    exhibitor_id: str
    quoted_price_cents: int
    status: str
    published_at: Optional[str]
    relocation_source_booth_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DockSlot(TypedDict, total=False):
    id: str
    exhibition_id: str
    dock_code: str
    window_kind: str
    start_at: str
    end_at: str
    allocation_id: Optional[str]
    crane_required: bool
    forklift_required: bool
    overnight_permit: bool
    status: str
    safety_inspection_passed: bool
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    exhibition_id: str
    allocation_id: str
    exhibitor_id: str
    lines: List[dict]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    status: str
    dispute_reason: Optional[str]
    resolved_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict, total=False):
    id: str
    exhibition_id: str
    kind: str
    channel: str
    price_cents: int
    qr_code: str
    group_id: Optional[str]
    status: str
    scanned_in_at: Optional[str]
    scanned_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorEntitlement(TypedDict, total=False):
    id: str
    exhibition_id: str
    exhibitor_id: str
    entitlement_code: str
    sponsor_tier: str
    deadline: str
    evidence_url: Optional[str]
    status: str
    make_good_credit_cents: int
    fulfillment_score: float
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only TypedDicts — id + created_at ONLY (common_fields: false)
# Per PRD §2.4, these MUST NOT carry updated_at or version.
# ===========================================================================
class FloorPlanVersion(TypedDict, total=False):
    id: str
    hall_id: str
    version_number: int
    status: str
    published_at: Optional[str]
    cells: List[dict]
    created_at: str


class SafetyInspection(TypedDict, total=False):
    id: str
    exhibition_id: str
    dock_slot_id: Optional[str]
    kind: str
    result: str
    inspector_id: str
    notes: Optional[str]
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    subject_kind: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    payload: dict
    created_at: str


__all__ = [
    "UserRole",
    "ExhibitionStatus",
    "ExhibitionPosture",
    "FloorPlanVersionStatus",
    "FloorPlanCellKind",
    "BoothTier",
    "BoothStatus",
    "SponsorshipLevel",
    "ApplicationStatus",
    "AllocationStatus",
    "DockSlotWindowKind",
    "DockSlotStatus",
    "SafetyInspectionKind",
    "SafetyInspectionResult",
    "WorkOrderServiceCode",
    "WorkOrderStatus",
    "TicketKind",
    "TicketChannel",
    "TicketStatus",
    "EntitlementCode",
    "SponsorTier",
    "EntitlementStatus",
    "AuditSubjectKind",
    "Exhibition",
    "Hall",
    "Booth",
    "ExhibitorApplication",
    "BoothAllocation",
    "DockSlot",
    "WorkOrder",
    "Ticket",
    "SponsorEntitlement",
    "FloorPlanVersion",
    "SafetyInspection",
    "AuditLogEntry",
]
