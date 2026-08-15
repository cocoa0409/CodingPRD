"""Domain thresholds and defaults from the PRD's calculation rules.

Standard event policy configuration shared by the test fixtures:
min bid 3000 bps (30 percent) of bundle FMV, 500-cent grid increment,
1000-cent absolute floor, three bid-increment tiers, 25000-cent donor
acknowledgment threshold, 30-day solicitation cooldown, 12-month
certificate validity with a 30-day grace tail.
"""

# Logical clock startup default per the PRD logical-clock section.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Disclosure tier thresholds (integer cents).
TIER_MEDIUM_FLOOR_CENTS = 100000
TIER_HIGH_FLOOR_CENTS = 500000

# Standard event policy configuration used across fixtures.
STANDARD_TIERS = [
    {"up_to_cents": 100000, "increment_cents": 2500},
    {"up_to_cents": 500000, "increment_cents": 5000},
    {"up_to_cents": None, "increment_cents": 10000},
]

STANDARD_EVENT_CONFIG = {
    "name": "Gala",
    "gala_date": "2026-11-20",
    "bidding_opens_at": "2026-11-20T18:00:00Z",
    "bidding_closes_at": "2026-11-20T22:00:00Z",
    "min_bid_pct_bps": 3000,
    "min_bid_increment_cents": 500,
    "min_bid_floor_cents": 1000,
    "bid_increment_tiers": STANDARD_TIERS,
    "ack_threshold_cents": 25000,
    "solicitation_cooldown_days": 30,
    "cert_validity_months": 12,
    "cert_grace_days": 30,
}

# Certificate window expected under the standard config when the invoice
# reaches PAID at the startup clock instant.
STANDARD_CERT_EXPIRES_AT = "2027-08-01T00:00:00Z"
STANDARD_CERT_GRACE_END_AT = "2027-08-31T00:00:00Z"

# Recurring money fixtures (integer cents).
FMV_STANDARD = 40000
WINNING_BID_STANDARD = 50000
