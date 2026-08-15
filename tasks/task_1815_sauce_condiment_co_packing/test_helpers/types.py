"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    CUSTOMER = "Customer"
    PROCESS_AUTHORITY = "ProcessAuthority"
    QA_REVIEWER = "QAReviewer"


class ProcessCategory(str, Enum):
    ACIDIFIED = "ACIDIFIED"
    LOW_ACID = "LOW_ACID"
    ACID = "ACID"


class AllergenClass(str, Enum):
    NONE = "NONE"
    GLUTEN = "GLUTEN"
    SOY = "SOY"
    NUT = "NUT"
    DAIRY = "DAIRY"


class SourcingMode(str, Enum):
    CUSTOMER_SUPPLIED = "CUSTOMER_SUPPLIED"
    COPACKER_SUPPLIED = "COPACKER_SUPPLIED"


class ComponentType(str, Enum):
    BOTTLE = "BOTTLE"
    CAP = "CAP"
    LABEL = "LABEL"
    CASE = "CASE"


class HoldReasonCategory(str, Enum):
    PH_DEVIATION = "PH_DEVIATION"
    AW_DEVIATION = "AW_DEVIATION"
    FOREIGN_MATERIAL = "FOREIGN_MATERIAL"
    LABEL_MISMATCH = "LABEL_MISMATCH"


class Disposition(str, Enum):
    RELEASE = "RELEASE"
    REWORK = "REWORK"
    DESTROY = "DESTROY"


class DispositionOwner(str, Enum):
    CUSTOMER = "CUSTOMER"
    COPACKER = "COPACKER"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_TRIAL = "IN_TRIAL"
    TRIAL_PASSED = "TRIAL_PASSED"
    APPROVED = "APPROVED"


class TrialStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LetterStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LabelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    REWORK = "REWORK"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    DESTROYED = "DESTROYED"


class HoldStatus(str, Enum):
    OPEN = "OPEN"
    DISPOSITIONED = "DISPOSITIONED"


# --- Entity TypedDicts -------------------------------------------------------
# All eleven resources carry the standard system-managed fields of PRD §2.4:
# id, created_at, updated_at, version.


class CustomerAccount(TypedDict, total=False):
    id: str
    brand_name: str
    contact_email: str
    default_disposition_owner: str
    credit_limit_cents: int
    outstanding_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    customer_id: str
    product_name: str
    sku_code: str
    process_category: str
    allergen_class: str
    min_run_units: int
    unit_rate_cents: int
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IngredientSupply(TypedDict, total=False):
    id: str
    formula_id: str
    ingredient_name: str
    sourcing_mode: str
    quantity_per_unit: float
    unit_cost_cents: Optional[float]
    consigned_units_on_hand: float
    created_at: str
    updated_at: str
    version: int


class PilotCell(TypedDict, total=False):
    id: str
    cell_name: str
    max_batch_units: int
    created_at: str
    updated_at: str
    version: int


class ScaleUpTrial(TypedDict, total=False):
    id: str
    formula_id: str
    pilot_cell_id: str
    batch_size_units: int
    scheduled_start: str
    scheduled_end: str
    yield_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessAuthorityLetter(TypedDict, total=False):
    id: str
    formula_id: str
    formula_revision: int
    authority_name: str
    letter_number: str
    max_ph: float
    max_water_activity: float
    status: str
    created_at: str
    updated_at: str
    version: int


class KettleLine(TypedDict, total=False):
    id: str
    line_name: str
    capacity_units: int
    created_at: str
    updated_at: str
    version: int


class PackagingComponent(TypedDict, total=False):
    id: str
    component_name: str
    component_type: str
    unit_cost_cents: int
    on_hand_units: int
    reserved_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class PackagingRequirement(TypedDict, total=False):
    component_id: str
    quantity_per_unit: float


class ProductionRun(TypedDict, total=False):
    id: str
    formula_id: str
    kettle_line_id: str
    planned_units: int
    scheduled_start: str
    scheduled_end: str
    packaging_requirements: List[Any]
    formula_revision: int
    actual_units_produced: Optional[int]
    measured_ph: Optional[float]
    measured_water_activity: Optional[float]
    changeover_fee_cents: Optional[int]
    estimated_charge_cents: Optional[int]
    final_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityHold(TypedDict, total=False):
    id: str
    production_run_id: str
    reason_category: str
    measured_ph: Optional[float]
    measured_water_activity: Optional[float]
    letter_deviation: Optional[float]
    statutory_margin: Optional[float]
    disposition_owner: str
    created_by_user_id: str
    disposition: Optional[str]
    disposition_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelApproval(TypedDict, total=False):
    id: str
    formula_id: str
    label_version: str
    brand_display_name: str
    net_quantity_statement: str
    allergen_declaration: str
    status: str
    created_at: str
    updated_at: str
    version: int
