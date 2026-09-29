"""In-memory data store. Starts completely empty on every process boot."""
from decimal import Decimal

from core import clock_now, fmt_dt, new_id, next_seq

# --------------------------------------------------------------------------
# Global constants (scaffold global_constants)
# --------------------------------------------------------------------------

BCR_APPROVAL_THRESHOLD = Decimal("1.0")
APPRAISAL_VALIDITY_MONTHS = 12
MAX_APPRAISAL_REVISIONS = 2
OFFER_VALIDITY_DAYS = 30
MONITORING_INTERVAL_MONTHS = 36
CURE_WINDOW_DAYS = 90
REQUIRED_UTILITY_TYPES = ["WATER", "ELECTRIC", "GAS", "SEWER"]
PROHIBITED_USE_CODES = ["NEW_STRUCTURE", "FILL_PLACEMENT", "RESALE_FOR_DEVELOPMENT", "PERMANENT_STORAGE"]
MIN_DIVERSION_PCT = Decimal("25.0")
VIABILITY_VIABLE_MIN = Decimal("0.75")
VIABILITY_AT_RISK_MIN = Decimal("0.50")
DEMOLITION_BUFFER_HOURS = 24
MAX_DEMOLITION_REWORKS = 2
RHP_OWNER_CAP_CENTS = 3150000
RENTAL_ASSISTANCE_CAP_CENTS = 3150000
MAX_RENTAL_ASSISTANCE_MONTHS = 42
INCOME_RENT_RATIO = Decimal("0.30")
INCENTIVE_CAP_CENTS = 2250000
MAX_RELOCATION_APPEALS = 2
OPEN_SPACE_TERMINATION_AUTH_PREFIX = "FEMA-OSR-"

DOB_SOURCE_FACTORS = {
    "NFIP_CLAIM": Decimal("1.00"),
    "ICC": Decimal("1.00"),
    "PRIVATE_INSURANCE": Decimal("1.00"),
    "SBA_LOAN": Decimal("0.50"),
    "CDBG_DR": Decimal("0.85"),
}

ROLES = [
    "ProgramAdministrator",
    "SubrecipientCoordinator",
    "StaffAppraiser",
    "ReviewAppraiser",
    "RelocationSpecialist",
    "ComplianceMonitor",
]
ALL_ROLES = list(ROLES)

