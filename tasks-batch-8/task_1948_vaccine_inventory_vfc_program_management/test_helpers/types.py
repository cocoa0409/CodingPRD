"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    VACCINE_MANAGER = "VaccineManager"
    STATE_PROGRAM_OFFICER = "StateProgramOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class ProviderSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_ORDERING = "SUSPENDED_ORDERING"
    TERMINATED = "TERMINATED"


class UnitKind(str, Enum):
    REFRIGERATOR = "REFRIGERATOR"
    FREEZER = "FREEZER"


class Presentation(str, Enum):
    SINGLE_DOSE_VIAL = "SINGLE_DOSE_VIAL"
    MULTI_DOSE_VIAL = "MULTI_DOSE_VIAL"
    PRE_FILLED_SYRINGE = "PRE_FILLED_SYRINGE"


class StorageRequirement(str, Enum):
    REFRIGERATED_2_8C = "REFRIGERATED_2_8C"
    FROZEN_MINUS_50_MINUS_15C = "FROZEN_MINUS_50_MINUS_15C"
    ULTRA_COLD_MINUS_90_MINUS_60C = "ULTRA_COLD_MINUS_90_MINUS_60C"


class StockType(str, Enum):
    PUBLIC_VFC = "PUBLIC_VFC"
    PRIVATE = "PRIVATE"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    WASTED_CLOSED = "WASTED_CLOSED"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_VIABLE = "RESOLVED_VIABLE"
    RESOLVED_WASTED = "RESOLVED_WASTED"


class InsuranceCategory(str, Enum):
    MEDICAID = "MEDICAID"
    UNINSURED = "UNINSURED"
    UNDERINSURED = "UNDERINSURED"
    AMERICAN_INDIAN_ALASKA_NATIVE = "AMERICAN_INDIAN_ALASKA_NATIVE"
    COMMERCIAL = "COMMERCIAL"


class ScreeningOutcome(str, Enum):
    VFC_ELIGIBLE = "VFC_ELIGIBLE"
    PRIVATE_ONLY = "PRIVATE_ONLY"


class FundingSource(str, Enum):
    PUBLIC_VFC = "PUBLIC_VFC"
    PRIVATE = "PRIVATE"


class RegistryStatus(str, Enum):
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    REJECTED_BY_REGISTRY = "REJECTED_BY_REGISTRY"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    CANCELLED = "CANCELLED"


class BorrowDirection(str, Enum):
    PUBLIC_FROM_PRIVATE = "PUBLIC_FROM_PRIVATE"
    PRIVATE_FROM_PUBLIC = "PRIVATE_FROM_PUBLIC"


class BorrowTicketStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_REPAID = "PARTIALLY_REPAID"
    REPAID = "REPAID"
    VOIDED = "VOIDED"


class ReasonCode(str, Enum):
    STOCK_OUT = "STOCK_OUT"
    SHORT_DATE_AVOIDANCE = "SHORT_DATE_AVOIDANCE"
    EMERGENCY_CLINIC = "EMERGENCY_CLINIC"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts -------------------------------------------------------
# Every resource except TemperatureReading carries id + created_at +
# updated_at + version (PRD §2.4). TemperatureReading is the append-only
# exception: it carries only id + created_at.


class ProviderSite(TypedDict):
    id: str
    site_name: str
    vfc_pin: str
    status: str
    excursion_count_open: int
    accountability_balance_doses: int
    private_lending_balance: int
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict):
    id: str
    provider_site_id: str
    unit_label: str
    unit_kind: str
    min_temp_c: float
    max_temp_c: float
    active_excursion_id: Optional[str]
    is_quarantined: bool
    created_at: str
    updated_at: str
    version: int


class VaccineProduct(TypedDict):
    id: str
    ndc_code: str
    display_name: str
    presentation: str
    doses_per_container: int
    vfc_program_eligible: bool
    storage_requirement: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    provider_site_id: str
    storage_unit_id: str
    vaccine_product_id: str
    lot_number: str
    stock_type: str
    quantity_on_hand: int
    quantity_borrowed_in: int
    expires_on: str
    status: str
    received_via_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict):
    # Append-only event log: NO updated_at, NO version (PRD §2.4).
    id: str
    storage_unit_id: str
    recorded_at: str
    temperature_c: float
    is_out_of_range: bool
    created_at: str


class TemperatureExcursion(TypedDict):
    id: str
    storage_unit_id: str
    opened_at: str
    closed_at: Optional[str]
    peak_temperature_c: float
    duration_minutes: int
    status: str
    doses_written_off: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    provider_site_id: str
    full_name: str
    date_of_birth: str
    insurance_category: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class EligibilityScreening(TypedDict):
    id: str
    patient_id: str
    screening_date: str
    screened_by_user_id: str
    insurance_category_at_visit: str
    vfc_eligible: bool
    outcome: str
    created_at: str
    updated_at: str
    version: int


class DoseAdministration(TypedDict):
    id: str
    provider_site_id: str
    patient_id: str
    eligibility_screening_id: str
    lot_id: str
    administration_date: str
    administered_by_user_id: str
    funding_source: str
    registry_status: str
    borrowed_context_ticket_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VaccineOrder(TypedDict):
    id: str
    provider_site_id: str
    order_number: str
    submitted_by_user_id: str
    status: str
    expected_vfc_doses: int
    approved_vfc_doses: int
    received_vfc_doses: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    vaccine_order_id: str
    vaccine_product_id: str
    requested_doses: int
    approved_doses: int
    received_doses: int
    created_at: str
    updated_at: str
    version: int


class AllocationReceipt(TypedDict):
    id: str
    vaccine_order_id: str
    order_line_id: str
    storage_unit_id: str
    lot_number: str
    expires_on: str
    quantity_doses: int
    lot_id: str
    created_at: str
    updated_at: str
    version: int


class BorrowTicket(TypedDict):
    id: str
    provider_site_id: str
    from_lot_id: str
    to_lot_id: str
    direction: str
    borrowed_quantity: int
    paid_back_quantity: int
    status: str
    opened_by_user_id: str
    reason_code: str
    created_at: str
    updated_at: str
    version: int


class SiteVisitAudit(TypedDict):
    id: str
    provider_site_id: str
    visit_date: str
    conducted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
    # Snapshot fields are populated when findings are issued (PRD §3.9).
    public_doses_received: int
    public_doses_administered: int
    public_doses_wasted: int
    public_doses_transferred_out: int
    accountability_gap: int
    on_hand_public_total: int


class ShortDateTransfer(TypedDict):
    id: str
    provider_site_id: str
    from_lot_id: str
    destination_site_id: str
    destination_storage_unit_id: str
    quantity_doses: int
    reason: str
    status: str
    new_lot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
