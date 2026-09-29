"""Entity shapes and state vocabularies declared by the PRD.

Two things live here:

* ``*_FIELDS`` tuples -- the field list each resource representation must
  expose, so a test can assert the shape of a row without spelling out a dozen
  key names inline.
* State vocabularies -- the exact set of state names each lifecycle may report.

Most resources carry the four system fields ``id``, ``created_at``,
``updated_at`` and ``version``.  Three resources are append-only records that
are never rewritten, so the PRD gives them ``id`` and ``created_at`` only:
ZoneEvaluation, HardeningFinding and CostRecoveryPayment.
"""

# ---------------------------------------------------------------------------
# System field groups
# ---------------------------------------------------------------------------

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# Append-only records: no updated_at and no version.
APPEND_ONLY_FIELDS = ("id", "created_at")

APPEND_ONLY_RESOURCES = ("ZoneEvaluation", "HardeningFinding", "CostRecoveryPayment")

# ---------------------------------------------------------------------------
# Business field inventories
# ---------------------------------------------------------------------------

INSPECTION_CYCLE_FIELDS = (
    "season_year",
    "status",
    "notice_lead_days",
    "invoice_due_days",
    "epoch",
    "activated_at_utc",
    "closed_at_utc",
)

COMMUNITY_FIELDS = (
    "name",
    "organizer_name",
    "target_certification_year",
    "status",
    "parcels_outreached_count",
    "compliance_rate_pct",
    "certified_at_utc",
    "lapse_count",
)

PARCEL_FIELDS = (
    "apn",
    "owner_name",
    "owner_email",
    "situs_address",
    "community_id",
    "structure_present",
    "roof_class",
    "vegetation_type",
    "slope_pct",
    "lot_area_sqft",
    "hazard_zone",
    "access_constraint",
    "owner_hardship_flag",
    "exemption_flag",
    "risk_score",
    "risk_score_basis",
    "risk_class",
    "compliance_status",
    "open_violation_count",
    "inspection_priority_rank",
    "last_passed_inspection_at_utc",
    "structure_survival_outcome",
    "survival_incident_name",
    "survival_incident_date_utc",
)

INSPECTOR_FIELDS = (
    "full_name",
    "certification_level",
    "status",
    "assigned_open_count",
)

CONTRACTOR_FIELDS = (
    "business_name",
    "hourly_rate_cents",
    "mobilization_fee_cents",
    "license_status",
    "insurance_expiry_utc",
    "max_daily_orders",
    "committed_crew_hours",
    "completed_crew_hours",
)

INSPECTION_FIELDS = (
    "parcel_id",
    "cycle_id",
    "inspector_id",
    "inspection_type",
    "scheduled_start_utc",
    "scheduled_end_utc",
    "access_arrangement",
    "status",
    "result",
    "notice_method",
    "notice_sent_at_utc",
    "access_denial_count",
    "measured_veg_points",
    "hardening_credit_points",
    "max_deficiency_severity",
    "completed_at_utc",
)

ZONE_EVALUATION_FIELDS = (
    "inspection_id",
    "zone",
    "measured_clearance_ft",
    "ladder_fuel_present",
    "required_clearance_ft",
    "deficit_ft",
    "deficit_ratio",
    "deficiency_severity",
    "points",
)

HARDENING_FINDING_FIELDS = (
    "inspection_id",
    "item_code",
    "status",
    "credit_points",
)

VIOLATION_NOTICE_FIELDS = (
    "parcel_id",
    "inspection_id",
    "supersedes_notice_id",
    "notice_method",
    "severity",
    "status",
    "issued_at_utc",
    "delivered_at_utc",
    "compliance_days",
    "deadline_utc",
    "extension_count",
    "cleared_at_utc",
    "void_reason",
)

ABATEMENT_ORDER_FIELDS = (
    "violation_notice_id",
    "contractor_id",
    "verified_by_inspector_id",
    "status",
    "estimated_cost_cents",
    "crew_hours",
    "work_start_utc",
    "work_end_utc",
    "actual_crew_hours",
    "green_waste_tons",
    "labor_line_cents",
    "disposal_line_cents",
    "mobilization_line_cents",
    "admin_overhead_cents",
    "pre_subsidy_total_cents",
    "subsidy_pct",
    "district_subsidy_cents",
    "total_recoverable_cents",
    "recovery_basis",
    "paid_cents",
    "lien_amount_cents",
    "invoice_due_utc",
    "cancel_reason",
)

COST_RECOVERY_PAYMENT_FIELDS = (
    "abatement_order_id",
    "amount_cents",
    "method",
    "allocation",
    "outstanding_after_cents",
)

SUPPORT_PROGRAM_FIELDS = (
    "cycle_id",
    "program_type",
    "budget_total_cents",
    "budget_remaining_cents",
    "capacity_slots",
    "reserved_slots",
    "service_window_start_utc",
    "service_window_end_utc",
)

