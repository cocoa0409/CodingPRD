"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Persisted resources carrying id + created_at + updated_at + version:
  Trust, Trustee, Beneficiary, Asset, Distribution, TaxYear, K1.
- Append-only event log carrying ONLY id + created_at: Transaction.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    GRANTOR = "Grantor"
    TRUSTEE = "Trustee"
    BENEFICIARY = "Beneficiary"
    TAX_PREPARER = "TaxPreparer"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class TrustStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    REVOKED = "REVOKED"


class TrustType(str, Enum):
    REVOCABLE = "REVOCABLE"
    IRREVOCABLE = "IRREVOCABLE"


class GrantorTaxStatus(str, Enum):
    GRANTOR = "GRANTOR"
    NON_GRANTOR = "NON_GRANTOR"


class TrusteeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RelationClass(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    GRANDCHILD = "GRANDCHILD"
    OTHER_LINEAL = "OTHER_LINEAL"
    NON_LINEAL = "NON_LINEAL"


class BeneficiaryClass(str, Enum):
    INCOME = "INCOME"
    REMAINDER = "REMAINDER"
    INCOME_AND_REMAINDER = "INCOME_AND_REMAINDER"


class DistributionTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class AssetClass(str, Enum):
    CASH = "CASH"
    EQUITY = "EQUITY"
    BOND = "BOND"
    REAL_ESTATE = "REAL_ESTATE"
    OTHER = "OTHER"


class AssetClassification(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    INCOME = "INCOME"


class AssetStatus(str, Enum):
    FUNDED = "FUNDED"
    DISTRIBUTED = "DISTRIBUTED"
    SOLD = "SOLD"


class TxnType(str, Enum):
    INCOME_ORDINARY = "INCOME_ORDINARY"
    INCOME_INTEREST = "INCOME_INTEREST"
    INCOME_DIVIDEND = "INCOME_DIVIDEND"
    INCOME_CAPITAL_GAIN = "INCOME_CAPITAL_GAIN"
    EXPENSE_ADMINISTRATIVE = "EXPENSE_ADMINISTRATIVE"
    EXPENSE_INVESTMENT = "EXPENSE_INVESTMENT"


class PrincipalOrIncome(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    INCOME = "INCOME"


class DistributionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class DistributionType(str, Enum):
    MANDATORY = "MANDATORY"
    DISCRETIONARY = "DISCRETIONARY"
    TERMINATING = "TERMINATING"


class TaxYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    AMENDED = "AMENDED"


class K1Status(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — id + created_at + updated_at + version per PRD §2.4
# ---------------------------------------------------------------------------
class Trust(TypedDict):
    id: str
    name: str
    trust_type: str
    grantor_tax_status: str
    has_grantor_powers: bool
    grantor_user_id: str
    situs_state: str
    inception_date: str
    status: str
    principal_balance: float
    income_balance: float
    gst_exemption_used: float
    current_tax_year_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trustee(TypedDict):
    id: str
    trust_id: str
    user_id: str
    full_name: str
    is_primary: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    trust_id: str
    full_name: str
    relation_class: str
    is_skip_person: bool
    beneficiary_class: str
    distribution_tier: str
    status: str
    birth_date: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    trust_id: str
    description: str
    asset_class: str
    book_value: float
    classification: str
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD §2.4 explicitly carves out Transaction: "no updated_at and no
# version". Append-only event log.
class Transaction(TypedDict):
    id: str
    trust_id: str
    tax_year_id: str
    txn_type: str
    amount: float
    transaction_date: str
    principal_or_income: str
    description: str
    created_at: str


class Distribution(TypedDict):
    id: str
    trust_id: str
    beneficiary_id: str
    tax_year_id: str
    scheduled_date: str
    amount_principal: float
    amount_income: float
    distribution_type: str
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    gst_taxable: bool
    gst_tax_amount: float
    created_at: str
    updated_at: str
    version: int


class TaxYear(TypedDict):
    id: str
    trust_id: str
    calendar_year: int
    start_date: str
    end_date: str
    status: str
    dni: float
    trust_taxable_income: float
    trust_income_tax: float
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class K1(TypedDict):
    id: str
    tax_year_id: str
    trust_id: str
    beneficiary_id: str
    ordinary_income_share: float
    interest_income_share: float
    dividend_income_share: float
    capital_gain_share: float
    total_distributed: float
    status: str
    snapshot_distribution_version_sum: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "TrustStatus",
    "TrustType",
    "GrantorTaxStatus",
    "TrusteeStatus",
    "BeneficiaryStatus",
    "RelationClass",
    "BeneficiaryClass",
    "DistributionTier",
    "AssetClass",
    "AssetClassification",
    "AssetStatus",
    "TxnType",
    "PrincipalOrIncome",
    "DistributionStatus",
    "DistributionType",
    "TaxYearStatus",
    "K1Status",
    "Trust",
    "Trustee",
    "Beneficiary",
    "Asset",
    "Transaction",
    "Distribution",
    "TaxYear",
    "K1",
]
