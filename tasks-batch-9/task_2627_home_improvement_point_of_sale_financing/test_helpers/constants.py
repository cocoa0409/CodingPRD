"""Program constants and the canonical reference-data literals used by fixtures.

Two kinds of value live here:

* **Program constants** — the numeric thresholds, tier tables and window lengths
  the PRD pins (FICO floor, DTI ceiling, reserve target rates, the speed
  surcharge, the per-draw holdback ceiling, and so on).
* **Canonical literals** — one concrete, reusable ROOFING programme: a trade
  rule, a deferred-interest promotion plan, a Texas roofer, its licence, a
  homeowner, a contract and a milestone layout.  Every fixture builds from
  these so that expected money figures can be written as exact integers.
"""

# ─── Logical clock ────────────────────────────────────

#: The instant the clock reads before it has ever been set.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ─── Units ────────────────────────────────────────────

BPS_ONE = 10000

# ─── Instant decision ─────────────────────────────────

FICO_FLOOR = 620
FICO_MIN = 300
FICO_MAX = 850
DTI_CEILING_BPS = 4500
MIN_WORTHWHILE_LIMIT_CENTS = 200000
OFFER_VALIDITY_DAYS = 14

#: (min_score, max_score, income_factor_bps, tier_cap_cents), closed bands.
FICO_TIERS = [
    (760, 850, 6000, 7500000),
    (700, 759, 4500, 5000000),
    (660, 699, 3000, 3000000),
    (620, 659, 2000, 1500000),
]

# ─── Disclosure ───────────────────────────────────────

DISCLOSURE_ACK_WINDOW_DAYS = 3

# ─── Project and staged funding ───────────────────────

SUBSTANTIAL_COMPLETION_BPS = 8000
FULL_RELEASE_BPS = 10000
MILESTONE_RELEASE_BUDGET_BPS = 10000

# ─── Settlement economics ─────────────────────────────

NEXT_DAY_SURCHARGE_BPS = 75
STANDARD_3DAY_SURCHARGE_BPS = 0

#: (minimum trailing-90-day volume in cents, credit in bps), first match wins.
VOLUME_TIER_CREDITS = [
    (50000000, 40),
    (20000000, 25),
    (5000000, 10),
]

PER_DRAW_HOLDBACK_CEILING_BPS = 1500

#: risk_tier -> reserve target rate in basis points.
RESERVE_TARGET_RATE_BPS = {
    "LOW": 200,
    "STANDARD": 400,
    "ELEVATED": 700,
    "HIGH": 1200,
}

SEASONING_SETTLED_DRAWS = 5
RESERVE_COVERAGE_FLOOR_BPS = 5000
FULL_COVERAGE_BPS = 10000

VELOCITY_WINDOW_DAYS = 7
RESERVE_TRAILING_WINDOW_DAYS = 180
VOLUME_TIER_TRAILING_WINDOW_DAYS = 90

# ─── Servicing ────────────────────────────────────────

DAYS_IN_YEAR = 365
DELINQUENCY_AFTER_DAYS = 30
CHARGE_OFF_AFTER_DAYS = 120
CURE_THRESHOLD_BPS = 500

# ─── Disputes ─────────────────────────────────────────

DISPUTE_RESPONSE_DAYS = 10
DISPUTE_REOPEN_WINDOW_DAYS = 30
CHARGEBACK_RECEIVABLE_CEILING_BPS = 5000

# ─── Fraud and portfolio ──────────────────────────────

SYSTEM_ALERT_SEVERITY_WEIGHT = 40
PHANTOM_SUSPENSION_THRESHOLD = 60
PHANTOM_SCORE_MAX = 100
SEVERITY_WEIGHT_MIN = 1
SEVERITY_WEIGHT_MAX = 100

#: grade -> (max dispute_rate_bps, max delinquency_rate_bps, max phantom_risk_score)
PORTFOLIO_GRADE_ROWS = [
    ("A", 200, 300, 20),
    ("B", 500, 700, 40),
    ("C", 1000, 1500, 60),
]

TERMINATION_DISPUTE_RATE_BPS = 2500

# ─── Pagination ───────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Canonical ROOFING trade rule ─────────────────────

ROOFING_TRADE_RULE = {
    "trade_type": "ROOFING",
    "max_ticket_cents": 5000000,
    "holdback_pct_bps": 500,
    "max_precompletion_release_bps": 7000,
    "velocity_cap_cents": 15000000,
    "requires_completion_certificate": True,
    "min_license_months": 6,
}

#: A second trade rule for cross-trade tests; certificate not required.
HVAC_TRADE_RULE = {
    "trade_type": "HVAC",
    "max_ticket_cents": 3000000,
    "holdback_pct_bps": 600,
    "max_precompletion_release_bps": 6000,
    "velocity_cap_cents": 8000000,
    "requires_completion_certificate": False,
    "min_license_months": 3,
}

