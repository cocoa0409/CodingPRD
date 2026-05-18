"""Server-wide configuration constants for the USCIS Immigration API."""
from __future__ import annotations

import os

# ── Networking ─────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# ── Auth headers (read from SCAFFOLD §1.4 / PRD §2.1) ──────────────────────
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Roles recognised by the system (PRD §2.1, SCAFFOLD §1.7).
ROLES = {"Petitioner", "Beneficiary", "Officer", "Supervisor"}

# ── Pagination (SCAFFOLD response_envelope.pagination_defaults) ────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Domain constants ───────────────────────────────────────────────────────
# Valid case_type values.
CASE_TYPES = {"I-130", "I-485", "I-765", "I-131"}
# Valid receipt prefixes (PRD §2.7).
VALID_RECEIPT_PREFIXES = {"MSC", "EAC", "WAC", "NBC", "LIN", "SRC", "IOE", "YSC"}
# Valid preference categories (Beneficiary).
PREFERENCE_CATEGORIES = {"F1", "F2A", "F2B", "F3", "F4", "IR"}
# Visa Bulletin preference categories (no IR; IR is exempt).
VB_PREFERENCE_CATEGORIES = {"F1", "F2A", "F2B", "F3", "F4"}
# Relationship enums.
RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT", "SIBLING", "FIANCE"}
# RFE reason codes.
RFE_REASON_CODES = {"MISSING_DOC", "IDENTITY_DOC", "FINANCIAL_PROOF", "MEDICAL_EXAM", "TRANSLATION"}
# Interview outcomes.
INTERVIEW_OUTCOMES = {"RECOMMEND_APPROVAL", "RECOMMEND_DENIAL", "CONTINUED"}
# Denial reasons (officer-driven subset).
OFFICER_DENIAL_REASONS = {"OFFICER_DENIAL", "INELIGIBLE"}
ALL_DENIAL_REASONS = {"RFE_TIMEOUT", "OFFICER_DENIAL", "ABANDONMENT", "INELIGIBLE"}
# Chart types.
CHART_TYPES = {"FINAL_ACTION", "DATES_FOR_FILING"}
DEFAULT_CHART_IN_EFFECT = "FINAL_ACTION"
# Case statuses.
CASE_STATUSES = {
    "DRAFT", "FILED", "BIOMETRICS_SCHEDULED", "BIOMETRICS_COMPLETED",
    "RFE_ISSUED", "RFE_RESPONDED", "INTERVIEW_SCHEDULED", "READY_FOR_DECISION",
    "APPROVED", "DENIED", "WITHDRAWN",
}
PRIORITY_DATE_STATUSES = {"NOT_APPLICABLE", "CURRENT", "NOT_CURRENT", "RETROGRESSED"}

# ── Score weights (PRD §3.11) ──────────────────────────────────────────────
WEIGHT_STATUS = "0.40"
WEIGHT_BIOMETRICS = "0.20"
WEIGHT_RFE = "0.10"
WEIGHT_INTERVIEW = "0.15"
WEIGHT_PRIORITY = "0.15"

# ── Time windows ───────────────────────────────────────────────────────────
BIOMETRICS_MIN_LEAD_DAYS = 7
INTERVIEW_MIN_LEAD_DAYS = 14
BIOMETRICS_RESCHEDULE_CAP = 3
NO_SHOW_GRACE_HOURS = 24
RESCHEDULE_BLACKOUT_HOURS = 24
