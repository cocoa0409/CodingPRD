"""Domain types for the Film Distribution Scheduling API.

Status enums and entity TypedDicts derived from PRD §2 and §3.

Per PRD §2.4 'Common Resource Properties': Distributor, Film, Cinema,
Screen, Showtime, and Ticket carry id + created_at + updated_at + version.
The five append-only entities -- Settlement, ScheduleAdjustment,
AnomalyAlert, ExternalEvent, and AuditLog -- carry only id and created_at;
their TypedDicts therefore omit updated_at and version.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ============================================================================
# Roles (PRD §2.1)
# ============================================================================
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISTRIBUTOR_OPS = "DistributorOps"
    CINEMA_OPS = "CinemaOps"
    TICKETING_PLATFORM = "TicketingPlatform"
    FINANCE_OPS = "FinanceOps"
    AUDITOR = "Auditor"


# ============================================================================
# Status enums (PRD §3)
# ============================================================================
class DistributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FilmStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    SHELVED = "SHELVED"
    DELISTED = "DELISTED"


class FilmFormat(str, Enum):
    TWO_D = "2D"
    THREE_D = "3D"
    IMAX = "IMAX"


class FilmRating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG13"
    R = "R"
    NC17 = "NC17"


class CinemaTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ShowtimeSaleStatus(str, Enum):
    PRESALE = "PRESALE"
    ON_SALE = "ON_SALE"
    CLOSED = "CLOSED"


class ShowtimeLifecycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    LOW_ATTENDANCE = "LOW_ATTENDANCE"
    NEW_FILM_INSERTION = "NEW_FILM_INSERTION"
    INCIDENT = "INCIDENT"


class TicketStatus(str, Enum):
    VALID = "VALID"
    REFUNDED = "REFUNDED"
    EXCHANGED = "EXCHANGED"


class SettlementKind(str, Enum):
    POSTING = "POSTING"
    REVERSAL = "REVERSAL"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class AdjustmentType(str, Enum):
    CANCEL = "CANCEL"
    EXCHANGE_TARGET = "EXCHANGE_TARGET"
    INSERTION = "INSERTION"


class AdjustmentReason(str, Enum):
    LOW_ATTENDANCE = "LOW_ATTENDANCE"
    NEW_FILM_INSERTION = "NEW_FILM_INSERTION"
    INCIDENT = "INCIDENT"


class AnomalyRule(str, Enum):
    ROLLING_WINDOW = "ROLLING_WINDOW"
    CUMULATIVE = "CUMULATIVE"


class ExternalEventKind(str, Enum):
    TICKETING_PLATFORM = "TICKETING_PLATFORM"
    PAYMENT = "PAYMENT"
    CINEMA_MGMT = "CINEMA_MGMT"


class AuditAction(str, Enum):
    FILM_RELEASE = "FILM_RELEASE"
    FILM_SHELVE = "FILM_SHELVE"
    FILM_DELIST = "FILM_DELIST"
    SHOWTIME_CREATE = "SHOWTIME_CREATE"
    SHOWTIME_CANCEL = "SHOWTIME_CANCEL"
    SETTLEMENT_POST = "SETTLEMENT_POST"
    SETTLEMENT_REVERSE = "SETTLEMENT_REVERSE"
    TICKET_REFUND = "TICKET_REFUND"
    TICKET_EXCHANGE = "TICKET_EXCHANGE"
    CLOCK_ADVANCE = "CLOCK_ADVANCE"
    SWEEP_RUN = "SWEEP_RUN"


# ============================================================================
# Entity TypedDicts -- common_fields: true
# ============================================================================
class Distributor(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    default_split_ratio_bps: int
    min_show_count_per_week: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Film(TypedDict, total=False):
    id: str
    title: str
    distributor_id: str
    duration_minutes: int
    rating: str
    format: str
    release_date: str
    region_strategy: dict
    status: str
    shelved_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cinema(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    tier: str
    peak_window_start_minute: int
    peak_window_end_minute: int
    created_at: str
    updated_at: str
    version: int


class Screen(TypedDict, total=False):
    id: str
    cinema_id: str
    label: str
    supported_formats: List[str]
    operating_start_minute: int
    operating_end_minute: int
    cleaning_interval_minutes: int
    trailer_minutes: int
    ad_minutes: int
    seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class Showtime(TypedDict, total=False):
    id: str
    screen_id: str
    cinema_id: str
    film_id: str
    distributor_id: str
    start_minute: int
    business_date: str
    block_minutes: int
    end_minute: int
    ticket_price_cents: int
    presale_opens_at: str
    sale_status: str
    lifecycle_status: str
    tickets_sold_count: int
    tickets_refunded_count: int
    gross_box_office_cents: int
    anomaly_flag: bool
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict, total=False):
    id: str
    showtime_id: str
    buyer_external_id: str
    paid_amount_cents: int
    promo_code: Optional[str]
    status: str
    exchanged_to_showtime_id: Optional[str]
    purchased_at: str
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ============================================================================
# Entity TypedDicts -- common_fields: false (append-only ledgers/archives)
# PRD §2.4: Settlement, ScheduleAdjustment, AnomalyAlert, ExternalEvent,
# and AuditLog carry only id + created_at (no updated_at, no version).
# ============================================================================
class Settlement(TypedDict, total=False):
    id: str
    showtime_id: str
    cycle_label: str
    kind: str
    status: str
    gross_cents: int
    platform_commission_cents: int
    tax_cents: int
    distributor_amount_cents: int
    cinema_amount_cents: int
    parent_settlement_id: Optional[str]
    created_at: str


class ScheduleAdjustment(TypedDict, total=False):
    id: str
    showtime_id: str
    adjustment_type: str
    reason: str
    affected_ticket_ids: List[str]
    notifications_dispatched: int
    archived_at: str
    created_at: str


class AnomalyAlert(TypedDict, total=False):
    id: str
    showtime_id: str
    buyer_external_id: str
    rule: str
    triggering_count: int
    created_at: str


class ExternalEvent(TypedDict, total=False):
    id: str
    kind: str
    payload: dict
    applied: bool
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    target_entity: str
    target_id: str
    payload_snapshot: dict
    created_at: str


__all__ = [
    "UserRole",
    "DistributorStatus",
    "FilmStatus",
    "FilmFormat",
    "FilmRating",
    "CinemaTier",
    "ShowtimeSaleStatus",
    "ShowtimeLifecycleStatus",
    "CancelReason",
    "TicketStatus",
    "SettlementKind",
    "SettlementStatus",
    "AdjustmentType",
    "AdjustmentReason",
    "AnomalyRule",
    "ExternalEventKind",
    "AuditAction",
    "Distributor",
    "Film",
    "Cinema",
    "Screen",
    "Showtime",
    "Ticket",
    "Settlement",
    "ScheduleAdjustment",
    "AnomalyAlert",
    "ExternalEvent",
    "AuditLog",
]
