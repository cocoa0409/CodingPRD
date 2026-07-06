"""Domain thresholds — numeric constants drawn from the PRD calculations (§2.5, §3.3, §3.4).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Labor accounting (§3.3): $30.00 charge per started quarter-hour, integer cents.
LABOR_QUARTER_CENTS = 3000

# Diagnostic fee assessment (§3.3): flat $89.00 diagnostic fee, waived above threshold.
DIAGNOSTIC_FEE_CENTS = 8900
WAIVER_THRESHOLD_CENTS = 15000

# Appliance health score weights (§3.3): baseline 100 minus weighted penalties.
HEALTH_BASELINE = 100
W_AGE = 5
W_REPAIR = 8
W_RECALL = 20

# Technician timeline conflict (§3.2): symmetric 30-minute travel buffer.
TRAVEL_BUFFER_MIN = 30

THRESHOLDS = {
    "LABOR_QUARTER_CENTS": LABOR_QUARTER_CENTS,
    "DIAGNOSTIC_FEE_CENTS": DIAGNOSTIC_FEE_CENTS,
    "WAIVER_THRESHOLD_CENTS": WAIVER_THRESHOLD_CENTS,
    "HEALTH_BASELINE": HEALTH_BASELINE,
    "W_AGE": W_AGE,
    "W_REPAIR": W_REPAIR,
    "W_RECALL": W_RECALL,
    "TRAVEL_BUFFER_MIN": TRAVEL_BUFFER_MIN,
}
