"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Allergy & Immunotherapy Clinic PRD. All primary entities
carry the full common-field set (id, created_at, updated_at, version) per
PRD section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles (PRD section 2.1) -------------------------------------------------
class UserRole(str, Enum):
    ALLERGIST = "Allergist"
    PHARMACIST = "Pharmacist"
    NURSE = "Nurse"
    BILLER = "Biller"
    FRONT_DESK = "FrontDesk"


# --- Status enums ------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PanelStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class RecommendedTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class TestMethod(str, Enum):
    SKIN = "SKIN"
    BLOOD = "BLOOD"


class VialColor(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    SILVER = "SILVER"


class PlanPhase(str, Enum):
    BUILD_UP = "BUILD_UP"
    MAINTENANCE = "MAINTENANCE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RECALLED = "RECALLED"


class VialStatus(str, Enum):
    IN_USE = "IN_USE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"


class VisitStatus(str, Enum):
    ADMINISTERED = "ADMINISTERED"
    RELEASED = "RELEASED"
    REACTION_LOCAL = "REACTION_LOCAL"
    REACTION_SYSTEMIC = "REACTION_SYSTEMIC"


class ReactionGrade(str, Enum):
    NONE = "NONE"
    LOCAL = "LOCAL"
    SYSTEMIC = "SYSTEMIC"


class CptCode(str, Enum):
    CPT_95115 = "CPT_95115"
    CPT_95117 = "CPT_95117"
    CPT_95165 = "CPT_95165"


class BillingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class BillingStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    RECONCILED = "RECONCILED"


# --- Entity TypedDicts (all carry full common fields per PRD 2.4) ------------
class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    epinephrine_on_file: bool
    prior_systemic_reaction: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DiagnosticPanel(TypedDict):
    id: str
    patient_id: str
    panel_name: str
    control_wheal_mm: float
    screening_composite: float
    clinical_composite: float
    recommended_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllergenTest(TypedDict):
    id: str
    panel_id: str
    allergen_code: str
    method: str
    wheal_mm: Optional[float]
    specific_ige_ku: Optional[float]
    clinically_relevant: bool
    sensitization_index: float
    is_positive: bool
    created_at: str
    updated_at: str
    version: int


class ImmunotherapyPlan(TypedDict):
    id: str
    patient_id: str
    panel_id: str
    starting_vial_color: str
    current_vial_color: str
    current_step_index: int
    phase: str
    last_dose_volume_ml: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SerumLot(TypedDict):
    id: str
    vial_color: str
    lot_number: str
    concentrate_potency_pnu_per_ml: float
    received_at_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SerumVial(TypedDict):
    id: str
    plan_id: str
    lot_id: str
    vial_color: str
    dilution_factor: float
    prepared_volume_ml: float
    remaining_volume_ml: float
    shelf_life_days: int
    beyond_use_date_iso: str
    mixed_at_iso: str
    needs_refill: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ShotVisit(TypedDict):
    id: str
    plan_id: str
    vial_id: str
    scheduled_dose_volume_ml: float
    administered_volume_ml: float
    antigen_units_delivered: float
    injection_count: int
    administered_at_iso: str
    observation_window_min: int
    released_at_iso: Optional[str]
    reaction_grade: Optional[str]
    epinephrine_administered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingEntry(TypedDict):
    id: str
    visit_id: Optional[str]
    vial_id: Optional[str]
    patient_id: str
    cpt_code: str
    billed_dose_units: int
    charge_cents: int
    variant: str
    status: str
    created_at: str
    updated_at: str
    version: int
