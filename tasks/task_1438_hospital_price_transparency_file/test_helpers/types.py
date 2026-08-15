"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONTRACT_MANAGER = "ContractManager"
    TRANSPARENCY_OFFICER = "TransparencyOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    CONSUMER = "Consumer"


# ---------------------------------------------------------------------------
# Facility
# ---------------------------------------------------------------------------
class PenaltyPolicy(str, Enum):
    SIMPLE = "SIMPLE"
    TIERED = "TIERED"


class AttestationStatus(str, Enum):
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class Facility(TypedDict, total=False):
    id: str
    name: str
    cms_certification_number: str
    bed_count: int
    penalty_policy: str
    min_records_per_cycle: int
    shoppable_min_entries: int
    mandated_min_entries: int
    shoppable_display_enabled: bool
    attestation_status: str
    attestation_year: Optional[int]
    attestation_cycle_id: Optional[str]
    rejected_at: Optional[str]
    plan_due_date: Optional[str]
    penalty_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Payer / PayerContract / PayerNegotiatedRate
# ---------------------------------------------------------------------------
class PayerType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    MEDICAID_MANAGED = "MEDICAID_MANAGED"


class ConfidentialityTier(str, Enum):
    STANDARD = "STANDARD"
    PROPRIETARY = "PROPRIETARY"


class Payer(TypedDict, total=False):
    id: str
    name: str
    payer_type: str
    confidentiality_tier: str
    created_at: str
    updated_at: str
    version: int


class ConfidentialityClause(str, Enum):
    DISCLOSE_ALLOWED = "DISCLOSE_ALLOWED"
    DERIVED_ONLY = "DERIVED_ONLY"
    AGGREGATE_ONLY = "AGGREGATE_ONLY"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEGOTIATING = "RENEGOTIATING"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class PayerContract(TypedDict, total=False):
    id: str
    facility_id: str
    payer_id: str
    confidentiality_clause: str
    annual_volume: int
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateType(str, Enum):
    PERCENT_OF_GROSS = "PERCENT_OF_GROSS"
    FEE_SCHEDULE_FLAT = "FEE_SCHEDULE_FLAT"
    PERCENT_OF_MEDICARE = "PERCENT_OF_MEDICARE"


class RateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INACTIVE = "INACTIVE"


class PayerNegotiatedRate(TypedDict, total=False):
    id: str
    contract_id: str
    service_item_id: str
    rate_type: str
    rate_percent: Optional[float]
    flat_amount_cents: Optional[int]
    negotiated_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# ServiceItem
# ---------------------------------------------------------------------------
class CodeType(str, Enum):
    CPT = "CPT"
    HCPCS = "HCPCS"
    MS_DRG = "MS_DRG"
    REVENUE_CODE = "REVENUE_CODE"


class ServiceClass(str, Enum):
    SHOPPABLE = "SHOPPABLE"
    ANCILLARY = "ANCILLARY"
    SUPPLY = "SUPPLY"
    DRUG = "DRUG"
    FACILITY_FEE = "FACILITY_FEE"


class AncillaryInclusion(str, Enum):
    ALWAYS_BUNDLED = "ALWAYS_BUNDLED"
    CONDITIONALLY_INCLUDED = "CONDITIONALLY_INCLUDED"
    SEPARATELY_PRICED = "SEPARATELY_PRICED"


class ServiceItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ServiceItem(TypedDict, total=False):
    id: str
    facility_id: str
    code: str
    code_type: str
    description: str
    service_class: str
    gross_charge_cents: int
    medicare_base_cents: Optional[int]
    ancillary_inclusion: str
    cms_shoppable_mandated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# StandardChargeRecord
# ---------------------------------------------------------------------------
class RecordStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    FLAGGED = "FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class DerivationMethod(str, Enum):
    EXACT_MIN = "EXACT_MIN"
    MIX_WEIGHTED = "MIX_WEIGHTED"
    NONE = "NONE"


class StandardChargeRecord(TypedDict, total=False):
    id: str
    facility_id: str
    publication_cycle_id: str
    service_item_id: str
    supersedes_id: Optional[str]
    gross_charge_cents: int
    discounted_cash_cents: int
    min_negotiated_cents: Optional[int]
    max_negotiated_cents: Optional[int]
    derived_disclosure_cents: Optional[int]
    derivation_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# ShoppableServiceList
# ---------------------------------------------------------------------------
class ListStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ShoppableEntry(TypedDict, total=False):
    service_item_id: str
    display_name: str
    bundled_ancillary_item_ids: List[str]
    include_conditional_ancillaries: bool
    display_order: int


class PinnedRecord(TypedDict, total=False):
    service_item_id: str
    charge_record_id: str
    record_version: int


class ShoppableServiceList(TypedDict, total=False):
    id: str
    facility_id: str
    title: str
    entries: List[dict]
    entry_count: int
    mandated_entry_count: int
    pinned_records: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# PublicationCycle / MachineReadableFile
# ---------------------------------------------------------------------------
class CycleType(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class CyclePosture(str, Enum):
    COLLECTING = "COLLECTING"
    FREEZABLE = "FREEZABLE"
    AWAITING_FILE = "AWAITING_FILE"
    FILE_UNVALIDATED = "FILE_UNVALIDATED"
    PUBLISHABLE = "PUBLISHABLE"
    FILE_INVALID = "FILE_INVALID"
    CURRENT = "CURRENT"
    ARCHIVED = "ARCHIVED"


class PublicationCycle(TypedDict, total=False):
    id: str
    facility_id: str
    cycle_type: str
    period_start: str
    period_end: str
    schema_version: str
    status: str
    posture: str
    validated_record_count: int
    total_gross_cents: int
    derived_rollup_cents: int
    created_at: str
    updated_at: str
    version: int


class FileFormat(str, Enum):
    JSON = "JSON"
    CSV = "CSV"


class GenerationStatus(str, Enum):
    SEALED = "SEALED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class ValidationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    VALID = "VALID"
    INVALID = "INVALID"


class MachineReadableFile(TypedDict, total=False):
    id: str
    publication_cycle_id: str
    file_format: str
    generation_status: str
    validation_status: str
    record_count: int
    summary_total_discounted_cents: int
    validation_errors: List[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# DiscrepancyReport
# ---------------------------------------------------------------------------
class ReporterType(str, Enum):
    CONSUMER = "CONSUMER"
    PAYER = "PAYER"
    INTERNAL = "INTERNAL"


class DiscrepancyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    CORRECTION_PROPOSED = "CORRECTION_PROPOSED"
    CORRECTION_APPROVED = "CORRECTION_APPROVED"
    CORRECTED = "CORRECTED"


class DiscrepancyReport(TypedDict, total=False):
    id: str
    publication_cycle_id: str
    standard_charge_record_id: str
    reporter_type: str
    description: str
    status: str
    proposed_gross_charge_cents: Optional[int]
    proposed_discounted_cash_cents: Optional[int]
    proposed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    applied_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
