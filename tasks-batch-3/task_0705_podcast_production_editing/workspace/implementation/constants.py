"""Domain constants (scaffold §1.3 calculation constants; PRD §3)."""

# Roles (PRD §2.1)
ROLES = {"PlatformAdmin", "ShowOwner", "ProducerEng", "AdOps"}

# Enum domains (scaffold §1.1)
SHOW_FORMATS = {"INTERVIEW", "SOLO", "PANEL", "NARRATIVE"}
BILLING_MODELS = {"PER_EPISODE", "RETAINER"}
CONTRACT_TIERS = {"STANDARD", "PRIORITY", "RUSH"}
ENGAGEMENT_TYPES = {"PER_EPISODE", "RETAINER"}
CAPTURE_MODES = {"STUDIO", "REMOTE"}
DELIVERABLE_KINDS = {"MASTER_AUDIO", "SHOW_NOTES", "TRANSCRIPT"}
INVOICE_KINDS = {"PER_EPISODE", "RETAINER_OVERAGE"}
AD_PLACEMENTS = {"PRE_ROLL", "MID_ROLL", "POST_ROLL"}

# target_loudness_lufs range / default (PRD §2.10)
TARGET_LOUDNESS_MIN = -23.0
TARGET_LOUDNESS_MAX = -12.0
TARGET_LOUDNESS_DEFAULT = -16.0

# Loudness tolerance (PRD §2.10): "a fixed tolerance". The PRD/scaffold name the
# constant LOUDNESS_TOLERANCE_LUFS but do not give a numeric value; 1.0 LU is the
# standard mastering conformance tolerance and is used here.
LOUDNESS_TOLERANCE_LUFS = 1.0

# Turnaround SLA (PRD §3.6 / calc turnaround_due)
TIER_SLA_HOURS = {"STANDARD": 72, "PRIORITY": 48, "RUSH": 24}
SURCHARGE_HOURS_PER_TRACK = 6
MULTITRACK_FLOOR_TRACKS = 2

# Per-episode invoice (PRD §3.5 / calc invoice_total)
TIER_BASE_CENTS = {"STANDARD": 15000, "PRIORITY": 22000, "RUSH": 35000}
TRANSCRIPT_CENTS = 4000
EXTRA_TRACK_FLOOR = 2
EXTRA_TRACK_RATE_CENTS = 2500
DISCOUNT_CAP_CENTS = 5000

# Late fee tiers (PRD §3.7 / calc late_fee)
GOLD_THRESHOLD_CENTS = 80000
SILVER_THRESHOLD_CENTS = 40000
LATE_FEE_PCT = {"BRONZE": 0.02, "SILVER": 0.035, "GOLD": 0.05}

# Retainer overage (PRD §3.8 / calc retainer_reconciliation)
OVERAGE_RATE_CENTS = {"STANDARD": 12000, "PRIORITY": 16000, "RUSH": 22000}

# AdCampaign platform fee default/range (PRD §3.10)
PLATFORM_FEE_DEFAULT = 0.30
PLATFORM_FEE_MIN = 0.0
PLATFORM_FEE_MAX = 0.5

# loyalty_discount_pct range (PRD §3.1)
LOYALTY_DISCOUNT_MIN = 0.0
LOYALTY_DISCOUNT_MAX = 0.5

# Engineer remote buffer default (PRD §3.3)
REMOTE_BUFFER_DEFAULT = 30

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
