"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD: the logical clock).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Cupping verdict thresholds (PRD §3.5).
SPECIALTY_GREEN_THRESHOLD = 80.00
ROASTED_BATCH_THRESHOLD = 78.00

# Cupping panel minimum for a decisive session.
MIN_PANELISTS = 3

# Recipe component sum must equal this at approval (5-decimal precision).
RECIPE_COMPONENT_SUM_TARGET = 1.00000

# Default delivery window used across tests.
DEFAULT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-12-31T23:59:59Z"