# Enumerations
GRANT_PROGRAMS = ["HMGP", "FMA", "BRIC"]
PROJECT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "CLOSEOUT_PENDING", "CLOSED_OUT", "DENIED"]
ANALYSIS_METHODS = ["FEMA_BCA_TOOLKIT", "PRE_CALCULATED_BENEFIT"]
HAZARD_TYPES = ["RIVERINE_FLOOD", "COASTAL_SURGE", "WILDFIRE", "LANDSLIDE"]
SFHA_ZONES = ["AE", "VE", "A", "X"]
BCA_STATUSES = ["SUBMITTED", "VALIDATED", "REJECTED"]
OCCUPANCY_TYPES = ["OWNER_OCCUPIED", "TENANT_OCCUPIED", "VACANT"]
STRUCTURE_TYPES = ["SINGLE_FAMILY", "MULTI_FAMILY", "MANUFACTURED_HOME", "NONE"]
PRE_EVENT_VALUE_BASES = ["ASSESSOR_ROLL", "PRE_EVENT_APPRAISAL", "MARKET_STUDY"]
PARTICIPATION_STATUSES = ["NOT_CONTACTED", "INTERESTED", "VOLUNTARY_CONFIRMED", "DECLINED", "WITHDRAWN"]
ACQUISITION_STATUSES = [
    "NOT_STARTED", "APPRAISAL_IN_PROGRESS", "VALUE_ESTABLISHED", "OFFER_OUTSTANDING",
    "OFFER_ACCEPTED", "CLOSED", "DEMOLISHED", "OPEN_SPACE_RECORDED", "ACQUISITION_CANCELLED",
]
PRE_CLOSING_ACQUISITION = [
    "NOT_STARTED", "APPRAISAL_IN_PROGRESS", "VALUE_ESTABLISHED", "OFFER_OUTSTANDING", "OFFER_ACCEPTED",
]
ACQUIRED_ACQUISITION = ["CLOSED", "DEMOLISHED", "OPEN_SPACE_RECORDED"]
APPRAISAL_TYPES = ["INITIAL", "REVIEW"]
VALUATION_BASES = ["PRE_EVENT", "POST_EVENT"]
APPRAISAL_STATUSES = ["DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION", "ACCEPTED", "REJECTED"]
BENEFIT_SOURCES = ["NFIP_CLAIM", "ICC", "PRIVATE_INSURANCE", "SBA_LOAN", "CDBG_DR"]
DOB_STATUSES = ["ACTIVE", "REVERSED"]
OFFER_BASES = ["PRE_EVENT_FMV", "POST_EVENT_FMV"]
OFFER_STATUSES = ["DRAFT", "PRESENTED", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN", "SUPERSEDED"]
DISPLACEE_TYPES = ["OWNER_OCCUPANT", "TENANT_90_DAY", "TENANT_UNDER_90_DAY", "BUSINESS"]
RHP_METHODS = ["COMPARABLE_DWELLING", "ACTUAL_REPLACEMENT"]
CASE_STATUSES = [
    "OPENED", "ELIGIBILITY_DETERMINED", "CLAIM_SUBMITTED", "CLAIM_PAID",
    "CLAIM_DENIED", "APPEALED", "CLAIM_DENIED_FINAL",
]
NON_TERMINAL_CASE_STATUSES = ["OPENED", "ELIGIBILITY_DETERMINED", "CLAIM_SUBMITTED", "CLAIM_DENIED", "APPEALED"]
CLOSING_STATUSES = ["SCHEDULED", "FUNDED", "RECORDED"]
CONTRACTOR_STATUSES = ["ACTIVE", "SUSPENDED"]
ASBESTOS_STATUSES = ["NOT_PERFORMED", "PERFORMED_POSITIVE", "ABATED", "CLEARED"]
WORK_ORDER_STATUSES = ["ISSUED", "UTILITY_HOLD", "READY", "IN_PROGRESS", "FAILED_INSPECTION", "COMPLETED"]
ACTIVE_WORK_ORDER_STATUSES = ["ISSUED", "UTILITY_HOLD", "READY", "IN_PROGRESS", "FAILED_INSPECTION"]
DISPOSAL_FACILITY_TYPES = ["LANDFILL", "RECYCLING", "COMBINED"]
UTILITY_TYPES = ["WATER", "ELECTRIC", "GAS", "SEWER"]
DISCONNECTION_STATUSES = ["PENDING", "CONFIRMED", "FAILED"]
RESTRICTION_STATUSES = ["RECORDED", "IN_COMPLIANCE", "VIOLATION_OPEN", "CURED", "TERMINATED"]
FINDINGS = ["COMPLIANT", "PROHIBITED_USE_OBSERVED"]
ENTRY_TYPES = ["LEASE_REVENUE", "SALVAGE_PROCEEDS", "EASEMENT_FEE", "DOB_RECOVERY", "EXPENDITURE"]
LEDGER_STATUSES = ["ACTIVE", "REVERSED"]

# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

projects = {}
bcas = {}
parcels = {}
adjacencies = {}
appraisals = {}
dob_records = {}
offers = {}
cases = {}
closings = {}
contractors = {}
work_orders = {}
disconnections = {}
restrictions = {}
inspections = {}
ledger = {}

TABLES = [projects, bcas, parcels, adjacencies, appraisals, dob_records, offers,
          cases, closings, contractors, work_orders, disconnections, restrictions,
          inspections, ledger]

# --------------------------------------------------------------------------
# Field ordering for serialisation
# --------------------------------------------------------------------------

FIELD_ORDER = {
    "MitigationProject": [
        "id", "project_code", "grant_program", "disaster_declaration_number", "subrecipient_name",
        "cost_share_federal_pct", "total_federal_share_cap_cents", "period_of_performance_end_date",
        "status", "validated_bcr", "validated_bca_method", "validated_by_user_id",
        "federal_obligated_cents", "program_income_balance_cents", "protected_open_space_acres",
        "participating_parcel_count", "holdout_parcel_count", "contiguous_open_space_parcel_count",
        "largest_component_parcel_ids", "neighborhood_viability_ratio", "viability_status",
        "created_at", "updated_at", "version",
    ],
    "BenefitCostAnalysis": [
        "id", "project_id", "analysis_method", "hazard_type", "sfha_zone", "repetitive_loss_flag",
        "annualized_loss_avoided_cents", "project_useful_life_years", "discount_rate_pct",
        "mitigation_cost_cents", "pv_annuity_factor", "npv_benefits_cents", "bcr",
        "validated_by_user_id", "status", "created_at", "updated_at", "version",
    ],
    "Parcel": [
        "id", "project_id", "apn", "site_address", "acreage", "occupancy_type", "structure_type",
        "substantial_damage_pct", "pre_event_fmv_cents", "pre_event_value_basis",
        "pre_event_value_determined_at", "voluntary_acknowledgement_signed_on",
        "participation_status", "acquisition_status", "dob_deduction_total_cents",
        "created_at", "updated_at", "version",
    ],
    "ParcelAdjacency": [
        "id", "project_id", "parcel_a_id", "parcel_b_id", "shared_boundary_feet", "created_at",
    ],
    "Appraisal": [
        "id", "parcel_id", "reviewed_appraisal_id", "appraisal_type", "valuation_basis",
        "appraiser_user_id", "appraiser_license_no", "effective_date", "validity_end_date",
        "indicated_value_cents", "revision_count", "status", "created_at", "updated_at", "version",
    ],
    "DuplicationOfBenefitsRecord": [
        "id", "parcel_id", "benefit_source", "amount_cents", "repair_documented_cents",
        "deductible_cents", "received_on", "status", "reversal_reason",
        "created_at", "updated_at", "version",
    ],
    "PurchaseOffer": [
        "id", "parcel_id", "source_appraisal_id", "offer_basis", "base_value_cents",
        "dob_deduction_cents", "pre_incentive_net_cents", "incentive_cents", "net_offer_cents",
        "presented_at", "expires_at", "withdrawal_reason", "superseded_by_offer_id", "status",
        "expected_parcel_version", "created_at", "updated_at", "version",
    ],
    "RelocationCase": [
        "id", "parcel_id", "displacee_type", "household_reference", "acquisition_price_cents",
        "comparable_dwelling_price_cents", "actual_purchase_price_cents", "current_rent_cents",
        "current_utility_cents", "comparable_rent_cents", "comparable_utility_cents",
        "monthly_gross_income_cents", "rhp_method", "rental_assistance_start_date",
        "rental_assistance_months", "rental_assistance_end_date",
        "replacement_housing_payment_cents", "rental_assistance_cents", "moving_expense_cents",
        "total_relocation_benefit_cents", "denial_reason", "appeal_basis", "appeal_count",
        "status", "created_at", "updated_at", "version",
    ],
    "ClosingRecord": [
        "id", "parcel_id", "accepted_offer_id", "scheduled_closing_date", "purchase_price_cents",
        "settlement_cost_cents", "funded_at", "funded_by_user_id", "recording_reference",
        "recorded_at", "status", "created_at", "updated_at", "version",
    ],
    "DemolitionContractor": [
        "id", "name", "license_no", "asbestos_certified", "max_concurrent_work_orders",
        "status", "active_work_order_count", "created_at", "updated_at", "version",
    ],
    "DemolitionWorkOrder": [
        "id", "parcel_id", "contractor_id", "asbestos_survey_status", "scheduled_start",
        "scheduled_end", "buffered_start", "buffered_end", "required_utility_types",
        "confirmed_utility_types", "total_debris_tons", "recycled_tons", "diversion_pct",
        "disposal_manifest_no", "disposal_facility_type", "failed_inspection_count", "status",
        "created_at", "updated_at", "version",
    ],
    "UtilityDisconnection": [
        "id", "work_order_id", "utility_type", "provider_name", "confirmation_reference",
        "resolved_at", "failed_attempt_count", "status", "created_at", "updated_at", "version",
    ],
    "DeedRestriction": [
        "id", "parcel_id", "closing_record_id", "restriction_type", "prohibited_uses",
        "recorded_on", "monitoring_interval_months", "next_monitoring_due_date",
        "corrective_deadline_date", "open_violation_code", "violation_reported_by_user_id",
        "cured_on", "maintenance_responsible_party", "termination_authorization_reference",
        "status", "created_at", "updated_at", "version",
    ],
    "MonitoringInspection": [
        "id", "deed_restriction_id", "inspection_date", "finding", "prohibited_use_code",
        "inspector_user_id", "narrative", "created_at",
    ],
    "ProgramIncomeLedgerEntry": [
        "id", "project_id", "applied_to_parcel_id", "entry_type", "amount_cents",
        "federal_share_cents", "posted_on", "reverses_entry_id", "status",
        "expected_project_version", "created_at",
    ],
}


def new_record(kind, fields, versioned=True):
    rec = {"_kind": kind, "_seq": next_seq()}
    rec["id"] = new_id()
    rec.update(fields)
    now = fmt_dt(clock_now())
    rec["created_at"] = now
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = fmt_dt(clock_now())
    rec["version"] = rec.get("version", 0) + 1


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def by_created(records):
    return sorted(records, key=sort_key)


def serialize(rec):
    order = FIELD_ORDER.get(rec.get("_kind"), [])
    out = {}
    for name in order:
        if name in rec:
            out[name] = rec[name]
    for name, value in rec.items():
        if name.startswith("_") or name in out:
            continue
        out[name] = value
    return out
