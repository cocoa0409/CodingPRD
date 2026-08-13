"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every resource carries id, created_at, updated_at and version —
except ComplianceLetter, an immutable artifact carrying only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class ArtworkStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    OBSOLETE = "OBSOLETE"


class JobStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    ON_PRESS = "ON_PRESS"
    PRINTED = "PRINTED"
    REWOUND = "REWOUND"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class MeasurementVerdict(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class RollStatus(str, Enum):
    WOUND = "WOUND"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DieStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LetterType(str, Enum):
    FOOD_CONTACT = "FOOD_CONTACT"


class UserRole(str, Enum):
    ESTIMATOR = "Estimator"
    PREPRESS_OPERATOR = "PrepressOperator"
    PRESS_OPERATOR = "PressOperator"
    QUALITY_MANAGER = "QualityManager"


# --- Entities (PRD §2.4 common fields: id, created_at, updated_at, version) ---


class Customer(TypedDict):
    id: str
    account_name: str
    credit_hold: bool
    preferred_currency: str
    created_at: str
    updated_at: str
    version: int


class ArtworkVersion(TypedDict):
    id: str
    customer_id: str
    artwork_code: str
    revision_no: int
    color_count: int
    plate_set_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Substrate(TypedDict):
    id: str
    substrate_code: str
    width_mm: int
    cost_per_msq_cents: int
    food_contact_certified: bool
    created_at: str
    updated_at: str
    version: int


class InkRecipe(TypedDict):
    id: str
    recipe_code: str
    food_contact_compliant: bool
    cost_per_lb_cents: int
    created_at: str
    updated_at: str
    version: int


class Die(TypedDict):
    id: str
    die_code: str
    shape_description: str
    cavities_across: int
    status: str
    new_die_charge_cents: int
    charge_collected: bool
    created_at: str
    updated_at: str
    version: int


class Press(TypedDict):
    id: str
    press_code: str
    station_count: int
    setup_waste_ft: int
    run_waste_pct_numerator: int
    created_at: str
    updated_at: str
    version: int


class LabelJob(TypedDict):
    id: str
    customer_id: str
    artwork_version_id: str
    substrate_id: str
    ink_recipe_id: str
    die_id: str
    press_id: str
    quantity_ordered: int
    repeat_length_mm: int
    requires_food_contact_letter: bool
    rewind_max_rolls: int
    max_splices_per_roll: int
    material_ft: Optional[int]
    quoted_price_cents: int
    invoiced_price_cents: Optional[int]
    die_charge_applied_cents: int
    status: str
    good_quantity_produced: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ColorMeasurement(TypedDict):
    id: str
    job_id: str
    station_no: int
    delta_e: float
    verdict: str
    created_at: str
    updated_at: str
    version: int


class RewindRoll(TypedDict):
    id: str
    job_id: str
    roll_seq: int
    label_count: int
    splice_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ComplianceLetter is append-only (PRD §2.4): ONLY id + created_at as common
# fields — no updated_at, no version.
class ComplianceLetter(TypedDict):
    id: str
    job_id: str
    letter_type: str
    issued_at: str
    body: str
    created_at: str
