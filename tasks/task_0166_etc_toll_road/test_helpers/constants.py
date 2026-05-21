"""Domain thresholds — integer-cents numeric constants from PRD §3.

Each constant traces to a verbatim PRD sentence.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The `limit` parameter defaults to 10, with a minimum of 1 and a
# maximum of 100; the `offset` parameter defaults to 0"
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Account — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "`auto_reload_threshold_cents` ... accepts any integer from 0
# through 10000 inclusive and defaults to 1000"
AUTO_RELOAD_THRESHOLD_MIN_CENTS: int = 0
AUTO_RELOAD_THRESHOLD_MAX_CENTS: int = 10000
AUTO_RELOAD_THRESHOLD_DEFAULT_CENTS: int = 1000

# PRD §3.1: "`auto_reload_topup_cents`, the credit amount, accepts any integer
# from 1000 through 20000 inclusive and defaults to 4000"
AUTO_RELOAD_TOPUP_MIN_CENTS: int = 1000
AUTO_RELOAD_TOPUP_MAX_CENTS: int = 20000
AUTO_RELOAD_TOPUP_DEFAULT_CENTS: int = 4000

# PRD §3.1: "the customer's `holder_name` (between 1 and 120 characters in
# length)"
HOLDER_NAME_MIN_LEN: int = 1
HOLDER_NAME_MAX_LEN: int = 120


# ---------------------------------------------------------------------------
# Vehicle — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "a `plate_number` (1 to 10 characters drawn from the set of
# uppercase letters, digits, and dashes)"
PLATE_NUMBER_MIN_LEN: int = 1
PLATE_NUMBER_MAX_LEN: int = 10

# PRD §3.2: "an optional `axle_count` between 2 and 7 (defaulting to 2)"
AXLE_COUNT_MIN: int = 2
AXLE_COUNT_MAX: int = 7
AXLE_COUNT_DEFAULT: int = 2

# PRD §3.2: "the table that maps `CLASS_2` to 1.00, `CLASS_3` to 1.50,
# `CLASS_4` to 2.25, and `CLASS_5_PLUS` to 3.50"
CLASS_MULTIPLIER = {
    "CLASS_2": 1.00,
    "CLASS_3": 1.50,
    "CLASS_4": 2.25,
    "CLASS_5_PLUS": 3.50,
}

AXLE_CLASS_MAP = {
    2: "CLASS_2",
    3: "CLASS_3",
    4: "CLASS_4",
    5: "CLASS_5_PLUS",
    6: "CLASS_5_PLUS",
    7: "CLASS_5_PLUS",
}


# ---------------------------------------------------------------------------
# Transponder — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the manufacturer `serial_number` (between 10 and 24 characters
# of uppercase letters and digits)"
SERIAL_NUMBER_MIN_LEN: int = 10
SERIAL_NUMBER_MAX_LEN: int = 24


# ---------------------------------------------------------------------------
# Toll event ingest — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "the `gantry_id` (an operator-defined string 1 to 32 characters
# in length)"
GANTRY_ID_MIN_LEN: int = 1
GANTRY_ID_MAX_LEN: int = 32

# PRD §3.3: "`declared_occupants`, an integer between 1 and 9 inclusive
# defaulting to 1"
DECLARED_OCCUPANTS_MIN: int = 1
DECLARED_OCCUPANTS_MAX: int = 9
DECLARED_OCCUPANTS_DEFAULT: int = 1

# PRD §3.3: "the `declared_occupants` is at least 3"
HOV_MIN_OCCUPANTS: int = 3


# ---------------------------------------------------------------------------
# Pricing — PRD §2.9, §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "a plate-bill surcharge of fifteen percent of `gross_toll_cents`
# is added — concretely, `gross_toll_cents` multiplied by 1500 basis points"
PLATE_BILL_SURCHARGE_BPS: int = 1500

# PRD §2.9 / §3.7: surcharge_bps and discount_bps bounds — "between 0 and
# 5000 inclusive"
INTEROP_BPS_MIN: int = 0
INTEROP_BPS_MAX: int = 5000


# ---------------------------------------------------------------------------
# Fines & violations — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
# PRD §3.5: civil penalty floors per reason_code.
#   "an `UNREAD_TRANSPONDER_NO_PLATE` violation incurs a civil penalty of
#    5000 cents, an `INSUFFICIENT_FUNDS_ON_PLATE_BILL` violation incurs
#    2500 cents, a `BLOCKED_VEHICLE` violation incurs 7500 cents, and an
#    `HOV_FRAUD` violation incurs 10000 cents."
BASE_PENALTY = {
    "UNREAD_TRANSPONDER_NO_PLATE": 5000,
    "INSUFFICIENT_FUNDS_ON_PLATE_BILL": 2500,
    "BLOCKED_VEHICLE": 7500,
    "HOV_FRAUD": 10000,
}

# PRD §3.6: "The sweep adds a late penalty of 2000 cents to both
# `amount_cents` and `civil_penalty_cents`"
LATE_PENALTY_CENTS: int = 2000

# PRD §3.5: "due_at exactly thirty days after issued_at"
FINE_DUE_AFTER_DAYS: int = 30

# PRD §3.5: "When that total reaches or exceeds 15000 cents — the suspension
# threshold"
SUSPEND_THRESHOLD_CENTS: int = 15000


# ---------------------------------------------------------------------------
# Dispute — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "A new dispute is permitted only when the fine's `dispute_count`
# is strictly less than 2"
DISPUTE_MAX_COUNT: int = 2


# ---------------------------------------------------------------------------
# Reload — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "amount_cents, which must be an integer between 100 and 50000
# inclusive"
MANUAL_RELOAD_MIN_CENTS: int = 100
MANUAL_RELOAD_MAX_CENTS: int = 50000


# ---------------------------------------------------------------------------
# Void window — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "An `AgencyAdmin` may void a toll event by referencing the
# event's id, but only within 24 hours of its `created_at`"
VOID_WINDOW_HOURS: int = 24


# ---------------------------------------------------------------------------
# Test defaults — useful in factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "HOLDER_NAME": "Test Holder",
    "HOME_AGENCY_CODE": "NY_EZPASS",
    "PLATE_STATE_DEFAULT": "NY",
    "PAYMENT_METHOD_TOKEN": "pmt_test_token_001",
    "GANTRY_ID": "G1",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "AUTO_RELOAD_THRESHOLD_MIN_CENTS",
    "AUTO_RELOAD_THRESHOLD_MAX_CENTS",
    "AUTO_RELOAD_THRESHOLD_DEFAULT_CENTS",
    "AUTO_RELOAD_TOPUP_MIN_CENTS",
    "AUTO_RELOAD_TOPUP_MAX_CENTS",
    "AUTO_RELOAD_TOPUP_DEFAULT_CENTS",
    "HOLDER_NAME_MIN_LEN",
    "HOLDER_NAME_MAX_LEN",
    "PLATE_NUMBER_MIN_LEN",
    "PLATE_NUMBER_MAX_LEN",
    "AXLE_COUNT_MIN",
    "AXLE_COUNT_MAX",
    "AXLE_COUNT_DEFAULT",
    "CLASS_MULTIPLIER",
    "AXLE_CLASS_MAP",
    "SERIAL_NUMBER_MIN_LEN",
    "SERIAL_NUMBER_MAX_LEN",
    "GANTRY_ID_MIN_LEN",
    "GANTRY_ID_MAX_LEN",
    "DECLARED_OCCUPANTS_MIN",
    "DECLARED_OCCUPANTS_MAX",
    "DECLARED_OCCUPANTS_DEFAULT",
    "HOV_MIN_OCCUPANTS",
    "PLATE_BILL_SURCHARGE_BPS",
    "INTEROP_BPS_MIN",
    "INTEROP_BPS_MAX",
    "BASE_PENALTY",
    "LATE_PENALTY_CENTS",
    "FINE_DUE_AFTER_DAYS",
    "SUSPEND_THRESHOLD_CENTS",
    "DISPUTE_MAX_COUNT",
    "MANUAL_RELOAD_MIN_CENTS",
    "MANUAL_RELOAD_MAX_CENTS",
    "VOID_WINDOW_HOURS",
    "TEST_DEFAULTS",
]
