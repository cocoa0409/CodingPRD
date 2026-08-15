"""Domain types for the Community Kitchen Meal Program API.

Entity field sets mirror the projections declared in PRD 2.4 and section 3.
BatchAllocation and WasteLog are append-only (PRD 2.4): they carry only `id`
and `created_at`, so their TypedDicts deliberately omit `updated_at` and
`version`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    KITCHEN_MANAGER = "KitchenManager"
    FOOD_SAFETY_OFFICER = "FoodSafetyOfficer"
    VOLUNTEER = "Volunteer"
    GUEST = "Guest"


class SiteStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EquipmentPosture(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    RESTRICTED = "RESTRICTED"
    HALTED = "HALTED"


class MenuDayStatus(str, Enum):
    DRAFT = "DRAFT"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SERVING = "SERVING"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class ForecastVariant(str, Enum):
    TRAILING_AVERAGE = "TRAILING_AVERAGE"
    DOW_WEIGHTED = "DOW_WEIGHTED"


class MenuItemStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    UNAVAILABLE = "UNAVAILABLE"
    SOLD_OUT = "SOLD_OUT"


class SourceType(str, Enum):
    DONATION = "DONATION"
    PURCHASE = "PURCHASE"
    RESCUE = "RESCUE"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class FoodBatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INSPECTING = "INSPECTING"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class CertificationLevel(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    SUPERVISOR = "SUPERVISOR"


class VolunteerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class RoleOnShift(str, Enum):
    PREP = "PREP"
    COOK = "COOK"
    SERVER = "SERVER"
    DRIVER = "DRIVER"
    SUPERVISOR_ON_DUTY = "SUPERVISOR_ON_DUTY"


class VolunteerShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class GuestStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FLAGGED = "FLAGGED"
    INACTIVE = "INACTIVE"


class ServiceModel(str, Enum):
    DINE_IN = "DINE_IN"
    TO_GO = "TO_GO"
    DELIVERY = "DELIVERY"


class MealServiceStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"


class PrepStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PREP = "IN_PREP"
    READY = "READY"


class FulfillmentStatus(str, Enum):
    RESERVED = "RESERVED"
    SERVED = "SERVED"
    DELIVERED = "DELIVERED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class EquipmentClass(str, Enum):
    OVEN = "OVEN"
    STOVETOP = "STOVETOP"
    COLD_HOLDING = "COLD_HOLDING"
    GENERAL = "GENERAL"


class Criticality(str, Enum):
    CRITICAL = "CRITICAL"
    SUPPORT = "SUPPORT"


class EquipmentStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    DOWN_FOR_REPAIR = "DOWN_FOR_REPAIR"
    DECOMMISSIONED = "DECOMMISSIONED"


class WasteReason(str, Enum):
    OVERPRODUCTION = "OVERPRODUCTION"
    SPOILAGE = "SPOILAGE"
    SAFETY_DISCARD = "SAFETY_DISCARD"
    PACKAGING_DAMAGE = "PACKAGING_DAMAGE"


class WasteDisposition(str, Enum):
    DISCARD = "DISCARD"
    COMPOST = "COMPOST"
    RESCUE_REDIRECT = "RESCUE_REDIRECT"


class Allergen(str, Enum):
    GLUTEN = "GLUTEN"
    DAIRY = "DAIRY"
    EGG = "EGG"
    SOY = "SOY"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"
    SESAME = "SESAME"


class DietaryLabel(str, Enum):
    VEGETARIAN = "VEGETARIAN"
    VEGAN = "VEGAN"
    HALAL = "HALAL"
    KOSHER_STYLE = "KOSHER_STYLE"
    LOW_SODIUM = "LOW_SODIUM"
    DIABETIC_FRIENDLY = "DIABETIC_FRIENDLY"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------


class Site(TypedDict, total=False):
    id: str
    name: str
    dine_in_capacity: int
    togo_capacity_per_window: int
    delivery_radius_km: float
    equipment_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuDay(TypedDict, total=False):
    id: str
    site_id: str
    service_date: str
    forecast_servings: Optional[int]
    forecast_variant: str
    committed_servings: int
    served_count: int
    overproduction_ratio: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict, total=False):
    id: str
    menu_day_id: str
    name: str
    planned_servings: int
    allergen_tags: List[str]
    dietary_labels: List[str]
    requires_equipment_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FoodBatch(TypedDict, total=False):
    id: str
    site_id: str
    source_type: str
    item_description: str
    quantity_servings: int
    remaining_servings: int
    received_at: str
    use_by: str
    unit_cost_cents_per_serving: Optional[float]
    inspection_result: str
    allergen_tags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BatchAllocation(TypedDict, total=False):
    """Append-only (PRD 2.4): no updated_at, no version."""

    id: str
    menu_item_id: str
    food_batch_id: str
    servings: int
    allocated_at: str
    created_at: str


class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    certification_level: str
    certification_expires_at: Optional[str]
    hours_balance: float
    strike_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict, total=False):
    id: str
    site_id: str
    volunteer_id: str
    menu_day_id: str
    role_on_shift: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GuestProfile(TypedDict, total=False):
    id: str
    full_name: str
    household_size: int
    allergens: List[str]
    dietary_preferences: List[str]
    delivery_address: Optional[str]
    delivery_distance_km: Optional[float]
    visits_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MealService(TypedDict, total=False):
    id: str
    menu_day_id: str
    service_model: str
    window_start: str
    window_end: str
    capacity: int
    reserved_count: int
    requires_supervisor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MealOrder(TypedDict, total=False):
    id: str
    meal_service_id: str
    guest_id: str
    menu_item_id: str
    quantity: int
    substitution_allowed: bool
    prep_status: str
    fulfillment_status: str
    charge_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    equipment_class: str
    criticality: str
    last_inspected_at: Optional[str]
    next_inspection_due: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteLog(TypedDict, total=False):
    """Append-only (PRD 2.4): no updated_at, no version."""

    id: str
    menu_day_id: str
    food_batch_id: str
    servings_wasted: int
    reason: str
    disposition: str
    logged_at: str
    created_at: str
