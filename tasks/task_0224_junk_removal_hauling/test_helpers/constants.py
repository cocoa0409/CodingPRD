"""Domain thresholds and the canonical pricing-policy rate set used across tests.

The canonical policy mirrors the rate set described throughout the PRD's pricing
examples (full truck 60000 cents; marginal tier bands 1.0 / 0.9 / 0.8; surcharges
3500 / 2500 / 5000; landfill 9000 per ton or 12000 flat; recycle 4000 per ton;
diversion credit 1500 per ton; default same-day 0.20, tax 0.08, cancellation 0.25 /
0.50). Generic NON_EXISTENT_UUID comes from the framework.
"""

# Two well-formed random UUIDs for not-found probes.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
NONEXISTENT_UUID_2 = "00000000-0000-4000-8000-000000000001"

# Canonical ACTIVE pricing-policy rate set ("std_policy").
STD_POLICY = {
    "name": "std_policy",
    "full_truck_cents": 60000,
    "tier_breaks": [
        {"upper_fraction": 0.25, "marginal_multiplier": 1.0},
        {"upper_fraction": 0.5, "marginal_multiplier": 0.9},
        {"upper_fraction": 1.0, "marginal_multiplier": 0.8},
    ],
    "mattress_surcharge_cents": 3500,
    "appliance_surcharge_cents": 2500,
    "freon_surcharge_cents": 5000,
    "dump_fee_per_ton_cents": 9000,
    "full_truck_dump_cents": 12000,
    "recycle_fee_per_ton_cents": 4000,
    "diversion_credit_per_ton_cents": 1500,
}

# Policy defaults (PRD §2.11 / §2.8).
POLICY_DEFAULTS = {
    "min_billable_fraction": 0.125,
    "fraction_step": 0.125,
    "same_day_surcharge_pct": 0.20,
    "tax_pct": 0.08,
    "cancel_pct_scheduled": 0.25,
    "cancel_pct_dispatched": 0.50,
}

# Default crew/customer knobs (PRD §3.1 / §2.9).
DEFAULT_BUFFER_MINUTES = 30
DEFAULT_CREDIT_LIMIT_CENTS = 50000

# A shift window comfortably covering the standard 09:00-12:00 dispatch windows.
SHIFT_START_UTC = "2026-06-10T08:00:00.000Z"
SHIFT_END_UTC = "2026-06-10T18:00:00.000Z"
