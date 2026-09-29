"""Enumerations and tunable constants (PRD sections 1, 3 and 6)."""

# ------------------------------------------------------------------- cycles

CYCLE_STATUSES = (
    "DRAFT",
    "OPEN",
    "CLOSED",
    "PANEL_REVIEW",
    "BOARD_REVIEW",
    "AWARDED",
    "CLOSED_OUT",
    "CANCELLED",
)
CYCLE_TRANSITIONS = {
    "DRAFT": ("OPEN", "CANCELLED"),
    "OPEN": ("CLOSED", "CANCELLED"),
    "CLOSED": ("PANEL_REVIEW",),
    "PANEL_REVIEW": ("BOARD_REVIEW",),
    "BOARD_REVIEW": ("AWARDED",),
    "AWARDED": ("CLOSED_OUT",),
    "CLOSED_OUT": (),
    "CANCELLED": (),
}
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
PRORATION_POLICIES = ("PRORATE", "SKIP_TO_ALTERNATE")

# Statuses during which the operating reserve is withheld from the budget.
RESERVE_STATUSES = ("DRAFT", "OPEN", "CLOSED", "PANEL_REVIEW", "BOARD_REVIEW")

# --------------------------------------------------------------- disciplines

DISCIPLINE_CODES = (
    "LITERARY_ARTS",
    "VISUAL_ARTS",
    "MEDIA_ARTS",
    "PERFORMING_ARTS",
    "TRADITIONAL_ARTS",
)
REGIONS = ("NORTH", "CENTRAL", "SOUTH", "COASTAL", "TRIBAL")
MEDIA = ("MANUSCRIPT_PAGES", "AUDIO", "VIDEO", "IMAGE_SET")
TIMED_MEDIA = ("AUDIO", "VIDEO")

# ------------------------------------------------------------------- artists

TIN_STATUSES = ("ON_FILE", "MISSING", "INVALID")
STANDINGS = ("GOOD_STANDING", "REPORT_DELINQUENT", "DEBARRED")
DEBAR_REASONS = ("FRAUD", "REPORT_ABANDONED", "FUNDS_MISUSE")

# -------------------------------------------------------------- applications

APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "ELIGIBLE",
    "INELIGIBLE",
    "UNDER_REVIEW",
    "SCORED",
    "RECOMMENDED",
    "NOT_RECOMMENDED",
    "AWARDED",
    "NOT_AWARDED",
    "WITHDRAWN",
)
ANONYMITY_STATUSES = ("SEALED", "BREACHED", "REDACTED", "UNSEALED")
INELIGIBILITY_REASONS = ("RESIDENCY_DURATION", "PRIOR_AWARD_BLACKOUT", "ENROLLED_STUDENT")
ELIGIBILITY_DETERMINATIONS = ("ELIGIBLE", "INELIGIBLE")

# Applications counted by DisciplineCategory.eligible_application_count.
ELIGIBLE_POOL_STATUSES = (
    "ELIGIBLE",
    "UNDER_REVIEW",
    "SCORED",
    "RECOMMENDED",
    "NOT_RECOMMENDED",
    "AWARDED",
    "NOT_AWARDED",
)
# Applications excluded from the diversity pool.
DIVERSITY_EXCLUDED_STATUSES = ("DRAFT", "WITHDRAWN", "INELIGIBLE")

# -------------------------------------------------------------- work samples

WORK_SAMPLE_STATUSES = ("PENDING_SCREEN", "CLEARED", "FLAGGED", "REDACTED", "REJECTED")
WORK_SAMPLE_DISPOSITIONS = ("CLEARED", "FLAGGED_IDENTIFYING", "REJECTED")
# Samples that count towards Application.work_sample_count.
COUNTED_SAMPLE_STATUSES = ("PENDING_SCREEN", "CLEARED", "REDACTED")

# -------------------------------------------------------------------- panels

PANEL_STATUSES = (
    "FORMING",
    "CHARTERED",
    "SCORING",
    "DELIBERATING",
    "SLATE_SUBMITTED",
    "DISSOLVED",
)
PANELIST_STATUSES = ("NOMINATED", "SEATED", "RECUSED", "RESIGNED")
# A recusal deliberately keeps the seat; resignation is the only release.
OCCUPYING_PANELIST_STATUSES = ("SEATED", "RECUSED")

# ----------------------------------------------------------------- conflicts

RELATIONSHIP_TYPES = (
    "TEACHER_STUDENT",
    "IMMEDIATE_FAMILY",
    "CO_AUTHOR",
    "SAME_INSTITUTION",
    "FINANCIAL_INTEREST",
    "PRIOR_MENTOR",
)
MANDATORY_RELATIONSHIPS = ("TEACHER_STUDENT", "IMMEDIATE_FAMILY", "FINANCIAL_INTEREST")
CONFLICT_SEVERITIES = ("MANDATORY_BLOCK", "DISCRETIONARY")
CONFLICT_STATUSES = ("DECLARED", "WAIVED", "BLOCKING")
CONFLICT_DISPOSITIONS = ("BLOCKING", "WAIVED")

# ------------------------------------------------------------------- reviews

REVIEW_STATUSES = ("DRAFT", "SUBMITTED", "INVALIDATED", "SUPERSEDED")
INVALIDATION_REASONS = ("BLOCKING_CONFLICT", "ANONYMITY_BREACH", "APPEAL_REMEDY")
SCORE_FIELDS = ("artistic_excellence", "work_sample_quality", "career_impact", "public_value")

# --------------------------------------------------------------------- slots

