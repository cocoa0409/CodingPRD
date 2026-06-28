"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this domain carries the full set of id, created_at, updated_at,
and version (see PRD Section 2.4), so every TypedDict lists all four common fields.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CATALOG_ADMIN = "CatalogAdmin"
    PATIENT = "Patient"
    ORDERING_PHYSICIAN = "OrderingPhysician"
    PHLEBOTOMY_TECH = "PhlebotomyTech"
    LAB_TECH = "LabTech"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class TestOfferingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PanelBundleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class CartStatus(str, Enum):
    OPEN = "OPEN"
    CHECKED_OUT = "CHECKED_OUT"


class FundSource(str, Enum):
    CARD = "CARD"
    HSA_FSA = "HSA_FSA"


class FulfillmentMode(str, Enum):
    PSC = "PSC"
    HOME_KIT = "HOME_KIT"


class SpecimenType(str, Enum):
    BLOOD = "BLOOD"
    URINE = "URINE"
    SALIVA = "SALIVA"


class OrderPaymentStatus(str, Enum):
    AUTH_PENDING = "AUTH_PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    AWAITING_COLLECTION = "AWAITING_COLLECTION"
    IN_PROCESSING = "IN_PROCESSING"
    PARTIALLY_RESULTED = "PARTIALLY_RESULTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTED = "COLLECTED"
    RESULTED = "RESULTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PhysicianOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"


class HomeKitStatus(str, Enum):
    SHIPPED = "SHIPPED"


class SpecimenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    IN_ANALYSIS = "IN_ANALYSIS"
    RESULTED = "RESULTED"
    REJECTED = "REJECTED"


class ResultFlag(str, Enum):
    NORMAL = "NORMAL"
    ABNORMAL = "ABNORMAL"
    CRITICAL = "CRITICAL"


class LabResultStatus(str, Enum):
    PROCESSING = "PROCESSING"
    PENDING_CRITICAL_CALLBACK = "PENDING_CRITICAL_CALLBACK"
    RELEASED = "RELEASED"
    AMENDED = "AMENDED"


class ReferralReason(str, Enum):
    ABNORMAL = "ABNORMAL"
    CRITICAL = "CRITICAL"


class TelehealthReferralStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"


class AnalyzerRunStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class TestOffering(TypedDict):
    id: str
    test_code: str
    display_name: str
    list_price_cents: int
    specimen_type: str
    home_kit_eligible: bool
    requires_fasting: bool
    critical_low: Optional[float]
    critical_high: Optional[float]
    ref_low: Optional[float]
    ref_high: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PanelBundle(TypedDict):
    id: str
    bundle_code: str
    display_name: str
    member_test_codes: List[str]
    bundle_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    state_code: str
    hsa_balance_cents: int
    consent_share_results: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Cart(TypedDict):
    id: str
    patient_id: str
    fund_source: str
    line_count: int
    subtotal_cents: int
    estimated_total_cents: int
    estimated_hsa_applied_cents: int
    estimated_patient_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CartLine(TypedDict):
    id: str
    cart_id: str
    test_offering_id: str
    test_code: str
    unit_list_price_cents: int
    repeat_discount_applied: bool
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    patient_id: str
    cart_id: str
    fulfillment_mode: str
    fund_source: str
    invoiced_total_cents: int
    hsa_applied_cents: int
    patient_due_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    test_offering_id: str
    test_code: str
    unit_list_price_cents: int
    repeat_discount_applied: bool
    requires_physician_order: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PhysicianOrder(TypedDict):
    id: str
    order_line_id: str
    patient_id: str
    reviewing_physician_id: Optional[str]
    clinical_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    order_id: str
    psc_location_code: str
    slot_start: str
    slot_end: str
    fasting_confirmed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class HomeKit(TypedDict):
    id: str
    order_id: str
    shipping_state_code: str
    tracking_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    order_line_id: str
    collected_by_user_id: str
    accession_code: str
    collected_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict):
    id: str
    specimen_id: str
    order_line_id: str
    patient_id: str
    test_code: str
    analyzer_value: float
    provisional_flag: str
    final_flag: Optional[str]
    critical_acknowledged: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TelehealthReferral(TypedDict):
    id: str
    lab_result_id: str
    patient_id: str
    referral_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalyzerRun(TypedDict):
    id: str
    analyzer_code: str
    run_start: str
    run_end: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    order_id: str
    fund_source: str
    authorized_amount_cents: int
    captured_amount_cents: int
    hsa_drawn_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
