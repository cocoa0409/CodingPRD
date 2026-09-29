"""Programme tunables, enumerations and numeric constants named by the PRD.

Every value here is a literal the PRD states, either as a seeded configuration
default (§2.6) or as a declared enumeration (§3). Nothing is inferred.
"""

# ── Service root and logical clock ──────────────────────────────────────────

API_PREFIX = "/cpo"

# PRD §2.5: "Before any request moves it, the clock reads exactly
# `2026-08-01T00:00:00Z`".
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_EMITTED = "2026-08-01T00:00:00.000Z"

# ── Pagination (§2.3) ───────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ── Roles (§2.1) ────────────────────────────────────────────────────────────

ROLE_PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
ROLE_PROGRAM_AUDITOR = "ProgramAuditor"
ROLE_DEALER_PRINCIPAL = "DealerPrincipal"
ROLE_INSPECTION_TECHNICIAN = "InspectionTechnician"
ROLE_CUSTOMER_ADVOCATE = "CustomerAdvocate"

ALL_ROLES = (
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_PROGRAM_AUDITOR,
    ROLE_DEALER_PRINCIPAL,
    ROLE_INSPECTION_TECHNICIAN,
    ROLE_CUSTOMER_ADVOCATE,
)

# ── Seeded programme configuration defaults (§2.6) ──────────────────────────

MAX_AGE_DAYS = 2190
MAX_ODOMETER_MILES = 80000
INELIGIBLE_TITLE_BRANDS = (
    "SALVAGE",
    "FLOOD",
    "LEMON",
    "REBUILT",
    "ODOMETER_DISCREPANCY",
)
INELIGIBLE_PRIOR_USES = ("RENTAL", "TAXI", "DRIVING_SCHOOL", "POLICE")

BASE_FEE_CENTS = 89900
AGE_SURCHARGE_FREE_YEARS = 3
AGE_SURCHARGE_CENTS_PER_YEAR = 12500
MILEAGE_SURCHARGE_FREE_MILES = 40000
MILEAGE_SURCHARGE_CENTS_PER_10K = 9000
SURCHARGE_CAP_PCT = 0.35
VOLUME_DISCOUNT_TIERS = (
    {"min_count": 0, "pct": 0.0},
    {"min_count": 10, "pct": 0.05},
    {"min_count": 50, "pct": 0.10},
)

RECON_REIMBURSEMENT_SHARE = 0.6
RECON_REIMBURSEMENT_CAP_CENTS = 150000

FACTORY_BASIC_MONTHS = 36
FACTORY_BASIC_MILES = 36000
WARRANTY_EXTENSION_MONTHS = 12
WARRANTY_EXTENSION_MILES = 12000
WARRANTY_TOTAL_CAP_MONTHS = 84
WARRANTY_TOTAL_CAP_MILES = 100000

CLAIM_PER_CLAIM_CAP_CENTS = 250000
CLAIM_WINDOW_DAYS = 365
CLAIM_VARIANT_VOLUME_FLOOR = 20
CLAIM_RATIO_PROBATION_THRESHOLD = 0.25
CLAIM_RATIO_SUSPENSION_THRESHOLD = 0.40
PROBATION_CLAIM_SHARE = 0.8

AUDIT_SAMPLE_PCT = 0.2
AUDIT_SAMPLE_MIN_PER_RUN = 1
AUDIT_FAIL_SUSPENSION_COUNT = 2

DOC_RETENTION_YEARS = 7
REQUIRED_DOC_TYPES = (
    "TITLE_HISTORY_REPORT",
    "INSPECTION_WORKSHEET",
    "RECONDITIONING_INVOICE",
    "CUSTOMER_DISCLOSURE",
)
LISTING_REQUIRED_DISCLOSURE_FIELDS = (
    "CERTIFIED_BADGE",
    "WARRANTY_END_DATE",
    "INSPECTION_DATE",
    "CERTIFICATION_NUMBER",
)
LISTING_REMOVAL_SLA_HOURS = 48

INSPECTION_SLOT_MINUTES = 120
TECHNICIAN_BUFFER_MINUTES = 30

