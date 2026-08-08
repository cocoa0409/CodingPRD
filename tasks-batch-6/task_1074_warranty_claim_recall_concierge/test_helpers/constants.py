"""Domain thresholds and tier configuration from the PRD calculations."""

# Per-tier configuration (PRD Sections 3.2, 3.3, 3.7, 3.8).
TIER_CONFIG = {
    "BASIC": {
        "included_claims_per_year": 2,
        "extended_warranty_bonus_months": 0,
        "prorate_refunds": True,
        "shipping_reimbursement_pct": 0.0,
        "concierge_fee_pct": 0.10,
    },
    "PLUS": {
        "included_claims_per_year": 5,
        "extended_warranty_bonus_months": 6,
        "prorate_refunds": False,
        "shipping_reimbursement_pct": 0.5,
        "concierge_fee_pct": 0.05,
    },
    "PREMIUM": {
        "included_claims_per_year": 20,
        "extended_warranty_bonus_months": 12,
        "prorate_refunds": False,
        "shipping_reimbursement_pct": 1.0,
        "concierge_fee_pct": 0.0,
    },
}

# Recall severity → exposure weight (PRD Section 3.1 / 3.4).
SEVERITY_WEIGHT = {"LOW": 1, "HIGH": 3, "CRITICAL": 5}

# Logical clock default on server startup (PRD Section 2.6).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
