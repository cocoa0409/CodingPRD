"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# PRD §3.3: sales tax rate applied to the per-line-rounded subtotal.
SALES_TAX_RATE = 0.0825

# PRD §3.10: retainage withheld per draw and its cumulative cap.
RETAINAGE_RATE = 0.10
RETAINAGE_CAP_RATE = 0.05

# PRD §3.11: APR tiers selected by financing term_months.
APR_BY_TERM = {60: 0.0599, 120: 0.0799, 180: 0.0999}

# PRD §3.11: DTI threshold — declined when dti_ratio strictly greater than this.
DTI_MAX = 0.43

# PRD §3.3: default and bounds for waste_factor_pct.
DEFAULT_WASTE_FACTOR_PCT = 0.10
WASTE_FACTOR_MIN = 0.0
WASTE_FACTOR_MAX = 0.50

# PRD §3.6: default crew wind threshold (mph).
DEFAULT_MAX_WIND_MPH = 25

# PRD §3.6: site sequencing buffer (hours) applied on each side of a window.
SITE_BUFFER_HOURS = 24

# PRD §3.12: server startup default logical clock.
DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"

# A convenient post-ETA clock instant used throughout fixtures.
COMMON_DELIVERY_ETA_ISO = "2026-04-10T00:00:00Z"

# Allowed financing terms (PRD §3.11).
ALLOWED_TERM_MONTHS = [60, 120, 180]
