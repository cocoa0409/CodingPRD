"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the four common fields (id, created_at,
updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SCREENING_OFFICER = "ScreeningOfficer"
    LAB_TECH = "LabTech"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CATALOG_MANAGER = "CatalogManager"
    RECIPIENT = "Recipient"
    BILLING_CLERK = "BillingClerk"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class DonorStatus(str, Enum):
    APPLICANT = "APPLICANT"
    SCREENING = "SCREENING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DEFERRED = "DEFERRED"
    RETIRED = "RETIRED"


class ScreeningApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"


class SpecimenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    DISCARDED = "DISCARDED"


class HoldStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class RecipientStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RecipientConsentStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class VialReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ShipmentStatus(str, Enum):
    PREPARING = "PREPARING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class StorageAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CLOSED = "CLOSED"


class StorageInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class BillingMode(str, Enum):
    RENEWAL = "RENEWAL"
    LAPSE = "LAPSE"


class SiblingRegistryStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class CollectionAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DewarMaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class RegulatoryReportStatus(str, Enum):
    FILED = "FILED"


class DonorType(str, Enum):
    SPERM = "SPERM"
    OOCYTE = "OOCYTE"


class ReportType(str, Enum):
    ADVERSE_REACTION = "ADVERSE_REACTION"
    FDA_ANNUAL = "FDA_ANNUAL"
    GENETIC_UPDATE = "GENETIC_UPDATE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4)
# ---------------------------------------------------------------------------
class Donor(TypedDict):
    id: str
    display_code: str
    full_name: str
    donor_type: str
    blood_type: str
    fda_eligible: bool
    genetic_panel_clear: bool
    family_limit: int
    reported_family_count: int
    status: str
    is_family_limit_reached: bool
    created_at: str
    updated_at: str
    version: int


class ScreeningApplication(TypedDict):
    id: str
    donor_id: str
    fda_risk_flag: bool
    genetic_carrier_count: int
    partner_screening_required: bool
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    donor_id: str
    collection_date: str
    initial_vial_count: int
    quarantine_release_date: str
    retest_negative: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DonorInventory(TypedDict):
    id: str
    specimen_id: str
    donor_id: str
    dewar_code: str
    total_vials: int
    reserved_vials: int
    shipped_vials: int
    available_vials: int
    committed_available_vials: int
    is_listed: bool
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class Recipient(TypedDict):
    id: str
    family_name: str
    contact_email: str
    consent_on_file: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RecipientConsent(TypedDict):
    id: str
    recipient_id: str
    donor_id: str
    acknowledges_open_id: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class VialReservation(TypedDict):
    id: str
    recipient_id: str
    inventory_id: str
    donor_id: str
    vial_count: int
    expected_inventory_version: int
    hold_expiry: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    reservation_id: str
    recipient_id: str
    clinic_address: str
    ln2_dewar_serial: str
    dispatched_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageAccount(TypedDict):
    id: str
    recipient_id: str
    reservation_id: str
    stored_vials: int
    period_start: str
    paid_through: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageInvoice(TypedDict):
    id: str
    storage_account_id: str
    period_index: int
    billing_mode: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SiblingRegistryEntry(TypedDict):
    id: str
    donor_id: str
    recipient_id: str
    birth_reported_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionAppointment(TypedDict):
    id: str
    donor_id: str
    room_code: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DewarMaintenanceWindow(TypedDict):
    id: str
    dewar_code: str
    service_start: str
    service_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict):
    id: str
    donor_id: str
    report_type: str
    as_of: str
    total_families_at_report: int
    total_vials_shipped_at_report: int
    status: str
    created_at: str
    updated_at: str
    version: int
