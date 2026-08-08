"""Global constant register -- every threshold, window, ceiling, interval, fee,
rate and band boundary used anywhere in this implementation.

Values are taken verbatim from SCAFFOLD.yaml `constants` and PRD sections 2/3.
"""
from decimal import Decimal

D = Decimal

# --- logical clock -----------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00.000Z"

# --- impression / scan quality bands (integer score 0..100) ------------------
IMPRESSION_ACCEPT_MIN = 85
IMPRESSION_PROVISIONAL_MIN = 70
IMPRESSION_SCORE_MIN = 0
IMPRESSION_SCORE_MAX = 100
IMPRESSION_RETAKE_CEILING = 3

# --- try-in milestone --------------------------------------------------------
TRYIN_ADJUST_CEILING = 2

# --- lab coordination --------------------------------------------------------
LAB_STANDARD_TURNAROUND_DAYS = 10
LAB_RUSH_TURNAROUND_DAYS = 4
LAB_RUSH_FEE_BASE = D("120.00")
LAB_RUSH_FEE_PER_UNIT = D("35.00")
LAB_SHELF_LIFE_DAYS = 45
LAB_QC_RESEND_CEILING = 2
LAB_FAULT_CREDIT_RATE = D("0.60")
LAB_DEFAULT_INVOICE_AMOUNT = D("450.00")
LAB_DEFAULT_BENCH_LINE_COUNT = 3
LAB_BENCH_LINE_COUNT_MIN = 1
LAB_BENCH_LINE_COUNT_MAX = 10
ARCH_TURNAROUND_BUFFER_HOURS = 24

# --- warranty / replacement --------------------------------------------------
WARRANTY_WINDOW_DAYS = 365
REPLACEMENT_FREQUENCY_MONTHS = 60

# --- included post-delivery adjustment allowance -----------------------------
ADJUSTMENT_ALLOWANCE_COUNT = 4
ADJUSTMENT_ALLOWANCE_WINDOW_DAYS = 90
ADJUSTMENT_CHARGEABLE_FEE = D("85.00")

# --- fee schedule per delivered arch, by prosthesis_type ---------------------
PROSTHESIS_TYPES = [
    "COMPLETE_DENTURE",
    "IMMEDIATE_DENTURE",
    "CAST_PARTIAL",
    "FLEXIBLE_PARTIAL",
    "OVERDENTURE",
    "IMPLANT_RETAINED_OVERDENTURE",
]

FEE_BY_TYPE = {
    "COMPLETE_DENTURE": D("1800.00"),
    "IMMEDIATE_DENTURE": D("2100.00"),
    "CAST_PARTIAL": D("1650.00"),
    "FLEXIBLE_PARTIAL": D("1200.00"),
    "OVERDENTURE": D("2400.00"),
    "IMPLANT_RETAINED_OVERDENTURE": D("3600.00"),
}

# --- post-delivery service fees ---------------------------------------------
SERVICE_FEE = {
    "ADJUSTMENT": D("85.00"),
    "SOFT_RELINE_CHAIRSIDE": D("260.00"),
    "HARD_RELINE_LAB": D("420.00"),
    "REBASE": D("590.00"),
    "REPAIR": D("180.00"),
    "TOOTH_ADDITION": D("155.00"),
    "CLASP_ADDITION": D("195.00"),
}
FEE_REPAIR = D("180.00")

# --- post-delivery service frequency limits (whole months; 0 = no limit) -----
SERVICE_FREQ_MONTHS = {
    "ADJUSTMENT": 0,
    "SOFT_RELINE_CHAIRSIDE": 6,
    "HARD_RELINE_LAB": 24,
    "REBASE": 36,
    "REPAIR": 0,
    "TOOTH_ADDITION": 0,
    "CLASP_ADDITION": 0,
}

# --- immediate-denture mandatory reline --------------------------------------
IMMEDIATE_DENTURE_RELINE_DUE_DAYS = 180

# --- recall intervals per prosthesis_type (days from delivered_at) -----------
RECALL_INTERVAL_DAYS = {
    "COMPLETE_DENTURE": 365,
    "IMMEDIATE_DENTURE": 90,
    "CAST_PARTIAL": 365,
    "FLEXIBLE_PARTIAL": 365,
    "OVERDENTURE": 180,
    "IMPLANT_RETAINED_OVERDENTURE": 180,
}
RECALL_OVERDUE_GRACE_DAYS = 30

# --- remake ------------------------------------------------------------------
REMAKE_CEILING_PER_ARCH = 2

# --- insurance ---------------------------------------------------------------
COVERAGE_DEFAULT_ANNUAL_MAXIMUM = D("1500.00")
COVERAGE_DEFAULT_COINSURANCE_MAJOR_RATE = D("0.50")
COVERAGE_DEFAULT_WAITING_PERIOD_DAYS = 180
COVERAGE_DEFAULT_REPLACEMENT_FREQUENCY_MONTHS = 60
PREDETERMINATION_REQUIRED_MIN_FEE = D("1500.00")
PREDETERMINATION_VALIDITY_DAYS = 180

