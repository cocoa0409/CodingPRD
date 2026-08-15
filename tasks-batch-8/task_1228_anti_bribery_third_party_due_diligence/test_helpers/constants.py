"""Domain thresholds and constants from the PRD's calculation narratives (§3)."""

# Logical clock startup default (PRD §2.5).
STARTUP_CLOCK = "2026-05-01T00:00:00Z"

# Risk scoring (PRD §3.1-§3.4).
INDUSTRY_SCORES = {
    "TECHNOLOGY": 20,
    "LOGISTICS": 40,
    "CONSULTING": 60,
    "CONSTRUCTION": 70,
    "GOVERNMENT_RELATIONS": 90,
}
TOUCHPOINT_SCORES = {"NONE": 0, "INDIRECT": 50, "DIRECT": 100}
Q_GOV_OWNERSHIP_MOD = 10
Q_FACILITATION_MOD = 15
Q_SUB_AGENTS_MOD = 5
S_PEP_MOD = 20
S_ADVERSE_MEDIA_MOD = 10
SANCTIONED_OVERRIDE_SCORE = 100

# Commission reasonableness (PRD §3.7) country multiplier bands.
MULT_BAND_HIGH_RISK = 0.60   # country_norm >= 70
MULT_BAND_MEDIUM_RISK = 0.80  # 40 <= country_norm <= 69
MULT_BAND_LOW_RISK = 1.00    # country_norm < 40
NORM_HIGH_MIN = 70
NORM_MEDIUM_MIN = 40

# Gift registry (PRD §3.8).
GIFT_ENHANCED_THRESHOLD_CENTS = 25000
GIFT_HARD_CAP_CENTS = 50000
GIFT_WINDOW_DAYS = 365

# Re-diligence (PRD §3.5, §3.9).
TIER_INTERVAL_DAYS = {"CRITICAL": 90, "HIGH": 180, "MEDIUM": 365, "LOW": 365}
MANUAL_CYCLE_DAYS = 30
AUTO_SUSPEND_GRACE_DAYS = 30

# Audit rights (PRD §3.9).
AUDIT_NOTICE_DAYS = 10

# Contract clause sets keyed off approval_tier_snapshot (PRD §3.6).
REQUIRED_CLAUSES = {
    "LOW": {"ABAC"},
    "MEDIUM": {"ABAC"},
    "HIGH": {"ABAC", "AUDIT_RIGHTS", "ANNUAL_CERTIFICATION"},
    "CRITICAL": {"ABAC", "AUDIT_RIGHTS", "ANNUAL_CERTIFICATION",
                 "TERMINATION_FOR_CAUSE", "GOVT_OFFICIAL_DISCLOSURE"},
}
