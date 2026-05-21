"""Domain thresholds — numeric constants from PRD calculations.

Derived from PRD §3.6 (franchise tax base + late fee + total-due-with-
credit), §3.8 (BOI penalty), §3.9 (exposure score), §3.10 (compliance
derivation), and §3.11 (administrative-dissolution waiting period).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Franchise tax base — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6 (FLAT): "base_tax_cents is the constant 30,000 cents — that
# is, three hundred dollars — drawn from the configuration constant
# LLC_LP_FLAT_TAX_CENTS."
LLC_LP_FLAT_TAX_CENTS: int = 30000

# PRD §3.6 (AUTHORIZED_SHARES tiers):
# "when authorized shares are at most 5,000, the base tax is 17,500 cents"
# "when authorized shares are at most 10,000, the base tax is 25,000 cents"
# "when authorized shares exceed 10,000, the base tax is 25,000 cents plus
#  8,500 cents for each additional block of 10,000 shares"
CORP_TIER1_MAX_SHARES: int = 5000
CORP_TIER1_TAX_CENTS: int = 17500
CORP_TIER2_MAX_SHARES: int = 10000
CORP_TIER2_TAX_CENTS: int = 25000
CORP_TIER3_BLOCK_SHARES: int = 10000
CORP_TIER3_BLOCK_TAX_CENTS: int = 8500

# PRD §3.6 (ASSUMED_PAR_VALUE): "divides that figure by 100,000,000 cents
# (a million dollars), rounds the quotient up to the next whole integer
# (call that count 'millions'), and produces a base tax of millions
# multiplied by 40,000 cents."
ASSUMED_PAR_MILLION_CENTS: int = 100_000_000
ASSUMED_PAR_PER_MILLION_TAX_CENTS: int = 40000

# PRD §3.6 sanity rail (over-selection)
TAX_METHOD_SANITY_RATIO: float = 1.50


# ---------------------------------------------------------------------------
# Late fee — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "Multiply base_tax_cents by 0.015 (the constant
# MONTHLY_INTEREST_RATE, representing 1.5% per month) ... Add the
# constant LATE_FEE_FLAT_CENTS of 20,000 cents (a flat 200-dollar
# penalty). ... Cap that month count at 18"
MONTHLY_INTEREST_RATE: float = 0.015
LATE_FEE_FLAT_CENTS: int = 20000
LATE_FEE_MONTH_CAP: int = 18


# ---------------------------------------------------------------------------
# BOI penalty — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "the daily penalty constant of 59,100 cents ... the cap of
# 1,000,000 cents — that is, $591 per day up to a maximum of $10,000."
# PRD §3.8: "1,000,000 divided by 59,100 is 16 (integer floor)"
DAILY_PENALTY_CENTS: int = 59100
PENALTY_CAP_CENTS: int = 1_000_000
PENALTY_CAP_DAYS: int = 16  # floor(1_000_000 / 59100)


# ---------------------------------------------------------------------------
# Exposure score — PRD §3.9
# ---------------------------------------------------------------------------
# PRD §3.9: "a FOREIGN_PASSPORT carries a risk weight of 3 (the constant
# RISK_FOREIGN_PASSPORT), a STATE_ID carries a weight of 2 (the constant
# RISK_STATE_ID), and either a US_PASSPORT or a STATE_DRIVERS_LICENSE
# carries a default weight of 1 (the constant RISK_DEFAULT)."
RISK_FOREIGN_PASSPORT: int = 3
RISK_STATE_ID: int = 2
RISK_DEFAULT: int = 1


# ---------------------------------------------------------------------------
# Compliance windows — PRD §3.6, §3.8, §3.11
# ---------------------------------------------------------------------------
# PRD §3.6: "Once the clock moves past due_date plus 90 days, the
# assessment transitions to DELINQUENT."
TAX_DELINQUENCY_DAYS: int = 90

# PRD §3.8: "thirty days after the ownership change, if no UPDATE or
# CORRECTION BOIReport has been filed in the interim, the system
# transitions the report CURRENT → STALE"
BOI_STALE_TIMER_DAYS: int = 30

# PRD §3.11: "Its sole precondition is that the entity has been in
# compliance_status DELINQUENT for at least sixty days"
ADMIN_DISSOLUTION_WAIT_DAYS: int = 60

# PRD §3.2: "Entities whose agent has resigned must replace the agent
# within thirty days"
AGENT_REPLACEMENT_DAYS: int = 30

# PRD §3.7 / §3.10: "the certificate_of_good_standing_date is within
# sixty days of the current clock instant"
COGS_VALIDITY_DAYS: int = 60


# ---------------------------------------------------------------------------
# Ownership / basis points — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "ownership_percent_basis_points — an integer in the closed
# interval from 0 to 10,000, where 10,000 basis points equals 100%."
OWNERSHIP_FULL_BPS: int = 10000
OWNERSHIP_MIN_BPS: int = 0


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit defaults to 10 when omitted, has a minimum of 1,
# and a maximum of 100"
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — values used by factories when overrides are not supplied
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "ENTITY_NAME_PREFIX": "Acme Holdings",
    "HOME_STATE": "DE",
    "FOREIGN_STATE": "NY",
    "AGENT_ADDRESS": "100 Market Street",
    "PRINCIPAL_OFFICE_ADDRESS": "200 Corporate Plaza, Suite 300",
    "OFFICER_DIRECTOR_COUNT": 3,
    "AUTHORIZED_SHARES_DEFAULT": 5000,
    "RESPONSIBLE_PARTY_NAME": "Jane Roe",
    "SSN_LAST4": "1234",
    "TEMPLATE_VERSION": "1.0.0",
    "OWNER_NAME_PREFIX": "John Doe",
    "OWNER_ADDRESS": "500 Owner Avenue",
    "OWNER_DOC_NUMBER_PREFIX": "DL",
}


__all__ = [
    "LLC_LP_FLAT_TAX_CENTS",
    "CORP_TIER1_MAX_SHARES",
    "CORP_TIER1_TAX_CENTS",
    "CORP_TIER2_MAX_SHARES",
    "CORP_TIER2_TAX_CENTS",
    "CORP_TIER3_BLOCK_SHARES",
    "CORP_TIER3_BLOCK_TAX_CENTS",
    "ASSUMED_PAR_MILLION_CENTS",
    "ASSUMED_PAR_PER_MILLION_TAX_CENTS",
    "TAX_METHOD_SANITY_RATIO",
    "MONTHLY_INTEREST_RATE",
    "LATE_FEE_FLAT_CENTS",
    "LATE_FEE_MONTH_CAP",
    "DAILY_PENALTY_CENTS",
    "PENALTY_CAP_CENTS",
    "PENALTY_CAP_DAYS",
    "RISK_FOREIGN_PASSPORT",
    "RISK_STATE_ID",
    "RISK_DEFAULT",
    "TAX_DELINQUENCY_DAYS",
    "BOI_STALE_TIMER_DAYS",
    "ADMIN_DISSOLUTION_WAIT_DAYS",
    "AGENT_REPLACEMENT_DAYS",
    "COGS_VALIDITY_DAYS",
    "OWNERSHIP_FULL_BPS",
    "OWNERSHIP_MIN_BPS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