# The complete set of tunables the configuration row carries, used by the
# retrieval test to prove none of them is missing.
PROGRAM_CONFIG_TUNABLES = (
    "max_age_days",
    "max_odometer_miles",
    "ineligible_title_brands",
    "ineligible_prior_uses",
    "base_fee_cents",
    "age_surcharge_free_years",
    "age_surcharge_cents_per_year",
    "mileage_surcharge_free_miles",
    "mileage_surcharge_cents_per_10k",
    "surcharge_cap_pct",
    "volume_discount_tiers",
    "recon_reimbursement_share",
    "recon_reimbursement_cap_cents",
    "factory_basic_months",
    "factory_basic_miles",
    "warranty_extension_months",
    "warranty_extension_miles",
    "warranty_total_cap_months",
    "warranty_total_cap_miles",
    "claim_per_claim_cap_cents",
    "claim_window_days",
    "claim_variant_volume_floor",
    "claim_ratio_probation_threshold",
    "claim_ratio_suspension_threshold",
    "probation_claim_share",
    "audit_sample_pct",
    "audit_sample_min_per_run",
    "audit_fail_suspension_count",
    "doc_retention_years",
    "required_doc_types",
    "listing_required_disclosure_fields",
    "listing_removal_sla_hours",
    "inspection_slot_minutes",
    "technician_buffer_minutes",
)

DEFAULT_PROGRAM_CONFIG = {
    "max_age_days": MAX_AGE_DAYS,
    "max_odometer_miles": MAX_ODOMETER_MILES,
    "base_fee_cents": BASE_FEE_CENTS,
    "age_surcharge_free_years": AGE_SURCHARGE_FREE_YEARS,
    "age_surcharge_cents_per_year": AGE_SURCHARGE_CENTS_PER_YEAR,
    "mileage_surcharge_free_miles": MILEAGE_SURCHARGE_FREE_MILES,
    "mileage_surcharge_cents_per_10k": MILEAGE_SURCHARGE_CENTS_PER_10K,
    "recon_reimbursement_cap_cents": RECON_REIMBURSEMENT_CAP_CENTS,
    "factory_basic_months": FACTORY_BASIC_MONTHS,
    "factory_basic_miles": FACTORY_BASIC_MILES,
    "warranty_extension_months": WARRANTY_EXTENSION_MONTHS,
    "warranty_extension_miles": WARRANTY_EXTENSION_MILES,
    "warranty_total_cap_months": WARRANTY_TOTAL_CAP_MONTHS,
    "warranty_total_cap_miles": WARRANTY_TOTAL_CAP_MILES,
    "claim_per_claim_cap_cents": CLAIM_PER_CLAIM_CAP_CENTS,
    "claim_window_days": CLAIM_WINDOW_DAYS,
    "claim_variant_volume_floor": CLAIM_VARIANT_VOLUME_FLOOR,
    "audit_sample_min_per_run": AUDIT_SAMPLE_MIN_PER_RUN,
    "audit_fail_suspension_count": AUDIT_FAIL_SUSPENSION_COUNT,
    "doc_retention_years": DOC_RETENTION_YEARS,
    "listing_removal_sla_hours": LISTING_REMOVAL_SLA_HOURS,
    "inspection_slot_minutes": INSPECTION_SLOT_MINUTES,
    "technician_buffer_minutes": TECHNICIAN_BUFFER_MINUTES,
}

DEFAULT_PROGRAM_CONFIG_FRACTIONS = {
    "surcharge_cap_pct": SURCHARGE_CAP_PCT,
    "recon_reimbursement_share": RECON_REIMBURSEMENT_SHARE,
    "claim_ratio_probation_threshold": CLAIM_RATIO_PROBATION_THRESHOLD,
    "claim_ratio_suspension_threshold": CLAIM_RATIO_SUSPENSION_THRESHOLD,
    "probation_claim_share": PROBATION_CLAIM_SHARE,
    "audit_sample_pct": AUDIT_SAMPLE_PCT,
}

# ── Declared enumerations (§3) ──────────────────────────────────────────────

