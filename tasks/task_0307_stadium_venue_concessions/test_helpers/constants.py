"""Domain thresholds — numeric constants from the PRD calculations (§3.4, §3.6, §3.7)."""

# Event-day pricing (PRD §3.4): surge percentage by demand tier, plus the peak bonus.
TIER_SURGE = {"LOW": 100, "MID": 115, "HIGH": 130}
PEAK_BONUS = 10

# Required staffing (PRD §3.7): throughput per worker and the peak bump.
STAFF_THROUGHPUT = 40
PEAK_STAFF_BONUS = 1

# A canonical non-existent UUID-shaped id used in not-found / forbidden-before-existence tests.
NON_EXISTENT_EVENT_ID = "00000000-0000-4000-8000-000000000000"