SLOT_STATUSES = ("PROPOSED", "BOARD_APPROVED", "BOARD_STRUCK", "VOIDED")
SLOT_DISPOSED_STATUSES = ("BOARD_APPROVED", "BOARD_STRUCK", "VOIDED")
BOARD_ACTIONS = ("APPROVE", "STRIKE")
STRUCK_REASONS = ("BUDGET", "PROCEDURAL_DEFECT", "APPLICANT_INELIGIBLE")

# -------------------------------------------------------------------- awards

AWARD_STATUSES = (
    "OFFERED",
    "ACCEPTED",
    "ACTIVE",
    "COMPLETED",
    "DECLINED",
    "RESCINDED",
    "FORFEITED",
)
AWARD_TERMINAL_STATUSES = ("COMPLETED", "DECLINED", "RESCINDED", "FORFEITED")
# Award statuses that consume budget / discipline allocation.
AWARD_FUNDED_STATUSES = ("OFFERED", "ACCEPTED", "ACTIVE", "COMPLETED")
# Award statuses counted by Artist.active_award_count.
AWARD_ACTIVE_STATUSES = ("OFFERED", "ACCEPTED", "ACTIVE")
PAYMENT_STATUSES = ("UNPAID", "PARTIALLY_PAID", "FULLY_PAID")
REPORTING_STATUSES = ("NOT_DUE", "DUE", "RECEIVED", "ACCEPTED", "DELINQUENT")
RESCIND_REASONS = ("APPEAL_REMEDY", "INELIGIBILITY_DISCOVERED", "APPLICANT_REQUEST")
AGREEMENT_VERSION = "FELLOWSHIP-AGREEMENT-2027.1"
AWARD_COOLING_DAYS = 365

# -------------------------------------------------------------- installments

INSTALLMENT_STATUSES = ("SCHEDULED", "HELD", "RELEASED", "PAID", "VOIDED", "REVERSED")
# The live set used for the award ledger conservation identity.
INSTALLMENT_LIVE_STATUSES = ("SCHEDULED", "HELD", "RELEASED", "PAID")
INSTALLMENT_UNDISBURSED_STATUSES = ("SCHEDULED", "HELD", "RELEASED")
INSTALLMENT_RELEASE_PRIOR_OK = ("PAID", "RELEASED", "VOIDED", "REVERSED")
REVERSAL_REASONS = ("BANK_RETURN", "OVERPAYMENT", "FRAUD_HOLD")
HOLD_REASONS = ("REPORT_DELINQUENT", "ARTIST_DEBARRED")
TAX_BASES = ("ACCRUAL", "CASH")

# -------------------------------------------------------------- final report

FINAL_REPORT_STATUSES = ("SUBMITTED", "REVISION_REQUESTED", "ACCEPTED")
FINAL_REPORT_DECISIONS = ("ACCEPT", "REQUEST_REVISION")
MAX_REPORT_REVISIONS = 2

# ------------------------------------------------------------------- appeals

APPEAL_GROUNDS = (
    "ELIGIBILITY_DETERMINATION_ERROR",
    "CONFLICT_NOT_MANAGED",
    "ANONYMITY_BREACH",
    "SCORING_PROCEDURE_DEFECT",
    "PANEL_COMPOSITION_DEFECT",
    "SUBSTANTIVE_SCORE_DISAGREEMENT",
)
PROCEDURAL_GROUNDS = (
    "ELIGIBILITY_DETERMINATION_ERROR",
    "CONFLICT_NOT_MANAGED",
    "ANONYMITY_BREACH",
    "SCORING_PROCEDURE_DEFECT",
    "PANEL_COMPOSITION_DEFECT",
)
APPEAL_STATUSES = ("FILED", "SCREENED", "UPHELD", "DENIED")
APPEAL_DECISIONS = ("UPHOLD", "DENY")
REMEDY_CODES = ("REINSTATE_ELIGIBILITY", "RESCORE_BY_NEW_PANEL", "REISSUE_SLATE")
REMEDY_PERMITTED = {
    "ELIGIBILITY_DETERMINATION_ERROR": ("REINSTATE_ELIGIBILITY",),
    "CONFLICT_NOT_MANAGED": ("RESCORE_BY_NEW_PANEL",),
    "ANONYMITY_BREACH": ("RESCORE_BY_NEW_PANEL",),
    "SCORING_PROCEDURE_DEFECT": ("RESCORE_BY_NEW_PANEL",),
    "PANEL_COMPOSITION_DEFECT": ("RESCORE_BY_NEW_PANEL", "REISSUE_SLATE"),
    "SUBSTANTIVE_SCORE_DISAGREEMENT": (),
}

# ------------------------------------------------------------- 404 selectors

NOT_FOUND = {
    "cycles": "ERR_CYCLE_NOT_FOUND",
    "disciplines": "ERR_DISCIPLINE_CATEGORY_NOT_FOUND",
    "artists": "ERR_ARTIST_NOT_FOUND",
    "applications": "ERR_APPLICATION_NOT_FOUND",
    "work_samples": "ERR_WORK_SAMPLE_NOT_FOUND",
    "panels": "ERR_PANEL_NOT_FOUND",
    "panelists": "ERR_PANELIST_NOT_FOUND",
    "conflicts": "ERR_CONFLICT_NOT_FOUND",
    "reviews": "ERR_REVIEW_NOT_FOUND",
    "slots": "ERR_SLOT_NOT_FOUND",
    "awards": "ERR_AWARD_NOT_FOUND",
    "installments": "ERR_INSTALLMENT_NOT_FOUND",
    "final_reports": "ERR_FINAL_REPORT_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
}
