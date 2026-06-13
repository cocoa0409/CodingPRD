"""Domain thresholds and constants from the PRD calculations (§3.2, §3.6, §2.3)."""

# Earth radius used by the haversine distance calculation (PRD §3.2, §3.6).
R_MILES = 3958.7613

# Average bus speed used by the ETA estimate (PRD §3.6).
AVG_SPEED_MPH = 25.0

# District configuration defaults (PRD §3.1).
DEFAULT_WALK_THRESHOLD_MILES = 1.5
DEFAULT_HAZARD_OVERRIDE_ENABLED = True
DEFAULT_MISSED_BUS_GRACE_MINUTES = 10

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Pre-computed haversine / ETA literals used by tests (school at 40.0, -75.0).
# home (40.05, -75.0) -> school: 3.45 mi  (DISTANCE student)
DIST_FAR_MILES = 3.45
# home (40.01, -75.0) -> school: 0.69 mi  (near / hazard student)
DIST_NEAR_MILES = 0.69
# home (40.02171, -75.0) -> school: raw 1.50002 rounds to 1.50 (boundary student)
DIST_EDGE_MILES = 1.5
# ETA from departed stop1 (40.0,-75.0) to next stop seq2 (40.01,-75.0): 1.7 min
ETA_STOP_FALLBACK_MIN = 1.7
# ETA from GPS ping (40.005,-75.0) to next stop seq2 (40.01,-75.0): 0.8 min
ETA_GPS_MIN = 0.8
