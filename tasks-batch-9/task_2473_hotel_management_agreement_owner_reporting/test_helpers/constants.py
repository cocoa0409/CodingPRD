"""Contract constants: prefixes, roles, enum vocabularies, defaults, clock anchors."""

API_PREFIX = "/hotel-management"
CLOCK_PATH = "/_clock/set_current_utc"

# The logical clock reads exactly this instant before any client sets it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"


class Role:
    PLATFORM_ADMIN = "PlatformAdmin"
    HOTEL_MANAGER_OPS = "HotelManagerOps"
    ASSET_MANAGER = "AssetManager"
    OWNER_REP = "OwnerRep"


ALL_ROLES = [
    Role.PLATFORM_ADMIN,
    Role.HOTEL_MANAGER_OPS,
    Role.ASSET_MANAGER,
    Role.OWNER_REP,
]

UNDECLARED_ROLE = "BrandStandardsAuditor"


class AgreementStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CURE_PERIOD = "CURE_PERIOD"
    TERMINATION_NOTICED = "TERMINATION_NOTICED"
    TERMINATED = "TERMINATED"


class BudgetStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DEEMED_APPROVED = "DEEMED_APPROVED"
    DEADLOCK_CARRYFORWARD = "DEADLOCK_CARRYFORWARD"
    SUPERSEDED = "SUPERSEDED"


class BudgetDecision:
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class VarianceCategory:
    OPERATING = "OPERATING"
    CAPITAL_FFE = "CAPITAL_FFE"
    CAPITAL_BRAND = "CAPITAL_BRAND"


class ApprovalLevel:
    MANAGER_DISCRETION = "MANAGER_DISCRETION"
    ASSET_MANAGER = "ASSET_MANAGER"
    OWNER_REP = "OWNER_REP"


class VarianceStatus:
    AUTO_APPROVED = "AUTO_APPROVED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class VarianceDecision:
    APPROVE = "APPROVE"
    DENY = "DENY"


class FinancialStatus:
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class BenchmarkStatus:
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    CHALLENGED = "CHALLENGED"


class PackageStatus:
    INCOMPLETE = "INCOMPLETE"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    CONTESTED = "CONTESTED"


class ReviewDimension:
    FINANCIAL = "FINANCIAL"
    BENCHMARK = "BENCHMARK"


class ReviewDecision:
    ACCEPT = "ACCEPT"
    DISPUTE = "DISPUTE"


class BenchmarkSource:
    STR_REPORT = "STR_REPORT"
    MANAGER_ESTIMATE = "MANAGER_ESTIMATE"


class ServiceCode:
    RESERVATIONS = "RESERVATIONS"
    REVENUE_MANAGEMENT = "REVENUE_MANAGEMENT"
    IT_HOSTING = "IT_HOSTING"
    PROCUREMENT = "PROCUREMENT"
    TALENT = "TALENT"


class AllocationBasis:
    ROOMS_AVAILABLE = "ROOMS_AVAILABLE"
    GROSS_REVENUE = "GROSS_REVENUE"
    HEADCOUNT = "HEADCOUNT"
    FLAT = "FLAT"


class DisclosureStatus:
    DISCLOSED = "DISCLOSED"
    CONTESTED = "CONTESTED"
    ADJUSTED = "ADJUSTED"


class ChargeReviewAction:
    CONTEST = "CONTEST"
    REAFFIRM = "REAFFIRM"
    ADJUST = "ADJUST"


class FeeType:
    BASE = "BASE"
    INCENTIVE = "INCENTIVE"
    CENTRALIZED_SERVICES = "CENTRALIZED_SERVICES"


class FeeVariant:
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AccrualStatus:
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    DISPUTED_HELD = "DISPUTED_HELD"


class DistributionStatus:
    CALCULATED = "CALCULATED"
    HELD = "HELD"
    EXECUTED = "EXECUTED"


class LedgerEntryType:
    CONTRIBUTION = "CONTRIBUTION"
    DISBURSEMENT = "DISBURSEMENT"
    DISBURSEMENT_REVERSAL = "DISBURSEMENT_REVERSAL"


class LedgerSourceKind:
    DISTRIBUTION_EXECUTION = "DISTRIBUTION_EXECUTION"
    BRAND_DISPUTE_FUNDING = "BRAND_DISPUTE_FUNDING"
    BRAND_DISPUTE_RESCISSION = "BRAND_DISPUTE_RESCISSION"


class CallReason:
    FLOOR_RESTORATION = "FLOOR_RESTORATION"
    DISTRIBUTION_SHORTFALL = "DISTRIBUTION_SHORTFALL"
    CLAIM_ALLOCATION = "CLAIM_ALLOCATION"


class CallStatus:
    REQUESTED = "REQUESTED"
    FUNDED = "FUNDED"
    OVERDUE = "OVERDUE"
    WAIVED_OFFSET = "WAIVED_OFFSET"


class TestStatus:
    PASSED = "PASSED"
    FAILED_CURABLE = "FAILED_CURABLE"
    CURE_ELECTED = "CURE_ELECTED"
    CURED = "CURED"
    TERMINATION_TRIGGERED = "TERMINATION_TRIGGERED"
    TERMINATED_NOTICE_ISSUED = "TERMINATED_NOTICE_ISSUED"


class CureAction:
    ELECT_CURE = "ELECT_CURE"
    PAY_CURE = "PAY_CURE"