ALTERNATE_BENEFIT_MAP = {
    "IMPLANT_RETAINED_OVERDENTURE": "COMPLETE_DENTURE",
    "OVERDENTURE": "COMPLETE_DENTURE",
    "CAST_PARTIAL": "FLEXIBLE_PARTIAL",
}

# --- payment plan ------------------------------------------------------------
PAYMENT_PLAN_MIN_INSTALLMENTS = 2
PAYMENT_PLAN_MAX_INSTALLMENTS = 12
PAYMENT_PLAN_MIN_DOWN_RATE = D("0.20")
PAYMENT_PLAN_DELINQUENCY_GRACE_DAYS = 10
PAYMENT_PLAN_DEFAULT_MISSED_COUNT = 3
PAYMENT_FREQUENCY_DAYS = {"MONTHLY": 30, "BIWEEKLY": 14}

# --- prompt-pay discount tiers (keyed on PRE-discount responsibility) --------
PROMPT_PAY_TIER_2_MIN = D("2500.00")
PROMPT_PAY_TIER_1_MIN = D("1000.00")
PROMPT_PAY_TIER_2_RATE = D("0.05")
PROMPT_PAY_TIER_1_RATE = D("0.03")
PROMPT_PAY_TIER_0_RATE = D("0.00")

# --- required milestone sequence per prosthesis_type -------------------------
MILESTONES_BY_TYPE = {
    "COMPLETE_DENTURE": ["WAX", "FINISH"],
    "IMMEDIATE_DENTURE": [],
    "CAST_PARTIAL": ["FRAMEWORK", "WAX", "FINISH"],
    "FLEXIBLE_PARTIAL": ["WAX"],
    "OVERDENTURE": ["WAX", "FINISH"],
    "IMPLANT_RETAINED_OVERDENTURE": ["FRAMEWORK", "FINISH"],
}

# --- service routing sets ----------------------------------------------------
CHAIRSIDE_SERVICE_TYPES = ["ADJUSTMENT", "SOFT_RELINE_CHAIRSIDE", "REPAIR"]
LAB_SERVICE_TYPES = ["HARD_RELINE_LAB", "REBASE", "TOOTH_ADDITION", "CLASP_ADDITION"]
PARTIAL_ONLY_SERVICE_TYPES = ["CLASP_ADDITION"]
PARTIAL_PROSTHESIS_TYPES = ["CAST_PARTIAL", "FLEXIBLE_PARTIAL"]
REBASE_INELIGIBLE_PROSTHESIS_TYPES = ["FLEXIBLE_PARTIAL"]

LAB_SERVICE_PURPOSE = {
    "HARD_RELINE_LAB": "RELINE",
    "REBASE": "REBASE",
    "TOOTH_ADDITION": "ADDITION",
    "CLASP_ADDITION": "ADDITION",
}

# --- enum member sets --------------------------------------------------------
ROLES = [
    "Prosthodontist",
    "ClinicalDirector",
    "LabTechnician",
    "FrontOffice",
    "Patient",
    "PlatformAdmin",
]

ENUMS = {
    "prosthesis_type": PROSTHESIS_TYPES,
    "arch_position": ["MAXILLARY", "MANDIBULAR"],
    "capture_method": ["PHYSICAL_IMPRESSION", "DIGITAL_SCAN"],
    "milestone_kind": ["WAX", "FRAMEWORK", "FINISH"],
    "decision": ["APPROVE", "ADJUST", "RESUBMIT", "REJECT"],
    "turnaround_class": ["STANDARD", "RUSH"],
    "purpose": ["FABRICATION", "RELINE", "REBASE", "REPAIR", "ADDITION", "REMAKE"],
    "qc_result": ["PASS", "FAIL"],
    "recall_outcome": ["NO_ACTION", "RELINE_INDICATED", "REMAKE_EVALUATION"],
    "service_type": [
        "ADJUSTMENT",
        "SOFT_RELINE_CHAIRSIDE",
        "HARD_RELINE_LAB",
        "REBASE",
        "REPAIR",
        "TOOTH_ADDITION",
        "CLASP_ADDITION",
    ],
    "fault_verdict": ["CLINIC_FAULT", "LAB_FAULT", "PATIENT_FAULT", "INDETERMINATE"],
    "resolved_verdict": ["CLINIC_FAULT", "LAB_FAULT", "PATIENT_FAULT"],
    "reason_code": [
        "TRYIN_REJECTED",
        "FIT_FAILURE",
        "LAB_DEFECT",
        "PATIENT_DISSATISFACTION",
        "RECALL_EVALUATION",
    ],
    "rank": ["PRIMARY", "SECONDARY"],
    "cob_convention": ["STANDARD", "NON_DUPLICATION"],
    "determination": ["APPROVED", "ALTERNATE_BENEFIT", "DENIED"],
    "adjudication_outcome": ["PAID", "DENIED"],
    "frequency": ["MONTHLY", "BIWEEKLY"],
}

