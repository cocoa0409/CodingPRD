"""System constants for the Supply Chain Finance domain.

These values are explicitly fixed in the SCAFFOLD or in PRD §3:
    MAX_EXTENSION_TIER      = 4         (PRD §3.2)
    PLATFORM_FEE_BPS        = 50        (SCAFFOLD financing_total_due)
    APR_FLOOR_BPS           = 300       (SCAFFOLD financing_apr_pricing)
    APR_CEILING_BPS         = 2400      (SCAFFOLD financing_apr_pricing)
    CAPITAL_GOODS_TOLERANCE_BPS = 500   (SCAFFOLD capital_goods_consistency)
    MAX_REVISION_ROUNDS     = 3         (SCAFFOLD_DIFFICULTY_DESIGN explicitly)

Other constants are not pinned by the PRD; sensible production-style defaults
are chosen here. They live as constants so they can be tuned/exposed without
changing call sites.
"""
from __future__ import annotations

# --- Multi-tier extension limits ---
MAX_EXTENSION_TIER: int = 4

# --- Pricing / fees ---
PLATFORM_FEE_BPS: int = 50
APR_FLOOR_BPS: int = 300
APR_CEILING_BPS: int = 2400

# --- Trade-background verification ---
CAPITAL_GOODS_TOLERANCE_BPS: int = 500
THIRD_PARTY_PASS_FLOOR: float = 0.60
ON_SITE_THRESHOLD_CENTS: int = 100_000_000  # 1,000,000.00 in cents

# --- KYC / AML ---
KYC_VALIDITY_DAYS: int = 180
AML_BLACKLIST_THRESHOLD: float = 0.80
FRAUD_RISK_THRESHOLD: float = 0.70
FRAUD_PENALTY: float = 0.20

# --- Financing application lifecycle ---
MAX_REVISION_ROUNDS: int = 3
MAX_PARTIAL_PREPAYMENTS: int = 3

# --- Receivable registration ---
CENTRAL_REGISTRY_THRESHOLD_CENTS: int = 10_000_000  # 100,000.00 in cents

# --- Confirmation due-date window ---
MAX_DUE_DATE_DAYS: int = 365

# --- Collections / aging ---
SOFT_TO_HARD_REMINDER_THRESHOLD: int = 3

# --- Composite supplier risk-rating weights ---
W_KYC: float = 0.5
W_AML: float = 0.3
W_TIER: float = 0.2

# --- Penalty interest rate (bps annualised) per aging bucket ---
PENALTY_BPS_BY_BUCKET: dict[str, int] = {
    "DPD_1_30": 1200,
    "DPD_31_60": 1800,
    "DPD_61_90": 2400,
    "DPD_OVER_90": 3000,
}

# --- Core enterprise risk-rating APR adjustment (bps) ---
CORE_RISK_ADJ_BPS: dict[str, int] = {
    "AAA": -150,
    "AA": -100,
    "A": 0,
    "BBB": 100,
    "BB": 250,
}

# --- Reverse-factoring KYC factor mapping ---
REVERSE_FACTOR_CORE_KYC_MAP: dict[str, float] = {
    "AAA": 1.0,
    "AA": 0.9,
    "A": 0.8,
    "BBB": 0.7,
    "BB": 0.5,
}

# --- Financing-application supplier-rating APR adjustment (bps) ---
SUPPLIER_RISK_ADJ_BPS: dict[str, int] = {
    "LOW": 0,
    "MEDIUM": 100,
    "HIGH": 250,
}

# --- Base APR (bps) by financing mode ---
MODE_BASE_BPS: dict[str, int] = {
    "FACTORING": 800,
    "REVERSE_FACTORING": 600,
    "DYNAMIC_DISCOUNTING": 500,
    "RECEIVABLE_PLEDGE": 700,
}

# --- Supported enums ---
FINANCING_MODES = set(MODE_BASE_BPS.keys())
RISK_RATINGS = set(CORE_RISK_ADJ_BPS.keys())
KYC_STATUSES = {"NOT_RUN", "PASSED", "FAILED", "EXPIRED"}
VALID_ROLES = {
    "CoreEnterpriseUser",
    "SupplierUser",
    "CreditOfficer",
    "ComplianceOfficer",
    "RiskReviewer",
    "CreditApprover",
    "Funder",
    "CollectionManager",
    "PlatformAdmin",
}
