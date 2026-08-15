"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — five roles, exact spellings)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DEALER_ADMIN = "DealerAdmin"
    ENERGY_ENGINEER = "EnergyEngineer"
    SERVICE_TECH = "ServiceTech"
    CONTRACT_MANAGER = "ContractManager"
    FACILITY_MANAGER = "FacilityManager"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class FacilityStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class FacilityPosture(str, Enum):
    NORMAL = "NORMAL"
    OUTAGE_ACTIVE = "OUTAGE_ACTIVE"
    MAINTENANCE_DELINQUENT = "MAINTENANCE_DELINQUENT"


class CompressorStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DOWN = "DOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class DemandProfileStatus(str, Enum):
    COLLECTING = "COLLECTING"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class LeakSurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class LeakTagStatus(str, Enum):
    TAGGED = "TAGGED"
    QUOTED = "QUOTED"
    REPAIR_AUTHORIZED = "REPAIR_AUTHORIZED"
    REPAIRED = "REPAIRED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    WONT_FIX = "WONT_FIX"


class LeakSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MaintenanceComponent(str, Enum):
    DRYER = "DRYER"
    FILTER = "FILTER"


class MaintenanceScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RetrofitProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    INSTALLED = "INSTALLED"
    COMMISSIONED = "COMMISSIONED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class SavingsStatus(str, Enum):
    DRAFT = "DRAFT"
    MODELED = "MODELED"
    MEASUREMENT_OPEN = "MEASUREMENT_OPEN"
    MEASURED = "MEASURED"


class RebateStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ContractTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ServiceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class TicketSeverity(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class ServiceTicketStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class RentalAssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_RENT = "ON_RENT"
    IN_MAINTENANCE = "IN_MAINTENANCE"


class RentalReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    ON_RENT = "ON_RENT"
    RETURNED = "RETURNED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    AWAITING_MEASUREMENT = "AWAITING_MEASUREMENT"
    SETTLED_NO_SHORTFALL = "SETTLED_NO_SHORTFALL"
    SETTLED_PAYOUT_DUE = "SETTLED_PAYOUT_DUE"
    PAID = "PAID"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERRULED = "RESOLVED_OVERRULED"


class ServiceCreditStatus(str, Enum):
    ACCRUED = "ACCRUED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries the full common-field set
# (id, created_at, updated_at, version) per PRD §2.4.
# ---------------------------------------------------------------------------

class Facility(TypedDict, total=False):
    id: str
    name: str
    utility_rate_cents_per_kwh: int
    operating_hours_per_year: int
    repair_budget_cents: int
    status: str
    posture: str
    repair_committed_cents: int
    rental_escrow_cents: int
    created_at: str
    updated_at: str
    version: int


class Compressor(TypedDict, total=False):
    id: str
    facility_id: str
    asset_tag: str
    rated_kw: int
    rated_cfm: int
    run_hours_total: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DemandProfile(TypedDict, total=False):
    id: str
    facility_id: str
    window_start_date: str
    window_end_date: str
    measured_kwh: int
    measured_avg_cfm: float
    measured_peak_cfm: float
    baseline_annual_kwh: int
    status: str
    locked_by_user_id: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeakSurvey(TypedDict, total=False):
    id: str
    facility_id: str
    survey_date: str
    status: str
    submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    total_leak_cfm: Optional[float]
    tag_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LeakTag(TypedDict, total=False):
    id: str
    survey_id: str
    location_description: str
    cfm_loss: float
    repair_quote_cents: int
    severity: Optional[str]
    priority_rank: Optional[int]
    annual_kwh_savings: Optional[int]
    status: str
    repaired_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceSchedule(TypedDict, total=False):
    id: str
    facility_id: str
    component: str
    interval_hours: int
    anchor_run_hours: int
    next_due_run_hours: int
    is_delinquent: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RetrofitProject(TypedDict, total=False):
    id: str
    facility_id: str
    baseline_pressure_psi: int
    target_pressure_psi: int
    sequence_compressor_ids: List[str]
    project_cost_cents: int
    accepted_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SavingsCase(TypedDict, total=False):
    id: str
    facility_id: str
    baseline_profile_id: str
    baseline_profile_version: int
    baseline_stale: bool
    retrofit_project_id: str
    retrofit_stale: bool
    deemed_annual_savings_kwh: int
    measured_annual_savings_kwh: Optional[int]
    post_profile_id: Optional[str]
    savings_status: str
    rebate_status: str
    provisional_rebate_cents: Optional[int]
    final_rebate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict, total=False):
    id: str
    facility_id: str
    tier: str
    start_date: str
    term_months: int
    end_date: str
    monthly_fee_cents: int
    sla_base_hours: int
    status: str
    sla_breach_count: int
    termination_penalty_waived: bool
    termination_fee_cents: Optional[int]
    credits_accrued_total_cents: int
    credits_applied_total_cents: int
    credits_expired_total_cents: int
    credits_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict, total=False):
    id: str
    facility_id: str
    contract_id: str
    compressor_id: str
    severity: str
    reported_at: str
    sla_tier_snapshot: str
    sla_deadline: str
    first_response_at: Optional[str]
    sla_met: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAsset(TypedDict, total=False):
    id: str
    fleet_tag: str
    rated_cfm: int
    daily_rate_cents: int
    deposit_cents: int
    status: str
    next_available_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalReservation(TypedDict, total=False):
    id: str
    facility_id: str
    rental_asset_id: str
    down_compressor_id: str
    start_date: str
    end_date: str
    planned_days: int
    quoted_cents: int
    deposit_cents: int
    actual_return_date: Optional[str]
    actual_bill_cents: Optional[int]
    final_bill_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class GuaranteeCertificate(TypedDict, total=False):
    id: str
    facility_id: str
    contract_id: str
    savings_case_id: str
    guaranteed_pct: float
    guaranteed_kwh: int
    deadband_kwh: int
    measured_kwh_at_settlement: Optional[int]
    shortfall_kwh: Optional[int]
    payout_cents: Optional[int]
    settlement_blocked: bool
    settlement_status: str
    dispute_status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict, total=False):
    id: str
    contract_id: str
    ticket_id: str
    source: str
    amount_cents: int
    accrued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
