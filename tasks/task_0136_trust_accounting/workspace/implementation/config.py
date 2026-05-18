"""Server-wide configuration constants for the Trust Accounting API."""
from __future__ import annotations

import os
from decimal import Decimal

PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# Auth header names (PRD §2.1, scaffold §1.4 priority 1).
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Roles recognised by the system (PRD §2.1).
ROLES = {"Grantor", "Trustee", "Beneficiary", "TaxPreparer", "Auditor"}

# Pagination defaults (PRD §2.3 / scaffold §1.0 response_envelope).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# GST / tax calculation constants (scaffold §1.3).
GST_EXEMPTION_LIMIT = Decimal("13610000.00")
GST_TAX_RATE = Decimal("0.40")
GST_GENERATION_GAP_YEARS = Decimal("37.5")

# Compressed trust tax brackets (scaffold §1.3 trust_income_tax_computation).
TRUST_TAX_BRACKETS = [
    (Decimal("0.00"), Decimal("3100.00"), Decimal("0.10")),
    (Decimal("3100.00"), Decimal("11150.00"), Decimal("0.24")),
    (Decimal("11150.00"), Decimal("15200.00"), Decimal("0.35")),
    (Decimal("15200.00"), None, Decimal("0.37")),  # None = infinity
]

# Enumerations used across the API.
TRUST_TYPES = {"REVOCABLE", "IRREVOCABLE"}
GRANTOR_TAX_STATUSES = {"GRANTOR", "NON_GRANTOR"}
TRUST_STATUSES = {"DRAFT", "ACTIVE", "TERMINATED", "REVOKED"}

TRUSTEE_STATUSES = {"ACTIVE", "RESIGNED", "REMOVED"}

BENEFICIARY_RELATION_CLASSES = {
    "SPOUSE", "CHILD", "GRANDCHILD", "OTHER_LINEAL", "NON_LINEAL"
}
BENEFICIARY_CLASSES = {"INCOME", "REMAINDER", "INCOME_AND_REMAINDER"}
DISTRIBUTION_TIERS = {"TIER_1", "TIER_2"}
BENEFICIARY_STATUSES = {"ACTIVE", "TERMINATED"}

ASSET_CLASSES = {"CASH", "EQUITY", "BOND", "REAL_ESTATE", "OTHER"}
ASSET_CLASSIFICATIONS = {"PRINCIPAL", "INCOME"}
ASSET_STATUSES = {"FUNDED", "DISTRIBUTED", "SOLD"}

TXN_TYPES = {
    "INCOME_ORDINARY", "INCOME_INTEREST", "INCOME_DIVIDEND", "INCOME_CAPITAL_GAIN",
    "EXPENSE_ADMINISTRATIVE", "EXPENSE_INVESTMENT",
}
INCOME_TXN_TYPES = {
    "INCOME_ORDINARY", "INCOME_INTEREST", "INCOME_DIVIDEND", "INCOME_CAPITAL_GAIN",
}
EXPENSE_TXN_TYPES = {"EXPENSE_ADMINISTRATIVE", "EXPENSE_INVESTMENT"}
PRINCIPAL_OR_INCOME = {"PRINCIPAL", "INCOME"}

DISTRIBUTION_TYPES = {"MANDATORY", "DISCRETIONARY", "TERMINATING"}
DISTRIBUTION_STATUSES = {"PROPOSED", "APPROVED", "EXECUTED", "REJECTED"}

TAX_YEAR_STATUSES = {"OPEN", "CLOSING", "CLOSED", "AMENDED"}
K1_STATUSES = {"DRAFT", "ISSUED", "SUPERSEDED"}
