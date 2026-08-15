"""Domain thresholds and canonical fixture values (PRD §2.4, §3)."""

# Logical clock startup default (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Actuarial calculation constants (PRD §3.2)
FULL_CREDIBILITY_EXPOSURE = 1082
TARGET_LOSS_RATIO = 0.68
LOSS_DEVELOPMENT_FACTOR = 1.12

# Wave scheduling separation rule (PRD §3.7)
MIN_WAVE_GAP_DAYS = 7

# Canonical experience fields shared by indication fixtures (PRD §3.2)
EXPERIENCE_DEFAULTS = {
    "earned_premium_cents": 10_000_000,
    "incurred_loss_cents": 7_000_000,
    "paid_loss_cents": 6_500_000,
    "exposure_units": 500,
    "trend_factor": 0.04,
    "countrywide_change_pct": 0.06,
}

# Canonical state regulatory parameters used across scenarios (PRD §3.1)
PROFILE_DEFAULTS = {
    "filing_method": "PRIOR_APPROVAL",
    "min_effective_lead_days": 45,
    "objection_response_sla_days": 30,
    "deemer_days": 60,
    "max_single_change_pct": 0.25,
    "renewal_notice_days": 30,
    "disapproval_window_days": 90,
}

# Canonical filing/wave parameters
FILING_DEFAULTS = {
    "filing_type": "RATE_CHANGE",
    "proposed_change_pct": 0.10,
    "proposed_effective_date": "2026-10-01",
}
WAVE_DEFAULTS = {
    "wave_start_date": "2026-11-16",
    "wave_end_date": "2026-12-15",
    "cap_pct": 0.15,
}
