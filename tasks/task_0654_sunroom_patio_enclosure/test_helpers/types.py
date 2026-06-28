"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values mirror the PRD contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────

class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    DESIGNED = "DESIGNED"
    QUOTED = "QUOTED"
    PERMITTING = "PERMITTING"
    APPROVED_TO_BUILD = "APPROVED_TO_BUILD"
    IN_MANUFACTURE = "IN_MANUFACTURE"
    INSTALLING = "INSTALLING"
    INSPECTING = "INSPECTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MeasurementStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class QuoteStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class QuoteVariant(str, Enum):
    ESTIMATE = "ESTIMATE"
    FINAL = "FINAL"


class FinancingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class PermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"


class HoaStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    HOA_APPROVED = "HOA_APPROVED"
    HOA_DENIED = "HOA_DENIED"


class EngineeringStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ManufactureStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    CANCELLED = "CANCELLED"


class ProgressStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    INSTALLED = "INSTALLED"


class WeatherStatus(str, Enum):
    CLEAR = "CLEAR"
    WEATHER_HOLD = "WEATHER_HOLD"


class InspectionResult(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED_PUNCHLIST = "FAILED_PUNCHLIST"


class StructureType(str, Enum):
    SCREEN_ROOM = "SCREEN_ROOM"
    THREE_SEASON = "THREE_SEASON"
    FOUR_SEASON = "FOUR_SEASON"


class Material(str, Enum):
    ALUMINUM = "ALUMINUM"
    VINYL = "VINYL"
    THERMAL_BREAK_ALUMINUM = "THERMAL_BREAK_ALUMINUM"


class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    SALES_DESIGNER = "SalesDesigner"
    PERMIT_OFFICER = "PermitOfficer"
    MANUFACTURER = "Manufacturer"
    INSTALL_MANAGER = "InstallManager"
    INSPECTOR = "Inspector"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# Entities with common_fields:true carry id + created_at + updated_at + version.
# Warranty (common_fields:false) carries ONLY id + created_at.

class Homeowner(TypedDict):
    id: str
    email: str
    full_name: str
    hoa_governed: bool
    ground_snow_load_psf: float
    design_wind_speed_mph: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    homeowner_id: str
    address_line: str
    structure_type: str
    material: str
    status: str
    width_in: float
    depth_in: float
    footprint_sqft: float
    accepted_quote_id: Optional[str]
    requires_hoa: bool
    requires_engineering: bool
    created_at: str
    updated_at: str
    version: int


class Measurement(TypedDict):
    id: str
    project_id: str
    width_in: float
    depth_in: float
    wall_height_in: float
    existing_slab: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    revision_no: int
    variant: str
    base_price_cents: int
    addons_cents: int
    tax_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    quote_id: str
    project_id: str
    amount_financed_cents: int
    down_payment_cents: int
    term_months: int
    credit_score: int
    apr_bps: Optional[int]
    monthly_payment_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    project_id: str
    jurisdiction_code: str
    hoa_required: bool
    hoa_status: str
    status: str
    resubmission_count: int
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngineeringReview(TypedDict):
    id: str
    permit_application_id: str
    project_id: str
    required_wind_mph: int
    required_snow_psf: float
    rated_wind_mph: int
    rated_snow_psf: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufactureOrder(TypedDict):
    id: str
    project_id: str
    quote_id: str
    lead_time_days: int
    promised_ready_at: str
    ready_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallCrew(TypedDict):
    id: str
    name: str
    max_wind_mph: int
    certified_four_season: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    project_id: str
    crew_id: str
    scheduled_start: str
    scheduled_end: str
    forecast_wind_mph: int
    progress_status: str
    weather_status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    project_id: str
    install_job_id: str
    attempt_no: int
    result: str
    punchlist_items: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, carries ONLY id + created_at (no updated_at, no version)
class Warranty(TypedDict):
    id: str
    project_id: str
    structure_type: str
    term_years: int
    starts_at: str
    expires_at: str
    created_at: str