TITLE_BRANDS = (
    "CLEAN",
    "SALVAGE",
    "FLOOD",
    "LEMON",
    "REBUILT",
    "ODOMETER_DISCREPANCY",
)
PRIOR_USES = (
    "PERSONAL",
    "LEASE",
    "FLEET",
    "RENTAL",
    "TAXI",
    "DRIVING_SCHOOL",
    "POLICE",
)
ITEM_CATEGORIES = (
    "POWERTRAIN",
    "BRAKES",
    "TIRES",
    "SAFETY",
    "ELECTRICAL",
    "BODY",
    "INTERIOR",
    "ROAD_TEST",
)
ITEM_SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
RESULT_OUTCOMES = ("PASS", "FAIL", "NOT_APPLICABLE")
COMPONENT_CATEGORIES = (
    "POWERTRAIN",
    "BRAKES",
    "TIRES",
    "SAFETY",
    "ELECTRICAL",
    "BODY",
    "INTERIOR",
)
LISTING_CHANNELS = ("OEM_SITE", "DEALER_SITE", "THIRD_PARTY_AGGREGATOR")
COMPLAINT_CATEGORIES = (
    "UNDISCLOSED_DAMAGE",
    "INSPECTION_ITEM_FAILURE",
    "WARRANTY_DENIAL",
    "MARKETING_MISREPRESENTATION",
)
HISTORY_EVENT_TYPES = (
    "ODOMETER_UPDATE",
    "TITLE_BRANDED",
    "RETAIL_SOLD",
    "WHOLESALED",
    "RETURNED_TO_INVENTORY",
)
FINDING_CODES = (
    "NONE",
    "DOCUMENTATION_MISSING",
    "ELIGIBILITY_VIOLATION",
    "INSPECTION_INCOMPLETE",
)
DENIAL_REASONS = (
    "NOT_COVERED_COMPONENT",
    "PRE_EXISTING_DAMAGE",
    "INSUFFICIENT_EVIDENCE",
)
REJECTION_REASONS = (None, "DOCUMENTATION_INCOMPLETE", "DEALER_SUSPENDED", "ADMIN_ACTION")
DECERTIFICATION_REASONS = (
    None,
    "RETAIL_SOLD",
    "WHOLESALED",
    "POST_AUDIT_FAIL",
    "TITLE_BRANDED",
    "COMPLAINT_REINSPECTION_FAIL",
    "ADMIN_ACTION",
)
WITHDRAWAL_REASONS = ("CERTIFICATION_DECERTIFIED", "DEALER_SUSPENDED", "DEALER_ACTION")
PRIVILEGE_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED")
PRIVILEGE_REASONS = (
    None,
    "CLAIM_RATIO_PROBATION",
    "CLAIM_RATIO_SUSPENSION",
    "AUDIT_FAILURE_SUSPENSION",
    "ADMIN_ACTION",
)
CLAIM_RATIO_VARIANTS = ("LIFETIME_CUMULATIVE", "TRAILING_WINDOW")
WARRANTY_ANCHOR_VARIANTS = ("IN_SERVICE_ANCHORED", "CERTIFICATION_ANCHORED")

# ── State value sets (§2.7, §3) ─────────────────────────────────────────────

CPO_STATES = ("NOT_CERTIFIED", "CERTIFICATION_PENDING", "CERTIFIED", "DECERTIFIED")
INVENTORY_STATES = ("IN_INVENTORY", "RETAIL_SOLD", "WHOLESALED")
TEMPLATE_STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")
INSPECTION_STATUSES = (
    "DRAFT",
    "IN_PROGRESS",
    "RECONDITIONING_REQUIRED",
    "PASSED",
    "FAILED",
    "VOIDED",
)
INSPECTION_PURPOSES = ("INITIAL", "RE_INSPECTION")
INSPECTION_FAILURE_REASONS = (
    "CRITICAL_ITEM_FAIL",
    "SUPERSEDED_BY_REINSPECTION",
    "COMPLAINT_DISMISSED",
)
RECONDITIONING_STATUSES = ("REQUIRED", "COMPLETED", "WAIVED")
CERTIFICATION_STATUSES = (
    "SUBMITTED",
    "ACTIVE",
    "UNDER_AUDIT",
    "REJECTED",
    "SUPERSEDED",
    "DECERTIFIED",
)
AUDIT_SAMPLE_STATUSES = ("SELECTED", "PASSED", "FAILED")
CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "DENIED")
LISTING_STATUSES = ("DRAFT", "SYNDICATED", "WITHDRAWN")
COMPLAINT_STATUSES = (
    "OPEN",
    "REINSPECTION_ORDERED",
    "RESOLVED_UPHELD",
    "RESOLVED_DECERTIFIED",
    "DISMISSED",
)

# ── Derived deadline lengths the PRD states in words ───────────────────────

# §3.11: "a derived `reinspection_deadline_at` equal to `filed_at` plus five days".
REINSPECTION_DEADLINE_DAYS = 5
