"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HOMEOWNER = "Homeowner"
    SOLAR_INSTALLER = "SolarInstaller"
    UTILITY = "Utility"
    SREC_BROKER = "SrecBroker"
    PLATFORM_ADMIN = "PlatformAdmin"


class ProjectStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSESSED = "ASSESSED"
    DESIGNED = "DESIGNED"
    PERMIT_PENDING = "PERMIT_PENDING"
    PERMIT_APPROVED = "PERMIT_APPROVED"
    INSTALLED = "INSTALLED"
    FAILED_INSPECTION = "FAILED_INSPECTION"
    REMEDIATION = "REMEDIATION"
    PTO_PENDING = "PTO_PENDING"
    OPERATIONAL = "OPERATIONAL"
    CANCELLED = "CANCELLED"


class FinancingModel(str, Enum):
    PPA = "PPA"
    LEASE = "LEASE"
    LOAN = "LOAN"


class FinancingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class Beneficiary(str, Enum):
    HOMEOWNER = "HOMEOWNER"
    FINANCIER = "FINANCIER"


class SrecStatus(str, Enum):
    MINTED = "MINTED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    RETIRED = "RETIRED"


class NetMeterPeriodStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class InterconnectionStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PTO_GRANTED = "PTO_GRANTED"
    REJECTED = "REJECTED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REMEDIATED = "REMEDIATED"


class WarrantyClaimType(str, Enum):
    PRODUCTION_SHORTFALL = "PRODUCTION_SHORTFALL"
    EQUIPMENT_DEFECT = "EQUIPMENT_DEFECT"


# --- Entities (common_fields: true carry id/created_at/updated_at/version) ---

class Homeowner(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    state_code: str
    annual_kwh_usage: int


class SolarInstaller(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    company_name: str
    licensed_states: List[str]


class Project(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    homeowner_id: str
    installer_id: Optional[str]
    status: str
    roof_area_sqft: int
    shading_factor: float
    peak_sun_hours: float
    system_size_kw: float
    estimated_annual_production_kwh: float
    gross_system_cost_cents: int
    itc_credit_cents: int
    financing_plan_id: Optional[str]
    lifetime_srec_count: int


class FinancingPlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    model: str
    status: str
    term_years: int
    ppa_rate_cents_per_kwh: float
    ppa_escalator_pct: float
    lease_monthly_cents: int
    loan_principal_cents: int
    loan_apr: float
    monthly_payment_cents: int
    srec_owner: str
    itc_beneficiary: str


class SREC(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    vintage_year: int
    status: str
    owner_type: str
    srec_sale_id: Optional[str]


class SrecSale(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    broker_id: str
    vintage_year: int
    price_cents_per_srec: int
    srec_count: int
    gross_proceeds_cents: int
    net_proceeds_cents: int


class SrecBroker(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    firm_name: str
    broker_fee_pct: float
    operating_states: List[str]


class NetMeterPeriod(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    period_start: str
    period_end: str
    kwh_produced: int
    kwh_consumed: int
    status: str
    net_kwh: int
    bill_credit_cents: int
    bank_kwh_after: int


# common_fields: false — append-only artifact; ONLY id + created_at
class WarrantyPolicy(TypedDict):
    id: str
    created_at: str
    project_id: str
    coverage_start: str
    production_guarantee_pct: float
    coverage_years: int


class WarrantyClaim(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    claim_type: str
    claimed_window_start: Optional[str]
    claimed_window_end: Optional[str]
    status: str
    measured_production_kwh: int
    shortfall_kwh: int
    payout_cents: int


class InterconnectionApplication(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    utility_id: str
    status: str
    requested_export_kw: float


class Utility(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    feeder_headroom_kw: float
    net_metering_rate_cents_per_kwh: float
    export_credit_ratio: float
