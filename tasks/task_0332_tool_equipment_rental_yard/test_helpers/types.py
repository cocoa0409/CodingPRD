"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's common-resource-properties rules:
- RateCard, RentalCatalogItem, EquipmentUnit, ContractorAccount, DeliveryTruck,
  Reservation, RentalAgreement, ReturnInspection, MaintenanceTicket carry the full
  id/created_at/updated_at/version set.
- DamageCharge, AccountLedgerEntry, YardClock are append-only/singleton records that
  carry ONLY id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────

class EquipmentAvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_RENT = "ON_RENT"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReservationState(str, Enum):
    CONFIRMED = "CONFIRMED"
    DISPATCHED_DELIVERY = "DISPATCHED_DELIVERY"
    PICKED_UP = "PICKED_UP"
    ON_RENT = "ON_RENT"
    CANCELLED = "CANCELLED"
    FULFILLED = "FULFILLED"


class AgreementState(str, Enum):
    ON_RENT = "ON_RENT"
    RETURNED_PENDING_INSPECTION = "RETURNED_PENDING_INSPECTION"
    CLOSED = "CLOSED"
    CLOSED_WITH_DAMAGE = "CLOSED_WITH_DAMAGE"


class TicketState(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class FulfillmentMethod(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class CatalogCategory(str, Enum):
    HAND_TOOL = "HAND_TOOL"
    POWER_TOOL = "POWER_TOOL"
    HEAVY_EQUIPMENT = "HEAVY_EQUIPMENT"


class Cleanliness(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"


class MaintenanceReason(str, Enum):
    SCHEDULED_SERVICE = "SCHEDULED_SERVICE"
    DAMAGE_REPAIR = "DAMAGE_REPAIR"
    INSPECTION = "INSPECTION"


class LedgerEntryType(str, Enum):
    RENTAL_CHARGE = "RENTAL_CHARGE"
    FUEL_CHARGE = "FUEL_CHARGE"
    CLEANING_CHARGE = "CLEANING_CHARGE"
    LATE_FEE = "LATE_FEE"
    DAMAGE_CHARGE = "DAMAGE_CHARGE"
    DEPOSIT_HOLD = "DEPOSIT_HOLD"
    DEPOSIT_REFUND = "DEPOSIT_REFUND"
    PAYMENT = "PAYMENT"


class UserRole(str, Enum):
    YARD_MANAGER = "YardManager"
    RENTAL_AGENT = "RentalAgent"
    CONTRACTOR = "Contractor"
    INSPECTOR = "Inspector"


# ─── Entities carrying the full common-field set ──────────────────

class RateCard(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    daily_rate_cents: int
    weekly_rate_cents: int
    four_week_rate_cents: int
    deposit_cents: int
    damage_waiver_daily_cents: int
    fuel_refill_cents_per_liter: int
    cleaning_fee_cents: int
    late_fee_multiplier: float
    active: bool


class RentalCatalogItem(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    rate_card_id: str
    sku: str
    name: str
    category: str
    requires_delivery: bool
    fuel_capacity_liters: int
    unit_count: int
    available_unit_count: int


class EquipmentUnit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    catalog_item_id: str
    asset_tag: str
    availability_state: str
    fuel_level_liters: int
    lifetime_rental_days: int
    service_due_at_days: int


class ContractorAccount(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    company_name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    account_status: str
    open_reservation_count: int


class DeliveryTruck(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    buffer_minutes: int


class Reservation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    contractor_account_id: str
    equipment_unit_id: str
    catalog_item_id: str
    fulfillment_method: str
    rental_start_date: str
    rental_end_date: str
    damage_waiver_opted: bool
    reservation_state: str
    estimated_rental_cents: int
    estimated_total_cents: int
    delivery_fee_cents: int
    delivery_truck_id: Optional[str]
    delivery_window_start: Optional[str]
    delivery_window_end: Optional[str]


class RentalAgreement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    reservation_id: str
    equipment_unit_id: str
    contractor_account_id: str
    agreement_state: str
    actual_start_date: str
    scheduled_end_date: str
    actual_return_date: Optional[str]
    deposit_held_cents: int
    final_rental_cents: int
    late_fee_cents: int
    final_total_cents: int


class ReturnInspection(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    rental_agreement_id: str
    return_fuel_level_liters: int
    cleanliness: str
    damage_assessed_cents: int
    fuel_refill_cents: int
    net_damage_cents: int


class MaintenanceTicket(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    equipment_unit_id: str
    reason: str
    ticket_state: str
    opened_by_agreement_id: Optional[str]


# ─── Append-only / singleton entities (id + created_at only) ──────

class DamageCharge(TypedDict):
    id: str
    created_at: str
    rental_agreement_id: str
    return_inspection_id: str
    gross_cents: int
    waiver_applied: bool
    net_cents: int


class AccountLedgerEntry(TypedDict):
    id: str
    created_at: str
    contractor_account_id: str
    rental_agreement_id: Optional[str]
    entry_type: str
    amount_cents: int


class YardClock(TypedDict):
    id: str
    created_at: str
    current_utc: str
