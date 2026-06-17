"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework. The constants here mirror the
literal figures the PRD pins for the hotshot fee, the credit/pagination defaults,
and vehicle-year range, so tests reference one named source.
"""

# Hotshot fee (PRD §3.4): flat base of twenty-five dollars plus seven dollars and
# fifty cents per special-order unit.
HOTSHOT_BASE_FEE_CENTS = 2500
HOTSHOT_PER_UNIT_CENTS = 750

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Vehicle model-year range (PRD §3.1).
MIN_VEHICLE_YEAR = 1900
MAX_VEHICLE_YEAR = 2100

# A syntactically valid UUID that does not resolve to any entity (for not-found tests
# where a specific literal is convenient).
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
