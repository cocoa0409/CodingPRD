"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class IntakePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LoadStatus(str, Enum):
    REPORTED = "REPORTED"
    WEIGHED = "WEIGHED"
    GRADED = "GRADED"
    STORED = "STORED"
    DEPLETED = "DEPLETED"
    REJECTED = "REJECTED"


class AflatoxinStatus(str, Enum):
    UNTESTED = "UNTESTED"
    SAMPLED = "SAMPLED"
    PASSED = "PASSED"
    SEGREGATED = "SEGREGATED"
    REJECTED = "REJECTED"


class DryingStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    BOOKED = "BOOKED"
    DRIED = "DRIED"


class GradeSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class CertificateStatus(str, Enum):
    SAMPLED = "SAMPLED"
    RESULT_RECORDED = "RESULT_RECORDED"
    CONFIRMED = "CONFIRMED"


class Determination(str, Enum):
    PASS = "PASS"
    SEGREGATE = "SEGREGATE"
    REJECT = "REJECT"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class Compartment(str, Enum):
    GENERAL = "GENERAL"
    SEGREGATED = "SEGREGATED"


class ReceiptStatus(str, Enum):
    OPEN = "OPEN"
    PLEDGED = "PLEDGED"
    CLOSED = "CLOSED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPAID = "REPAID"
    FORECLOSED = "FORECLOSED"


class MarginStatus(str, Enum):
    MARGIN_OK = "MARGIN_OK"
    MARGIN_CALL = "MARGIN_CALL"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class DeliveryCallStatus(str, Enum):
    ISSUED = "ISSUED"
    ALLOCATED = "ALLOCATED"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"
    DEFAULTED = "DEFAULTED"


class SettlementStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class HullLotStatus(str, Enum):
    GENERATED = "GENERATED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    DISPOSED = "DISPOSED"


class UserRole(str, Enum):
    BUYING_POINT_ADMIN = "BuyingPointAdmin"
    GROWER = "Grower"
    GRADING_INSPECTOR = "GradingInspector"
    LAB_TECHNICIAN = "LabTechnician"
    SETTLEMENT_CLERK = "SettlementClerk"
    SHELLER_REP = "ShellerRep"


class BuyingPoint(TypedDict):
    id: str
    name: str
    crop_year: int
    drying_rate_per_cycle_cents: int
    quota_price_cents_per_ton: int
    additional_price_cents_per_ton: int
    loan_rate_quota_cents_per_ton: int
    loan_rate_additional_cents_per_ton: int
    intake_posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Grower(TypedDict):
    id: str
    name: str
    farm_number: str
    status: str
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class DiscountSchedule(TypedDict):
    id: str
    schedule_code: str
    effective_from: str
    effective_to: str
    moisture_tiers: List[dict]
    foreign_material_tiers: List[dict]
    damage_rate_cents_per_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FarmerStockLoad(TypedDict):
    id: str
    grower_id: str
    crop_year: int
    gross_tons: Optional[float]
    weighed_at: Optional[str]
    status: str
    aflatoxin_status: str
    drying_status: str
    payable_tons: Optional[float]
    provisional_net_estimate_cents: Optional[int]
    settlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradeSheet(TypedDict):
    id: str
    load_id: str
    inspector_ref: str
    schedule_id: Optional[str]
    moisture_pct: float
    foreign_material_pct: float
    damage_pct: float
    lsk_pct: float
    payable_tons: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class AflatoxinCertificate(TypedDict):
    id: str
    load_id: str
    sample_ref: str
    lab_tech_ref: str
    result_ppb: Optional[float]
    result_recorded_by: Optional[str]
    confirmed_by: Optional[str]
    determination: Optional[str]
    retest_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dryer(TypedDict):
    id: str
    buying_point_id: str
    name: str
    cycle_capacity_tons: int
    cycle_hours: int
    created_at: str
    updated_at: str
    version: int


class DryerBooking(TypedDict):
    id: str
    dryer_id: str
    load_id: str
    tons: float
    starts_at: str
    ends_at: str
    moisture_at_booking: float
    actual_moisture_after: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict):
    id: str
    buying_point_id: str
    name: str
    compartment: str
    capacity_tons: int
    stored_tons: float
    reserved_tons: float
    free_tons: float
    created_at: str
    updated_at: str
    version: int


class StorageReceipt(TypedDict):
    id: str
    warehouse_id: str
    load_id: str
    segregated: bool
    tons_initial: float
    tons_remaining: float
    shelled_tons: float
    stored_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanPledge(TypedDict):
    id: str
    grower_id: str
    storage_receipt_id: str
    pledged_tons: float
    quota_part_tons: float
    additional_part_tons: float
    principal_cents: int
    outstanding_principal_cents: int
    accrued_interest_cents: int
    pledged_at: str
    maturity_date: str
    collateral_value_standard_cents: int
    collateral_value_conservative_cents: int
    margin_status: str
    foreclosure_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShellerContract(TypedDict):
    id: str
    buying_point_id: str
    sheller_ref: str
    total_units_tons: float
    fulfilled_units_tons: float
    remaining_units_tons: float
    price_per_ton_cents: int
    accepts_segregated: bool
    window_start: str
    window_end: str
    default_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryCall(TypedDict):
    id: str
    contract_id: str
    requested_tons: float
    dock_window_start: str
    dock_window_end: str
    allocated_tons: float
    delivered_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only junction: carries ONLY id + created_at (no updated_at, no version)
class AllocationLine(TypedDict):
    id: str
    delivery_call_id: str
    storage_receipt_id: str
    allocated_tons: float
    shipped_tons: float
    shelled_tons: float
    created_at: str


class Settlement(TypedDict):
    id: str
    grower_id: str
    crop_year: int
    supersedes_settlement_id: Optional[str]
    included_load_ids: List[str]
    offset_pledge_ids: List[str]
    quota_tons_applied: float
    additional_tons_applied: float
    gross_value_cents: int
    discount_cents: int
    drying_cents: int
    loan_offset_cents: int
    hull_credit_cents: int
    net_payment_cents: int
    computed_by: str
    approved_by: Optional[str]
    paid_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuotaHistory(TypedDict):
    id: str
    grower_id: str
    crop_year: int
    quota_tons: float
    used_quota_tons: float
    created_at: str
    updated_at: str
    version: int


class HullLot(TypedDict):
    id: str
    delivery_call_id: str
    tons: float
    sale_price_cents_per_ton: Optional[int]
    revenue_cents: Optional[int]
    sold_at: Optional[str]
    disposition_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
