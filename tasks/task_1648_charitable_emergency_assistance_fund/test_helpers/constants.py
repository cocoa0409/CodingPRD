"""Domain constants — logical-clock default and canonical money/period values
used across the suite. All monetary values are integer cents (PRD §2.6)."""

# PRD §2.4: at startup the logical clock reads exactly 2026-08-01T00:00:00Z.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical funding period covering the default clock reading.
PERIOD_START = "2026-01-01T00:00:00Z"
PERIOD_END = "2027-01-01T00:00:00Z"

# Canonical policy limits (integer cents).
POLICY_DEFAULTS = {
    "name": "P1",
    "max_annual_benefit_cents": 100000,
    "rent_cap_cents": 50000,
    "utility_cap_cents": 40000,
    "income_limit_cents": 5000000,
}

# Policy defaults the server applies when the optional fields are omitted
# (PRD §3.1).
POLICY_FIELD_DEFAULTS = {
    "appeal_window_days": 30,
    "require_eviction_notice": True,
    "require_lease_ledger": False,
    "require_utility_bill": True,
}

SOURCE_DEFAULTS = {
    "name": "General Fund",
    "funder_name": "First Church",
    "source_type": "DONOR_UNRESTRICTED",
    "allowed_categories": ["RENT", "UTILITY"],
    "period_start": PERIOD_START,
    "period_end": PERIOD_END,
    "total_budget_cents": 100000,
    "max_per_household_cents": 1000000,
}

HOUSEHOLD_DEFAULTS = {
    "head_of_household_name": "Ana Ruiz",
    "address": "12 Oak St",
    "phone": "555-0101",
    "household_size": 3,
    "annual_income_cents": 1000000,
}

VENDOR_DEFAULTS = {
    "name": "Riverside Properties",
    "vendor_type": "LANDLORD",
}

APPLICATION_DEFAULTS = {
    "category": "RENT",
    "requested_amount_cents": 10000,
    "service_month": "2026-08",
}

PAYMENT_DEFAULTS = {
    "payment_date": "2026-08-02T00:00:00Z",
}