# Status enum member sets, used to validate enum-valued list filters
# (those route to ERR_VALIDATION, never to ERR_INVALID_ENUM -- PRD rung 8).
STATUS_ENUMS = {
    "case_status": [
        "INTAKE",
        "EXAM_COMPLETE",
        "IN_FABRICATION",
        "DELIVERED",
        "CLOSED",
        "CANCELLED",
    ],
    "arch_status": [
        "PLANNED",
        "IMPRESSION_PENDING",
        "MILESTONE_PENDING",
        "LAB_FABRICATION",
        "READY_FOR_DELIVERY",
        "DELIVERED",
        "REMAKE_PENDING",
        "ARCH_CLOSED",
        "ARCH_ABANDONED",
    ],
    "quality_status": [
        "PENDING_REVIEW",
        "ACCEPTED",
        "PROVISIONAL_ACCEPTED",
        "REJECTED",
        "SUPERSEDED",
    ],
    "approval_status": [
        "PENDING_APPROVAL",
        "ADJUST_REQUESTED",
        "APPROVED",
        "REJECTED_FOR_REMAKE",
        "CANCELLED",
    ],
    "lab_status": [
        "DRAFT",
        "DISPATCHED",
        "RETURNED",
        "QC_PASSED",
        "QC_FAILED",
        "RESENT",
        "EXPIRED",
        "CANCELLED",
    ],
    "warranty_status": [
        "IN_WARRANTY",
        "WARRANTY_CONSUMED",
        "WARRANTY_EXPIRED",
        "WARRANTY_VOIDED",
    ],
    "recall_status": [
        "RECALL_SCHEDULED",
        "RECALL_DUE",
        "RECALL_OVERDUE",
        "RECALL_COMPLETED",
        "RECALL_CLOSED_SUPERSEDED",
    ],
    "service_status": ["REQUESTED", "IN_CHAIR", "AT_LAB", "COMPLETED", "VOIDED"],
    "claim_status": [
        "SUBMITTED",
        "CLINICAL_REVIEW",
        "CLINIC_FAULT",
        "LAB_FAULT",
        "PATIENT_FAULT",
    ],
    "authorization_status": ["PENDING_APPROVAL", "APPROVED", "DENIED", "FINAL_DENIED"],
    "determination_status": [
        "SUBMITTED",
        "APPROVED",
        "DENIED",
        "ALTERNATE_BENEFIT",
        "EXPIRED",
    ],
    "adjudication_status": [
        "DRAFT",
        "SUBMITTED_PRIMARY",
        "PRIMARY_PAID",
        "SUBMITTED_SECONDARY",
        "SECONDARY_PAID",
        "CLOSED",
        "DENIED",
        "REVERSED",
    ],
    "plan_status": ["ACTIVE", "DELINQUENT", "DEFAULTED", "PAID_OFF", "SUPERSEDED"],
    "installment_status": ["SCHEDULED", "MISSED", "PAID", "WAIVED"],
}

# --- terminal state sets per axis -------------------------------------------
TERMINAL = {
    "case_status": {"CLOSED", "CANCELLED"},
    "arch_status": {"ARCH_CLOSED", "ARCH_ABANDONED"},
    "quality_status": {"ACCEPTED", "SUPERSEDED"},
    "approval_status": {"APPROVED", "REJECTED_FOR_REMAKE", "CANCELLED"},
    "lab_status": {"QC_PASSED", "EXPIRED", "CANCELLED"},
    "warranty_status": {"WARRANTY_EXPIRED", "WARRANTY_VOIDED"},
    "recall_status": {"RECALL_COMPLETED", "RECALL_CLOSED_SUPERSEDED"},
    "service_status": {"VOIDED"},
    "claim_status": {"CLINIC_FAULT", "LAB_FAULT", "PATIENT_FAULT"},
    "authorization_status": {"APPROVED", "DENIED", "FINAL_DENIED"},
    "determination_status": {"DENIED", "EXPIRED"},
    "adjudication_status": {"DENIED", "REVERSED"},
    "plan_status": {"PAID_OFF", "SUPERSEDED"},
    "installment_status": {"WAIVED"},
}

# --- lab-case status sets that count as "occupying" --------------------------
OCCUPYING_LAB_STATUSES = {"DISPATCHED", "RETURNED", "QC_FAILED", "RESENT"}
CANCELLABLE_LAB_STATUSES = {"DRAFT", "DISPATCHED", "RETURNED", "QC_FAILED", "RESENT"}
RUSH_COUNTING_LAB_STATUSES = {
    "DISPATCHED",
    "RETURNED",
    "QC_PASSED",
    "QC_FAILED",
    "RESENT",
    "EXPIRED",
}

# --- pagination --------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- misc bounds -------------------------------------------------------------
UNIT_COUNT_MIN = 1
UNIT_COUNT_MAX = 32
