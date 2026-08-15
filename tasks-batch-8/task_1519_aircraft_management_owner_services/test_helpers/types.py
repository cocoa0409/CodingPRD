"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    OWNER = "Owner"
    ACCOUNT_EXECUTIVE = "AccountExecutive"
    FLIGHT_OPS_MANAGER = "FlightOpsManager"
    MAINTENANCE_PLANNER = "MaintenancePlanner"
    FINANCE_CONTROLLER = "FinanceController"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CONTRACTS_MANAGER = "ContractsManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    HANDOVER_IN_PROGRESS = "HANDOVER_IN_PROGRESS"
    TERMINATED = "TERMINATED"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExpenseStatus(str, Enum):
    POSTED = "POSTED"
    BILLED = "BILLED"
    VOID = "VOID"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    DELIVERED = "DELIVERED"


class CrewStatus(str, Enum):
    HIRED = "HIRED"
    IN_TRAINING = "IN_TRAINING"
    QUALIFIED = "QUALIFIED"
    INACTIVE = "INACTIVE"


class TripStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOID = "VOID"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class ProgramStatus(str, Enum):
    QUOTED = "QUOTED"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class EventStatus(str, Enum):
    FORECAST = "FORECAST"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class TaxAllocationMethod(str, Enum):
    FLIGHT_HOURS = "FLIGHT_HOURS"
    TRIP_LEGS = "TRIP_LEGS"


class ExpenseCategory(str, Enum):
    FUEL = "FUEL"
    CREW = "CREW"
    MAINTENANCE = "MAINTENANCE"
    HANGAR = "HANGAR"
    INSURANCE = "INSURANCE"
    PROGRAM_ACCRUAL = "PROGRAM_ACCRUAL"
    CHARTER_DIRECT = "CHARTER_DIRECT"
    OTHER = "OTHER"


class TaxUse(str, Enum):
    OWNER_USE = "OWNER_USE"
    CHARTER_USE = "CHARTER_USE"
    MIXED = "MIXED"


class TripUse(str, Enum):
    OWNER_USE = "OWNER_USE"
    CHARTER = "CHARTER"


class CrewRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    FIRST_OFFICER = "FIRST_OFFICER"


class DutyRole(str, Enum):
    PIC = "PIC"
    SIC = "SIC"


class FilingKind(str, Enum):
    INSURANCE_COI = "INSURANCE_COI"
    REGISTRATION = "REGISTRATION"
    OPS_SPECS_AMENDMENT = "OPS_SPECS_AMENDMENT"


class VendorKind(str, Enum):
    HANGAR = "HANGAR"
    FUEL = "FUEL"


class ContractUnit(str, Enum):
    MONTH = "MONTH"
    GALLON = "GALLON"


# All entities carry the full common set id/created_at/updated_at/version (PRD §2.4).

class Owner(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    owner_id: str
    tail_number: str
    model: str
    home_base_icao: str
    total_time_hours: float
    created_at: str
    updated_at: str
    version: int


class ManagementAgreement(TypedDict, total=False):
    id: str
    owner_id: str
    aircraft_id: str
    monthly_management_fee_cents: int
    variable_fee_pct: float
    charter_owner_share_pct: float
    tax_allocation_method: str
    status: str
    notice_given_at: Optional[str]
    records_total: int
    records_released: int
    created_at: str
    updated_at: str
    version: int


class OperatingBudget(TypedDict, total=False):
    id: str
    aircraft_id: str
    fiscal_year: int
    fuel_cents: int
    maintenance_cents: int
    crew_cents: int
    hangar_cents: int
    insurance_cents: int
    other_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Expense(TypedDict, total=False):
    id: str
    aircraft_id: str
    statement_id: Optional[str]
    trip_id: Optional[str]
    category: str
    amount_cents: int
    service_date: str
    paid_date: Optional[str]
    vendor_name: str
    tax_use: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlyStatement(TypedDict, total=False):
    id: str
    aircraft_id: str
    period: str
    prepared_by_user_id: str
    certified_by_user_id: Optional[str]
    accrual_total_cents: int
    cash_total_cents: int
    management_fee_cents: int
    charter_offset_cents: int
    budget_variance_cents: Optional[int]
    mixed_owner_share_cents: int
    mixed_charter_share_cents: int
    tax_method_used: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    aircraft_id: str
    full_name: str
    crew_role: str
    hire_date: str
    status: str
    training_hours_accumulated: float
    duty_hours_7d: float
    duty_hours_28d: float
    flight_hours_total: float
    created_at: str
    updated_at: str
    version: int


class TripRequest(TypedDict, total=False):
    id: str
    aircraft_id: str
    trip_use: str
    depart_icao: str
    arrive_icao: str
    departure_at: str
    block_hours_est: float
    block_hours_actual: Optional[float]
    charter_quote_cents: Optional[int]
    owner_credit_cents: Optional[int]
    charter_shortfall_cents: Optional[int]
    decline_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DutyAssignment(TypedDict, total=False):
    id: str
    trip_id: str
    crew_member_id: str
    duty_role: str
    duty_start_at: str
    duty_end_at: str
    duty_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceProgram(TypedDict, total=False):
    id: str
    aircraft_id: str
    program_name: str
    rate_per_hour_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceEvent(TypedDict, total=False):
    id: str
    aircraft_id: str
    previous_event_id: Optional[str]
    event_code: str
    interval_hours: float
    due_at_aircraft_hours: float
    scheduled_date: Optional[str]
    completed_at: Optional[str]
    actual_aircraft_hours: Optional[float]
    handed_over_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceFiling(TypedDict, total=False):
    id: str
    aircraft_id: str
    filing_kind: str
    authority: str
    reference_no: str
    valid_until: str
    filed_at: Optional[str]
    decision_notes: Optional[str]
    handed_over_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict, total=False):
    id: str
    aircraft_id: str
    vendor_kind: str
    vendor_name: str
    unit: str
    rate_cents_per_unit: int
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
