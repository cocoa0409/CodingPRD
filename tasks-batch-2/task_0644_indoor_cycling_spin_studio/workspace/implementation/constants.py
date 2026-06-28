"""System constants traced to the scaffold §1.3 and the PRD.

All values are taken verbatim from the PRD / scaffold. Where the PRD names a
quantity but no numeric value is pinned, the scaffold constant is used.
"""

# Roles (PRD §2.1, spelled exactly)
ROLE_STUDIO_MANAGER = "StudioManager"
ROLE_MEMBER = "Member"
ROLE_INSTRUCTOR = "Instructor"
ROLE_ANONYMOUS = "Anonymous"
VALID_ROLES = {ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR, ROLE_ANONYMOUS}

# Studio policy defaults (PRD §3.1)
DEFAULT_TIMEZONE = "UTC"
DEFAULT_LATE_CANCEL_WINDOW_MINUTES = 720  # 12h
DEFAULT_LATE_CANCEL_FEE_CENTS = 2000
DEFAULT_NO_SHOW_FEE_CENTS = 3000

# Session defaults (PRD §3.2)
DEFAULT_WAITLIST_CAPACITY = 10

# Shoe rental (PRD §3.7, scaffold booking_charge_resolution constants)
SHOE_RENTAL_FEE_CENTS = 500

# Strike accumulation (PRD §2.9, scaffold member_active_strike_count constants)
STRIKE_WINDOW_DAYS = 30
STRIKE_SUSPEND_THRESHOLD = 3

# Retail volume-discount tiers (PRD §3.10, scaffold retail_order_total constants)
TIER1_MIN_QTY = 3
TIER1_PCT = 0.05
TIER2_MIN_QTY = 6
TIER2_PCT = 0.10

# Check-in lead time (PRD §3.4: "the configured check-in lead time"; scaffold
# references CHECKIN_OPEN_MINUTES). No numeric value is pinned in the PRD, so a
# studio-standard 60-minute lead is used. Check-in is allowed from
# start_utc - CHECKIN_OPEN_MINUTES through end_utc.
CHECKIN_OPEN_MINUTES = 60
