"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class ZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class CompliancePosture(str, Enum):
    NORMAL = "NORMAL"
    AUDIT_HOLD = "AUDIT_HOLD"


class AdmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADMITTED = "ADMITTED"
    CANCELLED = "CANCELLED"


class ZoneStatusDesignation(str, Enum):
    PRIVILEGED_FOREIGN = "PRIVILEGED_FOREIGN"
    NON_PRIVILEGED_FOREIGN = "NON_PRIVILEGED_FOREIGN"
    DOMESTIC = "DOMESTIC"
    ZONE_RESTRICTED = "ZONE_RESTRICTED"


class LotStatus(str, Enum):
    IN_ZONE = "IN_ZONE"
    DEPLETED = "DEPLETED"


class ManipulationOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class WithdrawalType(str, Enum):
    CONSUMPTION = "CONSUMPTION"
    EXPORT = "EXPORT"


class WithdrawalStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    DUTY_PAID = "DUTY_PAID"
    EXPORTED = "EXPORTED"
    CANCELLED = "CANCELLED"


class DutyOutcome(str, Enum):
    PENDING = "PENDING"
    COLLECTED = "COLLECTED"
    EXTINGUISHED = "EXTINGUISHED"
    NONE = "NONE"


class WeeklyEntryStatus(str, Enum):
    OPEN = "OPEN"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    FROZEN = "FROZEN"


class ReconciliationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class BadgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class GateDirection(str, Enum):
    IN = "IN"
    OUT = "OUT"


class UserRole(str, Enum):
    ZONE_OPERATOR = "ZoneOperator"
    IMPORTER = "Importer"
    CUSTOMS_OFFICER = "CustomsOfficer"
    GATE_OFFICER = "GateOfficer"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Zone(TypedDict, total=False):
    id: str
    name: str
    zone_code: str
    bond_coverage_cents: int
    status: str
    compliance_posture: str
    deferred_duty_exposure_cents: int
    active_lot_count: int
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict, total=False):
    id: str
    zone_id: str
    importer_ref: str
    description: str
    hts_code: str
    quantity: int
    unit_value_cents: int
    zone_status: str
    admission_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    zone_id: str
    admission_id: Optional[str]
    source_manipulation_id: Optional[str]
    importer_ref: str
    hts_code: str
    zone_status: str
    admitted_quantity: int
    quantity_on_hand: int
    reserved_quantity: int
    cumulative_withdrawn: int
    cumulative_consumed: int
    unit_value_cents: int
    duty_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ManipulationOrder(TypedDict, total=False):
    id: str
    zone_id: str
    importer_ref: str
    source_lot_id: str
    input_quantity: int
    output_hts_code: str
    output_quantity: int
    value_added_cents: int
    output_description: str
    output_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict, total=False):
    id: str
    zone_id: str
    importer_ref: str
    lot_id: str
    weekly_entry_id: Optional[str]
    withdrawal_type: str
    quantity: int
    estimated_duty_cents: int
    assessed_duty_cents: Optional[int]
    withdrawal_date: Optional[str]
    duty_outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WeeklyEntry(TypedDict, total=False):
    id: str
    zone_id: str
    importer_ref: str
    week_start_date: str
    week_end_date: str
    entered_value_cents: int
    duty_total_cents: int
    mpf_uncapped_cents: int
    mpf_cents: int
    per_shipment_mpf_cents: int
    mpf_savings_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualReconciliation(TypedDict, total=False):
    id: str
    zone_id: str
    zone_year: int
    beginning_value_cents: int
    physical_ending_value_cents: int
    book_receipts_value_cents: Optional[int]
    book_withdrawals_value_cents: Optional[int]
    book_ending_value_cents: Optional[int]
    discrepancy_cents: Optional[int]
    discrepancy_pct: Optional[float]
    audit_flagged: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessBadge(TypedDict, total=False):
    id: str
    zone_id: str
    holder_name: str
    employer_ref: Optional[str]
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit log: carries ONLY id + created_at — no updated_at, no version.
class ZoneAccessEvent(TypedDict, total=False):
    id: str
    zone_id: str
    badge_id: str
    direction: str
    occurred_at: str
    created_at: str
