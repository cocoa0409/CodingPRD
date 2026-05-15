"""Domain types for the Festival Program Schedule API.

Carries the status enums for every stateful entity, the role enum, the
fixed four-target outbound sync envelope target enum, the six-value
audit event-category enum, and TypedDicts for every entity declared in
the PRD's §2.4 common-resource-properties and the §3 workflow prose.

Entities whose PRD §2.4 narrative names them as append-only event-log
rows — RiderRequirement, FulfilmentLog, AuditEntry — carry only `id`
and `created_at` and the entity-specific payload fields, never
`updated_at` and never `version`.  Every other mutable entity carries
the full four-field common-resource header.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict, Any


# ---------------------------------------------------------------------------
# Role enum — the eight role names the PRD §2.1 declares plus the synthetic
# 'Any' catch-all label used in the endpoint table for read-only opens.
# 'Any' is not a value any real request puts in X-User-Role.
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    FESTIVAL_PRODUCER = "FestivalProducer"
    ARTIST_LIAISON = "ArtistLiaison"
    STAGE_MANAGER = "StageManager"
    TICKETING_ADMIN = "TicketingAdmin"
    SPONSORSHIP_ADMIN = "SponsorshipAdmin"
    AUDIT_VIEWER = "AuditViewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Entity status enums.  Names are the literal enum strings from the PRD §3
# transition narratives.
# ---------------------------------------------------------------------------

class FestivalStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULING = "SCHEDULING"
    PUBLISHED = "PUBLISHED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProgramVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class StageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ArtistTier(str, Enum):
    HEADLINER = "HEADLINER"
    MAIN = "MAIN"
    OPENER = "OPENER"
    SURPRISE = "SURPRISE"


class ProgramItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    ANNOUNCED = "ANNOUNCED"
    ON_STAGE = "ON_STAGE"
    PERFORMED = "PERFORMED"
    CANCELLED = "CANCELLED"


class SoundCheckStatusAxis(str, Enum):
    """The independent parallel axis on a ProgramItem, distinct from the
    lifecycle axis above.  Driven externally by the SoundCheckSlot machine
    and by the explicit waive endpoint."""
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class AnnouncementSyncState(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    ACKED = "ACKED"
    FAILED = "FAILED"


class RiderCategory(str, Enum):
    TECHNICAL = "TECHNICAL"
    HOSPITALITY = "HOSPITALITY"
    SECURITY = "SECURITY"
    CATERING = "CATERING"
    ACCESSIBILITY = "ACCESSIBILITY"


class SoundEngineerTeamStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    WITHDRAWN = "WITHDRAWN"


class SoundCheckSlotStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RehearsalType(str, Enum):
    STAGE = "STAGE"
    ROOM = "ROOM"


class RehearsalStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class TicketClass(str, Enum):
    SINGLE_DAY = "SINGLE_DAY"
    FULL_FESTIVAL = "FULL_FESTIVAL"
    VIP = "VIP"


class TicketTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class SponsorTierCode(str, Enum):
    TITLE = "TITLE"
    GOLD = "GOLD"
    SILVER = "SILVER"


class ExposureKind(str, Enum):
    """The four-element catalog-kind enum.  The literals are lower-case
    strings, matching the PRD §2.8 catalog-dictionary key set."""
    STAGE_NAME = "stage_name"
    SCREEN_TIME = "screen_time"
    ARTIST_MENTION = "artist_mention"
    BRANDED_ZONE = "branded_zone"


class ExposureAllocationStatus(str, Enum):
    PLANNED = "PLANNED"
    DELIVERED = "DELIVERED"
    REPORTED = "REPORTED"
    VOIDED = "VOIDED"


class FulfilmentLogEventType(str, Enum):
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"
    REPORTED = "REPORTED"
    PROGRAM_VOIDED = "PROGRAM_VOIDED"


class ScheduleChangeKind(str, Enum):
    ITEM_CANCEL = "ITEM_CANCEL"
    ITEM_RESCHEDULE = "ITEM_RESCHEDULE"
    STAGE_SWAP = "STAGE_SWAP"
    VERSION_PUBLISH = "VERSION_PUBLISH"
    TICKET_NOTIFY = "TICKET_NOTIFY"


class ScheduleChangeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    SYNCED = "SYNCED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"


class SyncEnvelopeTarget(str, Enum):
    """The fixed four-element set of downstream-system target names that
    every ScheduleChange's sync_envelopes array contains, in the canonical
    order ticketing, im, broadcasting, sponsor."""
    TICKETING = "ticketing"
    IM = "im"
    BROADCASTING = "broadcasting"
    SPONSOR = "sponsor"


class SyncEnvelopeStatus(str, Enum):
    """The envelope-status enum is the four-element set {QUEUED,
    ACKNOWLEDGED, FAILED, CANCELLED}.  CANCELLED is reserved exclusively
    for the revert path which flips every still-QUEUED envelope on the
    reverted change."""
    QUEUED = "QUEUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AuditEventCategory(str, Enum):
    """The six-element audit-event-category enum the PRD §2.8 declares."""
    SCHEDULE_CHANGE = "SCHEDULE_CHANGE"
    EXPOSURE = "EXPOSURE"
    SYNC_ACK = "SYNC_ACK"
    CLOCK_TICK = "CLOCK_TICK"
    STATE_TRANSITION = "STATE_TRANSITION"
    OCC_CONFLICT = "OCC_CONFLICT"


# ---------------------------------------------------------------------------
# Entity TypedDicts.  Mutable entities carry the standard four common-resource
# fields id/created_at/updated_at/version.  The three append-only entities
# RiderRequirement, FulfilmentLog, AuditEntry carry only id and created_at
# (plus their entity-specific payload fields and, in the rider's case, the
# single mutable fulfilled_at timestamp flag).
# ---------------------------------------------------------------------------

class Festival(TypedDict, total=False):
    id: str
    name: str
    venue_name: str
    start_time: int
    end_time: int
    festival_day_count: int
    status: str
    current_program_version_id: Optional[str]
    clock_offset_seconds: int
    outstanding_tickets_total: int
    created_at: str
    updated_at: str
    version: int


class ProgramVersion(TypedDict, total=False):
    id: str
    festival_id: str
    version_label: str
    status: str
    program_item_ids: List[str]
    published_at: Optional[str]
    superseded_by_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Stage(TypedDict, total=False):
    id: str
    festival_id: str
    stage_name: str
    zone_capacity: int
    changeover_buffer_seconds: int
    equipment_kits: List[str]
    is_emergency_substitute: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentKit(TypedDict, total=False):
    id: str
    festival_id: str
    kit_code: str
    total_units: int
    description: str
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict, total=False):
    id: str
    stage_name: str
    tier: str
    home_city: str
    external_commitments: List[dict]
    minimum_travel_buffer_hours: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProgramItem(TypedDict, total=False):
    id: str
    festival_id: str
    program_version_id: str
    artist_id: str
    stage_id: str
    genre: str
    start_time: int
    end_time: int
    duration_seconds: int
    equipment_kit_codes: List[str]
    slot_priority_score: float
    status: str
    sound_check_status: str
    announcement_sync_state: str
    created_at: str
    updated_at: str
    version: int


class RiderRequirement(TypedDict, total=False):
    """Append-only.  No updated_at, no version.  The single mutable field
    is the fulfilled_at timestamp flag whose flip from null to a server
    timestamp is itself an audited event but does not bump a version on
    this row."""
    id: str
    program_item_id: str
    category: str
    description: str
    is_blocking: bool
    fulfilled_at: Optional[str]
    created_at: str


class SoundEngineerTeam(TypedDict, total=False):
    id: str
    festival_id: str
    team_name: str
    head_engineer_name: str
    warmup_minutes: int
    status: str
    current_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SoundCheckSlot(TypedDict, total=False):
    id: str
    festival_id: str
    program_item_id: str
    stage_id: str
    sound_engineer_team_id: Optional[str]
    scheduled_window_start: Optional[int]
    scheduled_window_end: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Rehearsal(TypedDict, total=False):
    id: str
    festival_id: str
    artist_id: str
    rehearsal_type: str
    stage_id: Optional[str]
    rehearsal_room_name: Optional[str]
    start_time: int
    end_time: int
    archive_uri: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TicketType(TypedDict, total=False):
    id: str
    festival_id: str
    ticket_class: str
    tied_program_item_ids: List[str]
    zone_name: str
    unit_price_cents: int
    issued_count: int
    refunded_count: int
    provisional_refund_cents_outstanding: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SponsorTier(TypedDict, total=False):
    id: str
    festival_id: str
    tier_code: str
    tier_name: str
    priority_rank: int
    sponsor_external_id: str
    sponsor_display_name: str
    contracted_units: int
    contract_kinds_allowed: List[str]
    projected_fulfilment_pct: float
    actual_fulfilment_pct: Optional[float]
    tier_remaining_quota: int
    created_at: str
    updated_at: str
    version: int


class ExposureAllocation(TypedDict, total=False):
    id: str
    festival_id: str
    sponsor_tier_id: str
    program_item_id: Optional[str]
    kind: str
    requested_units: int
    actual_units: int
    delivered_units: int
    pinned_rate_cents_per_unit: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FulfilmentLog(TypedDict, total=False):
    """Append-only event-log row.  No updated_at, no version, no PATCH."""
    id: str
    exposure_allocation_id: str
    program_item_id: Optional[str]
    event_type: str
    units: int
    note: str
    created_at: str


class SyncEnvelope(TypedDict, total=False):
    """One element of a ScheduleChange.sync_envelopes array."""
    target: str
    status: str
    queued_at: Optional[str]
    acked_at: Optional[str]
    payload_hash: Optional[str]


class ScheduleChange(TypedDict, total=False):
    id: str
    festival_id: str
    change_kind: str
    target_program_item_id: Optional[str]
    payload: dict
    status: str
    applied_at: Optional[str]
    sync_envelopes: List[SyncEnvelope]
    provisional_refund_cents_total: int
    final_refund_cents_total: Optional[int]
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEntry(TypedDict, total=False):
    """Append-only and immutable.  No updated_at, no version, no PATCH."""
    id: str
    festival_id: str
    actor_user_id: str
    actor_role: str
    event_category: str
    subject_entity_type: str
    subject_entity_id: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload_summary: str
    created_at: str


# ---------------------------------------------------------------------------
# Convenience: the literal four-element canonical target list, in the order
# the PRD §2.8 declares the elements must appear in the envelope array.
# ---------------------------------------------------------------------------

CANONICAL_SYNC_TARGETS: List[str] = ["ticketing", "im", "broadcasting", "sponsor"]


__all__ = [
    "UserRole",
    "FestivalStatus", "ProgramVersionStatus", "StageStatus", "ArtistTier",
    "ProgramItemStatus", "SoundCheckStatusAxis", "AnnouncementSyncState",
    "RiderCategory", "SoundEngineerTeamStatus", "SoundCheckSlotStatus",
    "RehearsalType", "RehearsalStatus", "TicketClass", "TicketTypeStatus",
    "SponsorTierCode", "ExposureKind", "ExposureAllocationStatus",
    "FulfilmentLogEventType", "ScheduleChangeKind", "ScheduleChangeStatus",
    "SyncEnvelopeTarget", "SyncEnvelopeStatus", "AuditEventCategory",
    "Festival", "ProgramVersion", "Stage", "EquipmentKit", "Artist",
    "ProgramItem", "RiderRequirement", "SoundEngineerTeam", "SoundCheckSlot",
    "Rehearsal", "TicketType", "SponsorTier", "ExposureAllocation",
    "FulfilmentLog", "SyncEnvelope", "ScheduleChange", "AuditEntry",
    "CANONICAL_SYNC_TARGETS",
]
