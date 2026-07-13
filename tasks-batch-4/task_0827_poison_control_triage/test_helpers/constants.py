"""Domain thresholds and constants used across the Poison Control Triage tests.

All values are drawn from the numeric rules stated in the PRD (§2.5, §2.6, §3.3,
§3.4, §3.7, §3.8). Generic ``NON_EXISTENT_UUID`` comes from the framework.
"""

# --- Logical clock (PRD §2.5) ---
STARTUP_CLOCK = "2026-03-01T00:00:00Z"

# --- Toxicity scoring: bioavailability by route (PRD §3.3) ---
ROUTE_BIOAVAILABILITY = {
    "INGESTION": 1.0,
    "INHALATION": 0.8,
    "DERMAL": 0.4,
    "OCULAR": 0.3,
    "INJECTION": 1.0,
}

# --- Severity band thresholds on toxicity_score (PRD §3.3) ---
SEVERITY_MODERATE_MIN = 0.25
SEVERITY_SEVERE_MIN = 0.75
SEVERITY_CRITICAL_MIN = 1.5

# --- Aggregate risk: co-ingestant interaction weights (PRD §3.4) ---
INTERACTION_WEIGHT = {
    "MINIMAL": 0.5,
    "MODERATE": 1.0,
    "SEVERE": 1.25,
    "CRITICAL": 1.5,
}
CO_INGESTANT_MULTIPLIER = 1.15
CO_INGESTANT_THRESHOLD_COUNT = 2
CO_INGESTANT_SCORE_FLOOR = 0.25

# --- Follow-up scheduling (PRD §3.5, §3.6) ---
FOLLOWUP_WINDOW_MINUTES = 30
FOLLOWUP_RETRY_INTERVAL_HOURS = 6
FOLLOWUP_SPECIALIST_BUFFER_MINUTES = 15

# --- Consult billing (PRD §3.7) ---
CONSULT_BASE_UNITS = 2
SPECIALIST_RATE_UNITS = {"MINIMAL": 1, "MODERATE": 2, "SEVERE": 3, "CRITICAL": 4}
DISCOUNT_TIER_1_THRESHOLD = 5
DISCOUNT_TIER_2_THRESHOLD = 10

# --- NPDS medical outcome thresholds on aggregate_score_additive (PRD §3.8) ---
OUTCOME_MODERATE_THRESHOLD = 0.5
OUTCOME_MAJOR_THRESHOLD = 1.5

# --- Pagination defaults (PRD §2.3) ---
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