SUPPORT_ENROLLMENT_FIELDS = (
    "support_program_id",
    "parcel_id",
    "vendor_invoice_cents",
    "status",
    "award_before_bonus_cents",
    "bonus_pct",
    "hardship_bonus_cents",
    "award_cents",
    "reserved_amount_cents",
    "reimbursed_cents",
    "waitlist_position",
)

COMPLIANCE_CERTIFICATE_FIELDS = (
    "parcel_id",
    "requester_kind",
    "transaction_reference",
    "status",
    "decision_note",
    "issued_at_utc",
    "expires_at_utc",
    "snapshot_risk_class",
    "snapshot_compliance_status",
    "revoked_at_utc",
)

DISTRICT_METRICS_FIELDS = (
    "eligible_parcel_count",
    "compliant_parcel_count",
    "compliance_rate_pct",
    "survived_compliant_pct",
    "survived_noncompliant_pct",
    "survival_delta_pp",
    "epoch",
)

COMMUNITY_METRICS_FIELDS = (
    "eligible_parcel_count",
    "compliant_parcel_count",
    "compliance_rate_pct",
    "member_parcel_count",
)

# ---------------------------------------------------------------------------
# State vocabularies
# ---------------------------------------------------------------------------

CYCLE_STATES = ("PLANNING", "ACTIVE", "CLOSED")

COMMUNITY_STATES = ("ORGANIZING", "SUBMITTED", "CERTIFIED", "DEFERRED", "LAPSED")

PARCEL_COMPLIANCE_STATES = (
    "PENDING_INSPECTION",
    "COMPLIANT",
    "NON_COMPLIANT",
    "ABATEMENT_PENDING",
    "EXEMPT",
)

INSPECTION_STATES = (
    "SCHEDULED",
    "NOTICED",
    "ACCESS_DENIED",
    "COMPLETED",
    "CANCELLED",
    "ABANDONED",
)

NOTICE_STATES = (
    "ISSUED",
    "EXTENDED",
    "OVERDUE",
    "ABATEMENT_AUTHORIZED",
    "CLEARED",
    "VOIDED",
)

ABATEMENT_ORDER_STATES = (
    "AUTHORIZED",
    "AWARDED",
    "WORK_COMPLETE",
    "INVOICED",
    "PAID",
    "LIEN_FILED",
    "CANCELLED",
)

ENROLLMENT_STATES = (
    "REQUESTED",
    "APPROVED",
    "WAITLISTED",
    "COMPLETED",
    "NO_SHOW",
    "REIMBURSED",
    "CANCELLED",
)

CERTIFICATE_STATES = ("REQUESTED", "ISSUED", "DENIED", "REVOKED")

# ---------------------------------------------------------------------------
# Enumerated inputs
# ---------------------------------------------------------------------------

ROOF_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C", "NONE")
VEGETATION_TYPES = ("IRRIGATED_LANDSCAPE", "GRASS", "BRUSH", "MIXED_CONIFER")
HAZARD_ZONES = ("MODERATE", "HIGH", "VERY_HIGH")
ACCESS_CONSTRAINTS = ("NONE", "GATED", "LOCKED_GATE", "DOG_ON_SITE")
RISK_CLASSES = ("LOW", "MODERATE", "HIGH", "EXTREME")
ZONES = ("ZONE_0_EMBER", "ZONE_1", "ZONE_2")
SEVERITIES = ("NONE", "MINOR", "MAJOR", "CRITICAL")
NOTICE_METHODS = ("IN_PERSON", "CERTIFIED_MAIL", "EMAIL")
INSPECTION_TYPES = ("INITIAL", "REINSPECTION", "COMPLAINT")
ACCESS_ARRANGEMENTS = ("EXTERIOR_ONLY", "OWNER_PRESENT", "GATE_CODE")
CERTIFICATION_LEVELS = ("BASIC", "ADVANCED", "WUI_SPECIALIST")
INSPECTOR_STATUSES = ("ACTIVE", "SUSPENDED")
LICENSE_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED")
HARDENING_ITEM_CODES = (
    "EAVE_VENTS",
    "ROOF_ASSEMBLY",
    "DECK_UNDERSIDE",
    "WINDOW_GLAZING",
    "SIDING",
    "GUTTER_DEBRIS",
)
HARDENING_STATUSES = ("COMPLIANT", "DEFICIENT", "NOT_APPLICABLE")
PAYMENT_METHODS = ("CHECK", "CARD", "ACH", "WRITE_OFF")
PROGRAM_TYPES = ("CHIPPER_DAY", "CURBSIDE_COLLECTION", "COST_SHARE_GRANT")
REQUESTER_KINDS = ("INSURANCE", "REAL_ESTATE", "LENDER")
INSPECTION_RESULTS = ("PASS", "FAIL")
SURVIVAL_OUTCOMES = ("SURVIVED", "DESTROYED")
