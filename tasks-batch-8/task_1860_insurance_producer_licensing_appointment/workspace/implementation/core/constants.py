"""Domain constants read from SCAFFOLD.yaml / PRD.md (never invented)."""

from decimal import Decimal

# Logical clock startup value (PRD 2.5): exactly this instant, never wall clock.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Roles (PRD 2.1) - X-User-Role must name one of these.
ROLES = (
    "Producer",
    "LicensingCoordinator",
    "ComplianceOfficer",
    "FinanceOps",
    "CarrierAdmin",
)

# Line-of-authority catalog (entities.License.fields.lines_of_authority).
LOAS = ("LIFE", "ACCIDENT_HEALTH", "PROPERTY", "CASUALTY", "PERSONAL_LINES")

# Base commission rate per line of authority (calculations.commission_amount_cents
# refers to LOA_BASE_RATE[...]).  Values pinned by the task's design examples:
# LIFE 0.10 (floor(999 * 0.10) == 99), PROPERTY 0.12 (floor(12345678 * 0.12 *
# 1.00 * 1.05) == 1555555), CASUALTY 0.12 (floor(999 * 0.12) == 119).
LOA_BASE_RATE = {
    "LIFE": Decimal("0.10"),
    "ACCIDENT_HEALTH": Decimal("0.08"),
    "PROPERTY": Decimal("0.12"),
    "CASUALTY": Decimal("0.12"),
    "PERSONAL_LINES": Decimal("0.15"),
}

# commission_amount_cents constants.
TIER2_THRESHOLD_CENTS = 100000000
TIER3_THRESHOLD_CENTS = 500000000
AGENCY_UPLIFT = Decimal("1.05")
VOLUME_MULT_LOW = Decimal("1.00")
VOLUME_MULT_MID = Decimal("1.10")
VOLUME_MULT_HIGH = Decimal("1.25")

# PolicyApplication premium floor.
MIN_PREMIUM_CENTS = 500

# ce_compliance_determination defaults.
DEFAULT_REQUIRED_HOURS = Decimal("24")
DEFAULT_ETHICS_HOURS = Decimal("3")

# jit_filing_deadline.
JIT_FILING_WINDOW_DAYS = 15

# RegulatoryInquiry response clock.
INQUIRY_RESPONSE_DAYS = 30

# renewal_window.
RENEWAL_WINDOW_DAYS_BEFORE = 90
RENEWAL_GRACE_DAYS_AFTER = 30
RENEWAL_EXTENSION_MONTHS = 24

# FOR_CAUSE termination filing deadline.
TERMINATION_FILING_DAYS = 30

# PROBATION spacing.
PROBATION_SPACING_DAYS = 365

# Enums.
PRODUCER_STATUSES = ("ACTIVE", "SUSPENDED")
LICENSE_CLASSES = ("RESIDENT", "NON_RESIDENT")
LICENSE_STATUSES = ("ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED")
CE_CATEGORIES = ("GENERAL", "ETHICS")
CE_CREDIT_STATUSES = ("REPORTED", "ACCEPTED", "REJECTED")
APPOINTMENT_ORIGINS = ("STANDARD", "JIT")
APPOINTMENT_STATUSES = (
    "REQUESTED", "JIT_PENDING", "ACTIVE",
    "TERMINATION_PENDING", "TERMINATED", "LAPSED",
)
APPOINTMENT_NON_TERMINAL = ("REQUESTED", "JIT_PENDING", "ACTIVE", "TERMINATION_PENDING")
TERMINATION_REASONS = ("VOLUNTARY", "FOR_CAUSE", "LICENSE_INACTIVE")
APPLICATION_STATUSES = ("SUBMITTED", "APPROVED", "DECLINED", "ISSUED", "RESCINDED")
COMMISSION_STATUSES = ("HELD", "PAYABLE", "PAID", "FORFEITED")
COMMISSION_NON_TERMINAL = ("HELD", "PAYABLE")
HOLD_REASONS = ("APPOINTMENT_PENDING", "UNLICENSED_AT_SALE", "REGULATORY_HOLD")
ACTION_TYPES = ("FINE", "SUSPENSION", "REVOCATION", "PROBATION")
ACTION_STATUSES = ("REPORTED", "CONFIRMED", "DISMISSED")
INQUIRY_STATUSES = ("OPEN", "OVERDUE", "RESPONSE_SUBMITTED", "CLOSED")
ELIGIBILITY_STATUSES = ("ELIGIBLE", "LICENSE_GAP", "APPOINTMENT_GAP", "PRODUCER_SUSPENDED")

# Pagination (response_envelope.pagination_defaults).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
