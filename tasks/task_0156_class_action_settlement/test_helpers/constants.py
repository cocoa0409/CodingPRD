"""Domain thresholds — numeric constants from the PRD's distribution and
cy-pres calculations (§2.6, §3.6, §3.8, §3.9)."""

# Tax reporting threshold: gross at or above this triggers backup withholding
# and tax-form issuance for a no-TIN claimant (PRD §3.6 / §3.9: 60000 cents).
TAX_REPORTING_THRESHOLD_CENTS = 60000

# Backup withholding rate, in basis points (PRD §3.6: 2400 bps = 24%).
BACKUP_WITHHOLDING_BPS = 2400

# Basis-point denominator for share and withholding math (PRD §2.6: 10000).
BPS_DENOMINATOR = 10000

# A closable settlement's ledger must net to exactly this (PRD §2.7).
EXPECTED_BALANCE_CENTS = 0

# A non-existent but well-formed UUID for not-found probes used in design recipes.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
