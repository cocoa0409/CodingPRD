"""Domain types: entity TypedDicts, status enums, role enum for the 340B Drug
Pricing & Compliance API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    HRSA_AUDITOR = "HrsaAuditor"
    PHARMACY_OPERATOR = "PharmacyOperator"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CoveredEntityStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RECERT_DUE = "RECERT_DUE"
    DENIED = "DENIED"
    TERMINATED = "TERMINATED"


class CompliancePosture(str, Enum):
    GOOD = "GOOD"
    FLAGGED = "FLAGGED"


class EntityType(str, Enum):
    DSH = "DSH"
    CHILDRENS_HOSPITAL = "CHILDRENS_HOSPITAL"
    FREESTANDING_CANCER = "FREESTANDING_CANCER"
    CRITICAL_ACCESS = "CRITICAL_ACCESS"
    RURAL_REFERRAL = "RURAL_REFERRAL"
    FQHC = "FQHC"
    RYAN_WHITE = "RYAN_WHITE"
    STD_CLINIC = "STD_CLINIC"


class MedicaidBillingMode(str, Enum):
    CARVE_IN = "CARVE_IN"
    CARVE_OUT = "CARVE_OUT"


class DispenseStatus(str, Enum):
    DISPENSED = "DISPENSED"
    REVERSED = "REVERSED"
    DISCLOSED = "DISCLOSED"


class ClassificationStatus(str, Enum):
    CLASSIFIED_340B = "CLASSIFIED_340B"
    CLASSIFIED_WAC = "CLASSIFIED_WAC"


class EligibilityReason(str, Enum):
    ELIGIBLE_340B = "ELIGIBLE_340B"
    INELIGIBLE_NO_RELATIONSHIP = "INELIGIBLE_NO_RELATIONSHIP"
    INELIGIBLE_NO_RESPONSIBILITY = "INELIGIBLE_NO_RESPONSIBILITY"
    INELIGIBLE_PRESCRIBER = "INELIGIBLE_PRESCRIBER"
    INELIGIBLE_UNREGISTERED_SITE = "INELIGIBLE_UNREGISTERED_SITE"
    CARVED_OUT_MEDICAID = "CARVED_OUT_MEDICAID"


class PricingVariant(str, Enum):
    STANDARD = "STANDARD"
    PENNY = "PENNY"


class ArrangementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClaimStatus(str, Enum):
    CLEAN = "CLEAN"
    DUPLICATE_RISK = "DUPLICATE_RISK"
    VOIDED = "VOIDED"


class FindingType(str, Enum):
    DIVERSION = "DIVERSION"
    DUPLICATE_DISCOUNT = "DUPLICATE_DISCOUNT"
    GPO_VIOLATION = "GPO_VIOLATION"
    INELIGIBLE_PATIENT = "INELIGIBLE_PATIENT"


class FindingOrigin(str, Enum):
    SELF_DISCLOSURE = "SELF_DISCLOSURE"
    HRSA_AUDIT = "HRSA_AUDIT"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class SourceKind(str, Enum):
    AUDIT_FINDING = "AUDIT_FINDING"
    CEILING_RECONCILIATION = "CEILING_RECONCILIATION"


class RepaymentStatus(str, Enum):
    OWED = "OWED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class PurchaseChannel(str, Enum):
    GPO = "GPO"
    WAC = "WAC"
    B340B = "B340B"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (Prescriber)
# ---------------------------------------------------------------------------
class CoveredEntity(TypedDict):
    id: str
    hrsa_id: str
    legal_name: str
    entity_type: str
    gpo_prohibited: bool
    medicaid_billing_mode: str
    medicaid_provider_number: Optional[str]
    registration_status: str
    recert_period_index: int
    compliance_posture: str
    open_repayment_cents: int
    created_at: str
    updated_at: str
    version: int


class ChildSite(TypedDict):
    id: str
    covered_entity_id: str
    site_name: str
    service_address: str
    registered: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — NO updated_at, NO version
class Prescriber(TypedDict):
    id: str
    covered_entity_id: str
    npi: str
    full_name: str
    relationship_type: str
    created_at: str


class Patient(TypedDict):
    id: str
    covered_entity_id: str
    mrn: str
    has_ce_care_record: bool
    ce_retains_responsibility: bool
    medicaid_ffs_enrolled: bool
    created_at: str
    updated_at: str
    version: int


class DrugProduct(TypedDict):
    id: str
    ndc: str
    drug_name: str
    package_size_units: int
    is_covered_outpatient_drug: bool
    wac_price_per_unit_cents: int
    created_at: str
    updated_at: str
    version: int


class CeilingPriceRecord(TypedDict):
    id: str
    drug_product_id: str
    quarter: str
    amp_per_unit_cents: int
    ura_per_unit_cents: int
    is_published: bool
    ceiling_price_per_unit_cents: int
    pricing_variant: str
    created_at: str
    updated_at: str
    version: int


class ContractPharmacyArrangement(TypedDict):
    id: str
    covered_entity_id: str
    pharmacy_name: str
    ship_to_bill_to_npi: str
    effective_start: str
    effective_end: str
    arrangement_status: str
    created_at: str
    updated_at: str
    version: int


class Accumulator(TypedDict):
    id: str
    covered_entity_id: str
    drug_product_id: str
    accrued_units: int
    replenished_packages_total: int
    last_replenish_dispense_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrescriptionDispense(TypedDict):
    id: str
    covered_entity_id: str
    child_site_id: Optional[str]
    contract_pharmacy_id: Optional[str]
    patient_id: str
    prescriber_id: str
    drug_product_id: str
    quantity_units: int
    quarter: str
    dispense_status: str
    classification_status: str
    eligibility_reason: str
    applied_price_per_unit_cents: int
    line_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MedicaidClaim(TypedDict):
    id: str
    prescription_dispense_id: str
    medicaid_state_code: str
    claim_status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    covered_entity_id: str
    prescription_dispense_id: str
    finding_type: str
    origin: str
    finding_status: str
    assessed_units: int
    created_at: str
    updated_at: str
    version: int


class RepaymentObligation(TypedDict):
    id: str
    covered_entity_id: str
    source_kind: str
    source_ref_id: str
    assessed_cents: int
    paid_cents: int
    remaining_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    covered_entity_id: str
    drug_product_id: str
    accumulator_id: Optional[str]
    channel: str
    packages_ordered: int
    quarter: str
    unit_price_paid_cents: int
    created_at: str
    updated_at: str
    version: int
