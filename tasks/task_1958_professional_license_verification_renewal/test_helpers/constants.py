"""Domain thresholds and defaults — numeric constants from the PRD."""

# Employer-wide fiscal ceilings (PRD §3.6): one million cents = ten thousand dollars.
EMPLOYER_COMMITTED_CAP_CENTS = 1_000_000
EMPLOYER_PAID_CAP_CENTS = 1_000_000

# Alert-tier day bands (PRD §3.5): boundaries fall into the nearer tier.
ALERT_T90_DAYS = 90
ALERT_T60_DAYS = 60
ALERT_T30_DAYS = 30

# License validity window (PRD §3.3): expires_on may not exceed issued_on + 730 days.
MAX_VALIDITY_DAYS = 730

# Renewal-in-place / reinstatement expiry extension (PRD §3.3): verified_on + 365 days.
RENEWAL_EXTENSION_DAYS = 365

# Exclusion screening validity (PRD §3.8): screened_on + 30 days, inclusive.
SCREENING_VALIDITY_DAYS = 30

# Rolling CE window (PRD §3.4): [current_date - 364 days, current_date].
ROLLING_CE_WINDOW_DAYS = 364

THRESHOLDS = {
    "EMPLOYER_COMMITTED_CAP_CENTS": EMPLOYER_COMMITTED_CAP_CENTS,
    "EMPLOYER_PAID_CAP_CENTS": EMPLOYER_PAID_CAP_CENTS,
    "ALERT_T90_DAYS": ALERT_T90_DAYS,
    "ALERT_T60_DAYS": ALERT_T60_DAYS,
    "ALERT_T30_DAYS": ALERT_T30_DAYS,
    "MAX_VALIDITY_DAYS": MAX_VALIDITY_DAYS,
    "RENEWAL_EXTENSION_DAYS": RENEWAL_EXTENSION_DAYS,
    "SCREENING_VALIDITY_DAYS": SCREENING_VALIDITY_DAYS,
    "ROLLING_CE_WINDOW_DAYS": ROLLING_CE_WINDOW_DAYS,
}

# Default license-type policies used across the suite.
RN_TYPE_PAYLOAD = {
    "code": "RN",
    "name": "Registered Nurse",
    "ce_hours_required_per_cycle": 30.0,
    "cycle_length_months": 24,
    "verification_frequency_days": 180,
    "grace_period_days": 45,
    "requires_exclusion_screening": True,
    "reimbursement_mode": "RECEIPT_BASED",
    "reimburse_full_up_to_cents": 200_000,
    "reimburse_half_up_to_cents": 500_000,
    "flat_schedule_amount_cents": 0,
    "hard_claim_cap_cents": 500_000,
}

PE_TYPE_PAYLOAD = {
    "code": "PE",
    "name": "Professional Engineer",
    "ce_hours_required_per_cycle": 0,
    "cycle_length_months": 24,
    "verification_frequency_days": 365,
    "grace_period_days": 30,
    "requires_exclusion_screening": False,
    "reimbursement_mode": "FLAT_SCHEDULE",
    "reimburse_full_up_to_cents": 0,
    "reimburse_half_up_to_cents": 0,
    "flat_schedule_amount_cents": 100_000,
    "hard_claim_cap_cents": 500_000,
}

LVN_TYPE_PAYLOAD = {
    "code": "LVN",
    "name": "Licensed Vocational Nurse",
    "ce_hours_required_per_cycle": 0,
    "cycle_length_months": 24,
    "verification_frequency_days": 30,
    "grace_period_days": 30,
    "requires_exclusion_screening": True,
    "reimbursement_mode": "FLAT_SCHEDULE",
    "reimburse_full_up_to_cents": 0,
    "reimburse_half_up_to_cents": 0,
    "flat_schedule_amount_cents": 50_000,
    "hard_claim_cap_cents": 500_000,
}

# The logical clock reads exactly this instant before any clock-setting call
# (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"
