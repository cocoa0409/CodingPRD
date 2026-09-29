"""Domain types for the Fuel Tax and Registration Apportionment API.

Status enums, role enum and entity TypedDicts. Field names are exactly the
names the PRD uses; nothing here is abbreviated or renamed.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    CARRIER_ADMIN = "CarrierAdmin"
    MILEAGE_ANALYST = "MileageAnalyst"
    TAX_PREPARER = "TaxPreparer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------

class IftaLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class IrpAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VehicleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"
    TRANSFERRED = "TRANSFERRED"


class VehicleCredentialStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    DISTRIBUTED = "DISTRIBUTED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TripStatus(str, Enum):
    CAPTURED = "CAPTURED"
    GAP_FLAGGED = "GAP_FLAGGED"
    RECONSTRUCTED = "RECONSTRUCTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class MileageSource(str, Enum):
    TELEMATICS = "TELEMATICS"
    MANUAL_RECONSTRUCTION = "MANUAL_RECONSTRUCTION"


class LegStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class PurchaseStatus(str, Enum):
    RECORDED = "RECORDED"
    ACCEPTED = "ACCEPTED"
    DISALLOWED = "DISALLOWED"


class DisallowReasonCode(str, Enum):
    MISSING_RECEIPT = "MISSING_RECEIPT"
    BULK_UNTAXED = "BULK_UNTAXED"
    DUPLICATE = "DUPLICATE"
    AUDIT_ADJUSTMENT = "AUDIT_ADJUSTMENT"


class ReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    FILED = "FILED"
    AUDIT_ADJUSTED = "AUDIT_ADJUSTED"


class SettlementBasis(str, Enum):
    PREPARER_BASIS = "PREPARER_BASIS"
    AUDIT_BASIS = "AUDIT_BASIS"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    INVOICED = "INVOICED"
    ISSUED = "ISSUED"


class DistanceBasis(str, Enum):
    ACTUAL_DISTANCE_BASIS = "ACTUAL_DISTANCE_BASIS"
    ESTIMATED_DISTANCE_BASIS = "ESTIMATED_DISTANCE_BASIS"


class ChangeType(str, Enum):
    ADDITION = "ADDITION"
    DELETION = "DELETION"
    TRANSFER = "TRANSFER"


class ChangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class ReversalReasonCode(str, Enum):
    CLERICAL_ERROR = "CLERICAL_ERROR"
    VEHICLE_NOT_DELIVERED = "VEHICLE_NOT_DELIVERED"
    JURISDICTION_REJECTION = "JURISDICTION_REJECTION"


class CredentialType(str, Enum):
    DECAL_SET = "DECAL_SET"
    CAB_CARD = "CAB_CARD"
    IFTA_LICENSE_COPY = "IFTA_LICENSE_COPY"


class CredentialStatus(str, Enum):
    ISSUED = "ISSUED"
    DISTRIBUTED = "DISTRIBUTED"
    VOIDED = "VOIDED"
    REPLACED = "REPLACED"


class VoidedReasonCode(str, Enum):
    FLEET_DELETION = "FLEET_DELETION"
    TRANSFER_REPLACEMENT = "TRANSFER_REPLACEMENT"
    LICENSE_SUSPENSION = "LICENSE_SUSPENSION"


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    RETENTION_REVIEWED = "RETENTION_REVIEWED"


# --------------------------------------------------------------------------
# Entities carrying the full common property set
# (id, created_at, updated_at, version)
# --------------------------------------------------------------------------

class Carrier(TypedDict):
    id: str
    legal_name: str
    usdot_number: str
    base_jurisdiction_code: str
    bond_ceiling_amount: float
    ifta_license_status: str
    irp_account_status: str
    tax_paid_gallons_ytd: float
    unsubstantiated_mileage_ratio: float
    audit_flag: bool
    latest_prepared_fleet_mpg: Optional[float]
    suspension_count: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    carrier_id: str
    unit_number: str
    vin: str
    weight_group_code: str
    factory_price_amount: float
    registration_year: int
    vehicle_status: str
    credential_status: str
    replaced_vehicle_id: Optional[str]
    activated_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    carrier_id: str
    full_name: str
    cdl_number: str
    driver_status: str
    created_at: str
    updated_at: str
    version: int


class TripRecord(TypedDict):
    id: str
    carrier_id: str
    vehicle_id: str
    trip_start_utc: str
    trip_end_utc: str
    start_odometer: float
    end_odometer: float
    odometer_delta_miles: float
    gap_miles_from_previous: float
    mileage_source: str
    trip_status: str
    reconstructed_by_user_id: Optional[str]
    supporting_document_reference: Optional[str]
    accepted_leg_miles_total: float
    created_at: str
    updated_at: str
    version: int


class FuelPurchase(TypedDict):
    id: str
    carrier_id: str
    vehicle_id: str
    jurisdiction_code: str
    purchase_date: str
    gallons: float
    tax_paid_flag: bool
    receipt_reference: Optional[str]
    purchase_status: str
    disallow_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FuelTaxReturn(TypedDict):
    id: str
    carrier_id: str
    filing_year: int
    filing_quarter: int
    settlement_basis: str
    return_status: str
    prepared_by_user_id: Optional[str]
    filed_by_user_id: Optional[str]
    total_fleet_miles: float
    total_tax_paid_gallons: float
    fleet_mpg: Optional[float]
    reconstructed_mileage_ratio: float
    total_net_tax_due: float
    reconstruction_penalty_amount: float
    total_amount_due: float
    audit_assessment_delta: float
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistrationApplication(TypedDict):
    id: str
    carrier_id: str
    registration_year: int
    weight_group_code: str
    distance_basis: str
    application_status: str
    prepared_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    apportioned_vehicle_count: int
    fleet_total_distance_miles: float
    base_fee_total: float
    total_apportioned_fee: float
    apportion_frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FleetChangeRequest(TypedDict):
    id: str
    registration_application_id: str
    vehicle_id: str
    replaced_vehicle_id: Optional[str]
    change_type: str
    effective_date: str
    prorate_months: int
    fee_delta: float
    change_status: str
    requested_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    reversal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    vehicle_id: str
    registration_application_id: str
    distributed_to_driver_id: Optional[str]
    credential_type: str
    registration_year: int
    valid_from_date: str
    valid_to_date: str
    credential_status: str
    distributed_at: Optional[str]
    voided_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditSelection(TypedDict):
    id: str
    carrier_id: str
    selection_year: int
    selection_quarter: int
    late_filing_count: int
    retention_deficiency_count: int
    risk_score: int
    post_review_risk_score: Optional[int]
    expected_records_count: Optional[int]
    records_missing_count: Optional[int]
    retention_deficiency_ratio: Optional[float]
    selection_status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# The five lighter entities: only id + created_at.
# Neither updated_at nor version exists on them, and neither field appears
# in their serialised representation.
# --------------------------------------------------------------------------

class Jurisdiction(TypedDict):
    id: str
    jurisdiction_code: str
    name: str
    fuel_tax_rate_per_gallon: float
    surcharge_rate_per_gallon: float
    is_surcharge_jurisdiction: bool
    created_at: str


class WeightGroupFee(TypedDict):
    id: str
    jurisdiction_code: str
    weight_group_code: str
    declared_weight_lbs: int
    annual_fee_amount: float
    created_at: str


class JurisdictionMileageLeg(TypedDict):
    id: str
    trip_record_id: str
    jurisdiction_code: str
    leg_miles: float
    leg_sequence: int
    leg_status: str
    created_at: str


class ReturnJurisdictionLine(TypedDict):
    id: str
    fuel_tax_return_id: str
    jurisdiction_code: str
    taxable_miles: float
    taxable_gallons: float
    tax_paid_gallons: float
    net_taxable_gallons: float
    base_tax_amount: float
    surcharge_amount: float
    net_tax_amount: float
    line_status: str
    created_at: str


class DistanceScheduleLine(TypedDict):
    id: str
    registration_application_id: str
    jurisdiction_code: str
    reported_distance_miles: float
    effective_distance_miles: float
    apportion_percent: float
    jurisdiction_fee_amount: float
    line_status: str
    created_at: str


LIGHT_ENTITY_FORBIDDEN_FIELDS: List[str] = ["updated_at", "version"]
