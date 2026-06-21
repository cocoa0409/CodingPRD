"""Domain thresholds — numeric constants from the PRD's calculations (§3.3, §3.4)."""

# TEFAP income eligibility (PRD §3.3): threshold_cents =
#   199800 + (household_size - 1) * 70500; eligible iff income <= threshold.
TEFAP_BASE_CENTS = 199800
TEFAP_PER_PERSON_CENTS = 70500


def tefap_threshold_cents(household_size: int) -> int:
    """Income ceiling in integer cents for a household of the given size (PRD §3.3)."""
    return TEFAP_BASE_CENTS + (household_size - 1) * TEFAP_PER_PERSON_CENTS


# Pagination bounds (PRD §2.3).
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_LIMIT = 10
