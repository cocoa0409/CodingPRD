"""Domain thresholds — numeric constants from the PRD's billing, ad-break,
watch-minute, and download-size computations (§2.6, §3.6, §3.7).

NON_EXISTENT_UUID comes from the framework.
"""

# Billing / proration (PRD §2.6): a billing period spans 30 whole days.
PERIOD_DAYS = 30

# Watch-minute attribution (PRD §3.6): minutes in a UTC day.
MINUTES_PER_DAY = 1440

# Ad-break cadence (PRD §3.6): one mid-roll per full 30 runtime minutes.
AD_CADENCE_MIN = 30

# Download size (PRD §3.7): HD doubles the SD license footprint.
HD_MULTIPLIER = 2

# Maturity rating order, least-to-most restrictive (PRD §2.8).
RATING_ORDER = ["G", "PG", "PG13", "R", "NC17"]

# Per-kind rating defaults (PRD §2.8).
KIND_RATING_DEFAULT = {"KID": "G", "TEEN": "PG13", "ADULT": "NC17"}
