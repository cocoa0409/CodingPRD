"""Server-wide configuration constants for the Personal Injury Case API.

All values are read from SCAFFOLD.yaml / PRD.md. Do not invent new constants.
"""
from __future__ import annotations

import os

# ── Networking ─────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# ── Auth headers (PRD §2.1, SCAFFOLD §1.4 priorities 1-3) ──────────────────
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Roles recognised by the system (PRD §2.1).
ROLE_PARALEGAL = "Paralegal"
ROLE_ATTORNEY = "Attorney"
ROLE_MANAGING_PARTNER = "ManagingPartner"
ROLES = {ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER}

# ── Pagination (SCAFFOLD response_envelope.pagination_defaults) ────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Domain constants ───────────────────────────────────────────────────────
INCIDENT_TYPES = {
    "AUTO", "SLIP_FALL", "MEDICAL_MALPRACTICE",
    "PRODUCT_LIABILITY", "PREMISES", "DOG_BITE",
}

CASE_STATUSES = {
    "INTAKE", "RECORDS_PENDING", "READY_FOR_DEMAND",
    "DEMAND_SENT", "NEGOTIATING", "LITIGATION",
    "SETTLED", "TRIAL_AWARDED", "DISMISSED", "CLOSED",
}
TERMINAL_CASE_STATUSES = {"SETTLED", "TRIAL_AWARDED", "DISMISSED", "CLOSED"}
CASE_CLOSED_STATUSES = {"DISMISSED", "CLOSED"}

MEDICAL_REQUEST_STATUSES = {"DRAFT", "SENT", "RECEIVED", "REJECTED", "CANCELED"}
TERMINAL_MEDICAL_STATUSES = {"RECEIVED", "REJECTED", "CANCELED"}

DEMAND_STATUSES = {"DRAFT", "SENT", "RESPONDED", "SUPERSEDED", "WITHDRAWN"}
TERMINAL_DEMAND_STATUSES = {"RESPONDED", "SUPERSEDED", "WITHDRAWN"}

OFFER_STATUSES = {"PENDING", "ACCEPTED", "REJECTED", "COUNTERED", "EXPIRED", "WITHDRAWN"}
TERMINAL_OFFER_STATUSES = {"ACCEPTED", "REJECTED", "EXPIRED", "WITHDRAWN"}
OFFER_PARTIES = {"DEFENDANT", "PLAINTIFF"}

LIEN_TYPES_STATUTORY = {"MEDICARE", "MEDICAID", "ERISA", "CHILD_SUPPORT"}
LIEN_TYPES_NEGOTIABLE = {"PROVIDER_NEGOTIATED", "HOSPITAL_STATUTORY", "ATTORNEY_PRIOR_COUNSEL"}
LIEN_TYPES = LIEN_TYPES_STATUTORY | LIEN_TYPES_NEGOTIABLE
LIEN_STATUSES = {"ASSERTED", "NEGOTIATING", "REDUCED", "RESOLVED", "DISPUTED"}
TERMINAL_LIEN_STATUSES = {"RESOLVED", "DISPUTED"}

# Lien priority for disbursement waterfall (SCAFFOLD calc_net_disbursement).
LIEN_PRIORITY_TABLE = {
    "MEDICARE": 1,
    "MEDICAID": 2,
    "ERISA": 3,
    "CHILD_SUPPORT": 4,
    "HOSPITAL_STATUTORY": 5,
    "ATTORNEY_PRIOR_COUNSEL": 6,
    "PROVIDER_NEGOTIATED": 7,
}

COURT_EVENT_TYPES = {
    "COMPLAINT_FILED", "ANSWER_DUE", "DISCOVERY_DEADLINE",
    "MEDIATION", "MOTION_HEARING", "TRIAL", "JUDGMENT",
}
COURT_EVENT_STATUSES = {"SCHEDULED", "COMPLETED", "CONTINUED", "CANCELED"}
TERMINAL_COURT_EVENT_STATUSES = {"COMPLETED", "CANCELED"}

DAMAGES_METHODS = {"MULTIPLIER", "PER_DIEM"}

DISBURSEMENT_STRATEGIES = {"CHRONOLOGICAL_PRIORITY", "FORWARD_LOOKING_PRORATA"}

# ── Statute-of-limitations tables (SCAFFOLD calc_sol_deadline.constants) ──
SOL_TABLE: dict[tuple[str, str], int] = {
    ("CA", "AUTO"): 2,
    ("CA", "MEDICAL_MALPRACTICE"): 3,
    ("CA", "SLIP_FALL"): 2,
    ("CA", "PRODUCT_LIABILITY"): 2,
    ("CA", "PREMISES"): 2,
    ("CA", "DOG_BITE"): 2,
    ("NY", "AUTO"): 3,
    ("NY", "MEDICAL_MALPRACTICE"): 2,
    ("NY", "SLIP_FALL"): 3,
    ("NY", "PRODUCT_LIABILITY"): 3,
    ("NY", "PREMISES"): 3,
    ("NY", "DOG_BITE"): 3,
    ("TX", "AUTO"): 2,
    ("TX", "MEDICAL_MALPRACTICE"): 2,
    ("TX", "SLIP_FALL"): 2,
    ("TX", "PRODUCT_LIABILITY"): 2,
    ("TX", "PREMISES"): 2,
    ("TX", "DOG_BITE"): 2,
}
# Default base years for a jurisdiction not listed above — 2 is the modal value.
SOL_DEFAULT_BASE_YEARS = 2

MINOR_TAIL_TABLE: dict[str, int] = {
    "CA": 2,
    "NY": 3,
    "TX": 2,
}
MINOR_TAIL_DEFAULT_YEARS = 2

# ── Court calendar constants ──────────────────────────────────────────────
COURT_BUFFER_MINUTES = 15
COURT_DURATION_MIN = 15
COURT_DURATION_MAX = 480

# ── Demand letter / records constants ─────────────────────────────────────
SOL_MIN_BUFFER_DAYS_FOR_RECORDS = 30  # Cannot start records work within 30 days of SoL.
DEMAND_RESPONSE_DUE_DAYS = 30
