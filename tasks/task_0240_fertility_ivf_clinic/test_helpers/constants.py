"""Domain thresholds — numeric constants from the PRD billing/fee rules.

Generic NON_EXISTENT_UUID comes from the framework. A second well-formed but
unused UUID is provided for body-FK not-found tests that must not collide.
"""

# Cancellation-fee tiers, keyed by the protocol stage reached at cancel time (PRD 3.9).
CANCELLATION_FEE_CENTS = {
    "DRAFT": 0,
    "STIM": 50000,
    "RETRIEVAL": 150000,
    "FERTILIZATION": 250000,
}

# Pagination defaults (PRD 2.3).
PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}

# Clinic clock initial value (PRD 2.5).
CLOCK_EPOCH = "1970-01-01T00:00:00.000Z"

# A well-formed UUID guaranteed not to be a real entity id (for body-FK 404 tests).
MISSING_FK_UUID = "00000000-0000-4000-8000-000000000001"
