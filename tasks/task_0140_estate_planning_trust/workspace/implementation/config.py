"""Server-wide configuration constants for the Estate Planning Trust API.

All values are anchored in SCAFFOLD.yaml / PRD.md — do not hardcode literals
elsewhere that should be read from this module.
"""
from __future__ import annotations

import os

# ── Networking ─────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# ── Auth headers (PRD §2.1) ────────────────────────────────────────────────
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Roles (PRD §2.1 / SCAFFOLD §1.7)
ROLE_EXECUTOR = "Executor"
ROLE_BENEFICIARY = "Beneficiary"
ROLE_COURT_CLERK = "CourtClerk"
ROLE_FIDUCIARY = "Fiduciary"
ROLES = {ROLE_EXECUTOR, ROLE_BENEFICIARY, ROLE_COURT_CLERK, ROLE_FIDUCIARY}

# ── Pagination (response_envelope.pagination_defaults) ─────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Domain enums (SCAFFOLD §1.1) ───────────────────────────────────────────
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

ESTATE_PHASES = {"DRAFT", "IN_PROBATE", "INVENTORIED", "DISTRIBUTING", "SETTLED", "CONTESTED"}
PROBATE_POSTURES = {"OPEN", "UNDER_COURT_REVIEW", "FROZEN"}

ASSET_CLASSES = {"REAL_ESTATE", "FINANCIAL", "PERSONAL_PROPERTY", "DIGITAL"}
ASSET_STATUSES = {"DECLARED", "INVENTORIED", "APPRAISED", "DISTRIBUTED", "EXCLUDED"}

BENEFICIARY_RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT", "SIBLING", "CHARITY", "OTHER"}
BENEFICIARY_STATUSES = {"ACTIVE", "DISCLAIMED", "REMOVED"}

DESIGNATION_STATUSES = {"PROPOSED", "LOCKED", "VOIDED"}

FIDUCIARY_SCOPE_TYPES = {"EXECUTOR", "TRUSTEE", "GUARDIAN"}
FIDUCIARY_STATUSES = {"NOMINATED", "CONFIRMED", "RESIGNED", "REMOVED"}

GUARDIANSHIP_STATUSES = {"DRAFT", "EFFECTIVE", "SUPERSEDED", "REVOKED"}

HIPAA_SCOPES = {"MEDICAL_RECORDS", "MENTAL_HEALTH", "SUBSTANCE_ABUSE", "ALL"}
HIPAA_STATUSES = {"ACTIVE", "EXPIRED", "REVOKED"}

POA_TYPES = {"FINANCIAL_DURABLE", "MEDICAL", "LIMITED"}
POA_STATUSES = {"PENDING", "ACTIVE", "REVOKED", "TERMINATED"}

DIRECTIVE_TYPES = {"LIVING_WILL", "DNR", "DNI", "POLST"}
DIRECTIVE_STATUSES = {"DRAFT", "EXECUTED", "SUPERSEDED", "REVOKED"}

FILING_TYPES = {
    "PETITION_TO_PROBATE",
    "INVENTORY_REPORT",
    "INTERIM_ACCOUNTING",
    "FINAL_ACCOUNTING",
    "DISTRIBUTION_PETITION",
}
FILING_STATUSES = {"SUBMITTED", "ACCEPTED", "REJECTED", "REVISION_REQUESTED"}

DISTRIBUTION_STATUSES = {"PLANNED", "EXECUTED", "REVERSED"}

# ── Bond tiers (SCAFFOLD §1.3 required_bond) ───────────────────────────────
FLAT_BOND_FEE_CENTS = 25000
TIER1_LIMIT_CENTS = 10_000_000
TIER2_LIMIT_CENTS = 100_000_000
# Rates as Decimal-string literals for precision.
TIER1_RATE = "0.0100"
TIER2_RATE = "0.0050"
TIER3_RATE = "0.0025"

# ── Settlement window ──────────────────────────────────────────────────────
# 18 months ≈ 540 days (per PRD §3.1 / §3.14).
SETTLEMENT_WINDOW_DAYS = 540

# ── Risk score weights (SCAFFOLD §1.3 fiduciary_risk_score) ────────────────
TIME_FACTOR_WEIGHT = "1.0"
BOND_FACTOR_WEIGHT = "2.0"
FILING_FACTOR_WEIGHT = "2.0"
SCORE_FLOOR = "0.0"
SCORE_CEILING = "5.0"

# ── Field length limits ────────────────────────────────────────────────────
ASSET_DESCRIPTION_MAX = 500
DIRECTIVE_INSTRUCTIONS_MAX = 4000
