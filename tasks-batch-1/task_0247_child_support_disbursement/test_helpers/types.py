"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as named in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles -----------------------------------------------------------------
class UserRole(str, Enum):
    CASE_WORKER = "CaseWorker"
    FINANCE_OFFICER = "FinanceOfficer"
    SUPERVISOR = "Supervisor"
    EMPLOYER = "Employer"
    CUSTODIAL_PARTY = "CustodialParty"


# --- Status / enum dimensions ---------------------------------------------
class AssistanceStatus(str, Enum):
    NEVER_ASSISTED = "NEVER_ASSISTED"
    FORMERLY_ASSISTED = "FORMERLY_ASSISTED"
    CURRENTLY_ASSISTED = "CURRENTLY_ASSISTED"


class PayeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"


class ArrearsDistributionRule(str, Enum):
    FAMILY_FIRST = "FAMILY_FIRST"
    STATE_FIRST = "STATE_FIRST"


class ObligationStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    MODIFIED = "MODIFIED"
    TERMINATED = "TERMINATED"


class EnforcementStatus(str, Enum):
    NONE = "NONE"
    INTERCEPT_PENDING = "INTERCEPT_PENDING"
    INTERCEPT_ACTIVE = "INTERCEPT_ACTIVE"
    LIFTED = "LIFTED"


class IwoStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    TERMINATED = "TERMINATED"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"
    RETURNED = "RETURNED"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    RETURNED = "RETURNED"


class DisbursementMethod(str, Enum):
    EFT = "EFT"
    CHECK = "CHECK"
    DEBIT_CARD = "DEBIT_CARD"


class ModificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class EnforcementActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CERTIFIED = "CERTIFIED"
    SATISFIED = "SATISFIED"
    WITHDRAWN = "WITHDRAWN"


class EntryType(str, Enum):
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    INTEREST = "INTEREST"
    DISBURSEMENT = "DISBURSEMENT"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerBucket(str, Enum):
    CURRENT_SUPPORT = "CURRENT_SUPPORT"
    INTEREST = "INTEREST"
    PRINCIPAL = "PRINCIPAL"


# --- Entity TypedDicts -----------------------------------------------------
# Entities below carry common_fields: id, created_at, updated_at, version.

class CustodialParty(TypedDict):
    id: str
    full_name: str
    state_code: str
    assistance_status: str
    payee_status: str
    created_at: str
    updated_at: str
    version: int


class NoncustodialParty(TypedDict):
    id: str
    full_name: str
    ssn_last4: str
    supports_second_family: bool
    total_current_support_cents: int
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    legal_name: str
    fein: str
    remittance_method: str
    created_at: str
    updated_at: str
    version: int


class SupportOrder(TypedDict):
    id: str
    custodial_party_id: str
    noncustodial_party_id: str
    current_support_cents: int
    frequency: str
    interest_rate_bps: int
    arrears_distribution_rule: str
    assigned_arrears_cents: int
    obligation_status: str
    enforcement_status: str
    current_support_due_cents: int
    arrears_principal_cents: int
    interest_balance_cents: int
    net_disbursed_to_family_cents: int
    last_interest_accrual_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeWithholdingOrder(TypedDict):
    id: str
    support_order_id: str
    employer_id: str
    ordered_amount_cents: int
    effective_start_at: str
    effective_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict):
    id: str
    employer_id: str
    noncustodial_party_id: str
    disposable_earnings_cents: int
    gross_remitted_cents: int
    ccpa_cap_cents: int
    distributable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    remittance_id: str
    support_order_id: str
    current_support_applied_cents: int
    interest_applied_cents: int
    principal_applied_cents: int
    total_applied_cents: int
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    support_order_id: str
    custodial_party_id: str
    allocation_id: str
    method: str
    family_amount_cents: int
    state_retained_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Modification(TypedDict):
    id: str
    support_order_id: str
    proposed_current_support_cents: int
    coverage_start_at: str
    coverage_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    support_order_id: str
    action_type: str
    certified_arrears_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# LedgerEntry is append-only (common_fields: false): id + created_at only.
# No updated_at, no version.
class LedgerEntry(TypedDict):
    id: str
    support_order_id: str
    entry_type: str
    bucket: str
    amount_cents: int
    source_ref: str
    effective_at: str
    created_at: str
