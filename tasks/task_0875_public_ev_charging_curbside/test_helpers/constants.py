"""Domain thresholds — numeric constants from the PRD pricing, idle, SLA, and buffer rules."""

# Time-of-use energy pricing (PRD §3.4)
PRICING = {
    "PEAK_RATE": 48,               # cents/kWh, hour in [16, 21)
    "SHOULDER_RATE": 36,           # cents/kWh, all other hours
    "OFFPEAK_RATE": 24,            # cents/kWh, hour in [0, 7)
    "DEMAND_KW_THRESHOLD": 150,    # kW; power_kw >= this adds the demand surcharge
    "DEMAND_SURCHARGE_CENTS": 5,   # cents/kWh surcharge
    "ENERGY_COST_CAP_CENTS": 50000,
    "SESSION_FEE_CENTS": 100,      # flat per-session connection fee
}

# Idle occupancy fee (PRD §3.4)
IDLE = {
    "IDLE_GRACE_MIN": 10,          # strict > grace before fee applies
    "IDLE_RATE_CENTS_PER_MIN": 40,
    "IDLE_CAP_CENTS": 3000,
}

# Work-order service-level allowances in hours (PRD §3.6)
SLA_HOURS = {
    "CRITICAL": 4,
    "MEDIUM": 24,
    "LOW": 72,
}

# Maintenance-window clearance buffer (PRD §3.6)
MW_BUFFER_MIN = 60   # minutes; consecutive windows on one station must be >= this apart

# Pagination defaults (PRD §2.3)
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}
