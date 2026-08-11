"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3).

PRD §2.4: all entities carry the full common-field set (id, created_at,
updated_at, version); none are timestamp-only.
"""
from enum import Enum
from typing import Optional, TypedDict


class ProducerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class QualityFlag(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    PROBATION = "PROBATION"


class HaulerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TankerDisposition(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED_FOR_PROCESSING = "RELEASED_FOR_PROCESSING"
    REJECTED = "REJECTED"
    DIVERTED = "DIVERTED"


class AntibioticResult(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class RejectionReason(str, Enum):
    ANTIBIOTIC_POSITIVE = "ANTIBIOTIC_POSITIVE"
    SCC_EXCEEDED = "SCC_EXCEEDED"
    TEMPERATURE_EXCEEDED = "TEMPERATURE_EXCEEDED"
    HAULER_LICENSE_EXPIRED = "HAULER_LICENSE_EXPIRED"


class LabTestType(str, Enum):
    ANTIBIOTIC = "ANTIBIOTIC"
    SCC = "SCC"
    TEMPERATURE_RECHECK = "TEMPERATURE_RECHECK"


class LabTestStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"


class ResultDisposition(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class PricingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PasteurizerRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class CipCycleStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class ValidationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ProductCode(str, Enum):
    WHOLE_MILK = "WHOLE_MILK"
    TWO_PERCENT = "TWO_PERCENT"
    SKIM = "SKIM"
    HEAVY_CREAM = "HEAVY_CREAM"
    BUTTER = "BUTTER"
    CONDENSED_SKIM = "CONDENSED_SKIM"


class ProductBatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    CODED = "CODED"
    SCRAPPED = "SCRAPPED"


class DistributionRouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class GradeAPermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSPENDED = "SUSPENDED"
    REINSTATED = "REINSTATED"
    REVOKED = "REVOKED"


class MarketingOrderPoolStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    FINALIZED = "FINALIZED"


class UserRole(str, Enum):
    PLANT_CONTROLLER = "PlantController"
    QUALITY_ASSURANCE_MANAGER = "QualityAssuranceManager"
    LAB_TECHNICIAN = "LabTechnician"
    PASTEURIZER_OPERATOR = "PasteurizerOperator"
    STATE_INSPECTOR = "StateInspector"


class Producer(TypedDict, total=False):
    id: str
    producer_code: str
    farm_name: str
    base_hauling_rate_cents_per_cwt: int
    quality_flag: str
    rolling_rejection_count_30d: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Hauler(TypedDict, total=False):
    id: str
    hauler_code: str
    company_name: str
    license_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TankerReceipt(TypedDict, total=False):
    id: str
    producer_id: str
    hauler_id: str
    arrived_at: str
    gross_weight_lbs: float
    tare_weight_lbs: float
    net_weight_lbs: float
    temperature_f: float
    antibiotic_result: str
    scc_cells_per_ml: Optional[int]
    rejection_reason: Optional[str]
    disposition: str
    created_at: str
    updated_at: str
    version: int


class LabTest(TypedDict, total=False):
    id: str
    tanker_receipt_id: str
    test_type: str
    result_value: float
    result_disposition: Optional[str]
    completed_at: Optional[str]
    lab_technician_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComponentAssay(TypedDict, total=False):
    id: str
    tanker_receipt_id: str
    butterfat_pct: float
    protein_pct: float
    other_solids_pct: float
    butterfat_lbs: float
    protein_lbs: float
    other_solids_lbs: float
    created_at: str
    updated_at: str
    version: int


class ProducerSettlement(TypedDict, total=False):
    id: str
    producer_id: str
    period_start_date: str
    period_end_date: str
    gross_pool_credit_cents: int
    over_order_premium_cents: int
    hauling_deduction_cents: int
    net_payment_cents: int
    pricing_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PasteurizerRun(TypedDict, total=False):
    id: str
    pasteurizer_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    flow_rate_gph: int
    min_hold_temp_f: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CipCycle(TypedDict, total=False):
    id: str
    pasteurizer_run_id: str
    started_at: str
    completed_at: Optional[str]
    caustic_conductivity_ms: float
    rinse_ph: float
    validation_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductBatch(TypedDict, total=False):
    id: str
    pasteurizer_run_id: str
    product_code: str
    quantity_gallons: int
    shelf_life_days: int
    code_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionRoute(TypedDict, total=False):
    id: str
    route_code: str
    destination_zip: str
    transit_days: int
    min_days_of_code_required: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GradeAPermit(TypedDict, total=False):
    id: str
    permit_number: str
    issued_at: str
    expires_at: str
    inspection_score: Optional[int]
    violation_count_12mo: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketingOrderPool(TypedDict, total=False):
    id: str
    pool_month: str
    announced_class_i_price_cents: int
    butterfat_price_cents_per_lb: int
    protein_price_cents_per_lb: int
    other_solids_price_cents_per_lb: int
    producer_price_differential_cents: Optional[int]
    total_pooled_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int