class DisputeStatus:
    OPENED = "OPENED"
    MANAGER_RESPONDED = "MANAGER_RESPONDED"
    OWNER_COUNTERED = "OWNER_COUNTERED"
    ESCALATED_TO_FRANCHISOR = "ESCALATED_TO_FRANCHISOR"
    RESOLVED_OWNER_FUNDS = "RESOLVED_OWNER_FUNDS"
    RESOLVED_WAIVED = "RESOLVED_WAIVED"
    DEADLOCKED = "DEADLOCKED"


class DisputeAction:
    MANAGER_RESPONSE = "MANAGER_RESPONSE"
    OWNER_COUNTER = "OWNER_COUNTER"
    ESCALATE_TO_FRANCHISOR = "ESCALATE_TO_FRANCHISOR"
    RESOLVE_OWNER_FUNDS = "RESOLVE_OWNER_FUNDS"
    RESOLVE_WAIVED = "RESOLVE_WAIVED"
    RESCIND_RESOLUTION = "RESCIND_RESOLUTION"


class FundingSource:
    FFE_RESERVE = "FFE_RESERVE"
    OWNER_CONTRIBUTION = "OWNER_CONTRIBUTION"


class PositionClass:
    GM = "GM"
    EXEC_COMMITTEE = "EXEC_COMMITTEE"
    LINE_STAFF = "LINE_STAFF"


class ClaimStatus:
    FILED = "FILED"
    ALLOCATED = "ALLOCATED"
    REVERSED = "REVERSED"


class ClaimAction:
    ALLOCATE = "ALLOCATE"
    REVERSE = "REVERSE"


class EmployeeModel:
    OWNER_EMPLOYEES = "OWNER_EMPLOYEES"
    MANAGER_EMPLOYEES = "MANAGER_EMPLOYEES"


class EmployerOfRecord:
    OWNER = "OWNER"
    MANAGER = "MANAGER"


class BudgetSourceStatus:
    APPROVED = "APPROVED"
    DEEMED_APPROVED = "DEEMED_APPROVED"
    DEADLOCK_CARRYFORWARD = "DEADLOCK_CARRYFORWARD"


# ---------------------------------------------------------------------------
# Declared registration defaults
# ---------------------------------------------------------------------------

AGREEMENT_DEFAULTS = {
    "incentive_tier2_pct": 0.15,
    "incentive_tier2_threshold_cents": 5000000,
    "ffe_reserve_pct": 0.04,
    "centralized_services_cap_pct": 0.015,
    "working_capital_floor_cents": 0,
    "initial_working_capital_cents": 0,
    "owner_review_window_days": 30,
    "max_revision_rounds": 2,
    "cure_window_days": 60,
    "dispute_standstill_days": 45,
    "max_dispute_rounds": 2,
    "funding_due_days": 15,
    "termination_notice_days": 90,
    "gop_test_threshold_pct": 0.85,
    "rpi_test_threshold": 90.0,
    "min_benchmark_months": 10,
    "test_periods_expected": 12,
    "consecutive_failure_limit": 2,
    "employee_model": EmployeeModel.MANAGER_EMPLOYEES,
    "manager_indemnity_cap_cents": 0,
}

# Pagination bounds
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# The settlement projection returned by the annual true-up: the complete key set.
TRUE_UP_SUMMARY_KEYS = {
    "fiscal_year",
    "accepted_period_count",
    "annual_agop_cents",
    "final_incentive_fee_cents",
    "provisional_incentive_total_cents",
    "true_up_delta_cents",
    "true_up_accrual_id",
    "attached_report_package_id",
}

# Decimal precision pins
VARIANCE_PCT_DECIMALS = 6
RPI_DECIMALS = 2
GOP_ACHIEVEMENT_DECIMALS = 4

__all__ = [
    "AGREEMENT_DEFAULTS",
    "ALL_ROLES",
    "API_PREFIX",
    "AccrualStatus",
    "AgreementStatus",
    "AllocationBasis",
    "ApprovalLevel",
    "BenchmarkSource",
    "BenchmarkStatus",
    "BudgetDecision",
    "BudgetSourceStatus",
    "BudgetStatus",
    "CLOCK_EPOCH",
    "CLOCK_PATH",
    "CallReason",
    "CallStatus",
    "ChargeReviewAction",
    "ClaimAction",
    "ClaimStatus",
    "CureAction",
    "DEFAULT_LIMIT",
    "DEFAULT_OFFSET",
    "DisclosureStatus",
    "DisputeAction",
    "DisputeStatus",
    "DistributionStatus",
    "EmployeeModel",
    "EmployerOfRecord",
    "FeeType",
    "FeeVariant",
    "FinancialStatus",
    "FundingSource",
    "GOP_ACHIEVEMENT_DECIMALS",
    "LedgerEntryType",
    "LedgerSourceKind",
    "MAX_LIMIT",
    "PackageStatus",
    "PositionClass",
    "RPI_DECIMALS",
    "ReviewDecision",
    "ReviewDimension",
    "Role",
    "ServiceCode",
    "TRUE_UP_SUMMARY_KEYS",
    "TestStatus",
    "UNDECLARED_ROLE",
    "VARIANCE_PCT_DECIMALS",
    "VarianceCategory",
    "VarianceDecision",
    "VarianceStatus",
]
