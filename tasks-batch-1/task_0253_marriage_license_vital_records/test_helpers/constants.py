"""Domain thresholds — numeric constants from the PRD's fee and eligibility rules."""

# Waiting period & validity window (PRD §3.3)
WAITING_PERIOD_HOURS = 72          # valid_from = issued_at + 72 hours
VALIDITY_WINDOW_DAYS = 90          # expires_at = issued_at + 90 days

# Certified-copy tiered pricing (PRD §3.6)
FIRST_TIER_COPIES = 3
FIRST_TIER_CENTS = 1500
ADDITIONAL_COPY_CENTS = 900
CONFIDENTIAL_SURCHARGE_CENTS = 2500

# Amendment fee (PRD §3.7)
CLERICAL_BASE_CENTS = 2000
SUBSTANTIVE_BASE_CENTS = 5000
EXPEDITE_PCT = 0.15
RESUBMIT_PENALTY_PCT = 0.10
MAX_AMENDMENT_RESUBMITS = 2

# Fee waiver means test (PRD §3.7)
BASE_POVERTY_CENTS = 130000
PER_PERSON_POVERTY_CENTS = 45000
DEEP_NEED_RATIO = 0.50
FULL_WAIVER_CAP_CENTS = 6000
PARTIAL_WAIVER_CAP_CENTS = 3000

# Eligibility ages (PRD §3.2)
MIN_AGE_NO_CONSENT = 18
MIN_AGE_WITH_CONSENT = 16

# Remarriage wait (PRD §3.2)
REMARRIAGE_WAIT_DAYS = 30

# Return filing window (PRD §3.4)
RETURN_FILING_DAYS = 10

# Fixed action fees (PRD §3.3, §3.4, §3.7)
LICENSE_FEE_CENTS = 9000
LATE_RETURN_SURCHARGE_CENTS = 2000
APOSTILLE_FEE_CENTS = 4000

# Interval conflict buffer (PRD §3.8)
OFFICIANT_BUFFER_MINUTES = 60
