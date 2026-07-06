"""Domain thresholds — numeric constants from the MSP Managed IT PRD.

Every value here is a verbatim constant from PRD prose. Comment references
point to the numbered section that names each constant.
"""

# PRD §2.4: logical clock startup default.
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# PRD §3.2: contract billing period is exactly 30 days.
PERIOD_DAYS = 30

# PRD §3.8: add-on rates per seat, per period.
BACKUP_RATE_CENTS_PER_SEAT = 800
SECURITY_RATE_CENTS_PER_SEAT = 1500

# PRD §3.8: overage rate.
OVERAGE_RATE_CENTS_PER_MIN = 250

# PRD §3.8: included ticket minutes per tier.
INCLUDED_MINUTES = {
    "BRONZE": 600,
    "SILVER": 1200,
    "GOLD": 3000,
}

# PRD §3.8: volume-discount tiers (inclusive lower bound on seat_count_snapshot).
VOLUME_DISCOUNT_TIERS = [
    (1, 9, 0.00),
    (10, 24, 0.05),
    (25, 49, 0.10),
    (50, 10_000_000, 0.15),
]

# PRD §3.5: priority-standard ESTIMATED minutes.
PRIORITY_ESTIMATE_MINUTES = {
    "P1": 240,
    "P2": 120,
    "P3": 60,
    "P4": 30,
}

# PRD §3.5: SLA response-time targets (minutes) by service tier and priority.
SLA_RESPONSE_MINUTES = {
    "GOLD":   {"P1": 15,  "P2": 30,  "P3": 60,   "P4": 120},
    "SILVER": {"P1": 30,  "P2": 60,  "P3": 120,  "P4": 240},
    "BRONZE": {"P1": 60,  "P2": 120, "P3": 240,  "P4": 480},
}

# PRD §3.5: SLA resolve-time targets (minutes).
SLA_RESOLVE_MINUTES = {
    "GOLD":   {"P1": 240, "P2": 480, "P3": 1440, "P4": 2880},
    "SILVER": {"P1": 480, "P2": 960, "P3": 2880, "P4": 5760},
    "BRONZE": {"P1": 960, "P2": 1920,"P3": 5760, "P4": 11520},
}

# PRD §3.6: technician travel buffer is 30 minutes for ONSITE, 0 for REMOTE.
TRAVEL_BUFFER_ONSITE_MIN = 30
TRAVEL_BUFFER_REMOTE_MIN = 0

# PRD §3.7: default tax rate for quotes and procurement orders.
DEFAULT_TAX_RATE = 0.08

# PRD §3.4: empty-set patch compliance default.
PATCH_COMPLIANCE_EMPTY_DEFAULT = 100.00