# ─── Canonical promotion plans ────────────────────────

DISCLOSURE_TEMPLATE_VERSION = "DI-2026.2"

DEFERRED_INTEREST_PLAN = {
    "code": "DI12-ROOF",
    "promotion_type": "DEFERRED_INTEREST",
    "promo_term_months": 12,
    "deferred_apr_bps": 2699,
    "post_promo_apr_bps": 2699,
    "merchant_discount_bps": 525,
    "min_ticket_cents": 100000,
    "max_ticket_cents": 5000000,
    "disclosure_template_version": DISCLOSURE_TEMPLATE_VERSION,
    "allowed_trade_types": ["ROOFING", "GENERAL_REMODEL"],
}

#: A second plan on the same trades, used for enrollment-window tests.
SECOND_PLAN = {
    "code": "DI18-ROOF",
    "promotion_type": "DEFERRED_INTEREST",
    "promo_term_months": 18,
    "deferred_apr_bps": 2499,
    "post_promo_apr_bps": 2499,
    "merchant_discount_bps": 600,
    "min_ticket_cents": 100000,
    "max_ticket_cents": 5000000,
    "disclosure_template_version": "DI-2026.3",
    "allowed_trade_types": ["ROOFING", "GENERAL_REMODEL"],
}

#: A plan whose allowed_trade_types excludes ROOFING.
SOLAR_ONLY_PLAN = {
    "code": "DI12-SOLAR",
    "promotion_type": "DEFERRED_INTEREST",
    "promo_term_months": 12,
    "deferred_apr_bps": 2499,
    "post_promo_apr_bps": 2499,
    "merchant_discount_bps": 500,
    "min_ticket_cents": 100000,
    "max_ticket_cents": 5000000,
    "disclosure_template_version": "DI-2026.2",
    "allowed_trade_types": ["SOLAR"],
}

# ─── Canonical merchant and licence ───────────────────

CANONICAL_MERCHANT = {
    "legal_name": "Summit Roofing LLC",
    "trade_type": "ROOFING",
    "state_code": "TX",
    "contact_email": "ops@summitroof.example",
}

SECOND_MERCHANT = {
    "legal_name": "Lone Star Exteriors LLC",
    "trade_type": "ROOFING",
    "state_code": "TX",
    "contact_email": "ops@lonestarext.example",
}

CANONICAL_LICENSE = {
    "trade_type": "ROOFING",
    "license_number": "TX-RCF-88120",
    "state_code": "TX",
    "effective_from": "2026-01-01",
    "expires_on": "2027-06-30",
}

ATTESTATION_REF = "ATT-2026-0801"

# ─── Canonical enrollment window ──────────────────────

ENROLLMENT_WINDOW_START = "2026-08-01"
ENROLLMENT_WINDOW_END = "2026-12-31"
NEGOTIATED_DISCOUNT_BPS = 449

# ─── Canonical consumer, contract and milestones ──────

CANONICAL_CONSUMER = {
    "full_name": "Dana Ruiz",
    "ssn_last4": "4417",
    "annual_income_cents": 9600000,
    "fico_score": 742,
    "state_code": "TX",
}

SECOND_CONSUMER = {
    "full_name": "Miles Okafor",
    "ssn_last4": "9082",
    "annual_income_cents": 12000000,
    "fico_score": 771,
    "state_code": "TX",
}

#: Ticket used by the canonical application; inside both plan and trade ceilings.
CANONICAL_TICKET_CENTS = 3500000

#: The tier-derived ceiling for the canonical consumer: 9600000 * 4500 / 10000.
CANONICAL_APPROVED_LIMIT_CENTS = 4320000

#: (3500000 * 10000) / 9600000 rounded half up.
CANONICAL_DECISION_DTI_BPS = 3646

#: DEFAULT_CLOCK advanced fourteen days.
CANONICAL_OFFER_EXPIRES_AT = "2026-08-15T00:00:00Z"

#: DEFAULT_CLOCK date advanced twelve whole months.
CANONICAL_PROMO_EXPIRES_ON = "2027-08-01"

CANONICAL_PROJECT = {
    "scope_description": "Full roof replacement, 32 squares",
    "contract_amount_cents": 3500000,
}

CANONICAL_MILESTONES = [
    {"sequence_no": 1, "name": "Tear-off and deck inspection", "release_pct_bps": 3000},
    {"sequence_no": 2, "name": "Shingle installation", "release_pct_bps": 4000},
    {"sequence_no": 3, "name": "Flashing, gutters and final cleanup", "release_pct_bps": 3000},
]

EVIDENCE_REF = "EV-2026-0801-A"
SIGNATURE_REF = "SIG-DANA-RUIZ-0801"
COMPLETION_CERTIFICATE_REF = "CERT-2026-0810-ROOF"
