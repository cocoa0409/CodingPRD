"""Domain thresholds and test default identifiers.

Numeric constants come from the PRD's calculation rules (§3); the opaque-operator
user-id strings are test-local identifiers for the four operator roles.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"

# --- Calculation thresholds (PRD §3) -----------------------------------------
THRESHOLDS = {
    "TERM_DAYS": 365,                    # membership term length (PRD §3.2)
    "RENEWAL_WINDOW_DAYS": 30,           # renewal window opens term_end - 30 days (PRD §3.2)
    "MEMBER_DISCOUNT_FLOOR_CENTS": 50000,  # rental subtotal floor for PATRON discount (PRD §3.6)
    "BENEFIT_THRESHOLD_CENTS": 25000,    # GENERAL gift benefit recognition threshold (PRD §3.7)
    "BENEFIT_FMV_CENTS": 2000,           # fair-market value of token-gift premium (PRD §3.7)
}

# --- Garden defaults (PRD §3.1) ----------------------------------------------
GARDEN_DEFAULTS = {
    "TIMEZONE": "America/New_York",
    "RECIPROCAL_DISCOUNT_PCT": 0.5,
    "HOUSEHOLD_MEMBER_CAP": 2,
    "GUEST_PASS_GRANT_HOUSEHOLD": 4,
    "GUEST_PASS_GRANT_PATRON": 8,
}

# --- Opaque operator user identifiers (PRD §2.1) -----------------------------
ADMIN_USER_ID = "op-admin-1"
STAFF_USER_ID = "op-staff-1"
RENTAL_COORDINATOR_USER_ID = "op-rental-1"
DEVELOPMENT_OFFICER_USER_ID = "op-dev-1"

# A generic anonymous Visitor id for non-ownership-gated calls.
ANON_VISITOR_USER_ID = "anon-visitor-1"
