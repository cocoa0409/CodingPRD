"""Domain types: entity TypedDicts, status enums, role enum (PRD 3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    TREASURER = "Treasurer"
    CASHIER = "Cashier"
    COLLECTIONS_OFFICER = "CollectionsOfficer"
    RELIEF_OFFICER = "ReliefOfficer"
    TAXPAYER = "Taxpayer"


class CollectionStatus(str, Enum):
    CURRENT = "CURRENT"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


class SaleStatus(str, Enum):
    NONE = "NONE"
    IN_TAX_SALE = "IN_TAX_SALE"
    REDEEMED = "REDEEMED"
    SOLD = "SOLD"


class InstallmentStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


class ReliefStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    REDEEMED = "REDEEMED"
    SOLD = "SOLD"


class PropertyClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    AGRICULTURAL = "AGRICULTURAL"
    INDUSTRIAL = "INDUSTRIAL"


class ReliefClass(str, Enum):
    EXEMPTION = "EXEMPTION"
    ABATEMENT = "ABATEMENT"


class ReliefType(str, Enum):
    HOMESTEAD = "HOMESTEAD"
    SENIOR = "SENIOR"
    HARDSHIP = "HARDSHIP"
    DISABLED_VETERAN = "DISABLED_VETERAN"


class EntryType(str, Enum):
    CHARGE = "CHARGE"
    PENALTY = "PENALTY"
    INTEREST = "INTEREST"
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"
    ABATEMENT = "ABATEMENT"
    REFUND = "REFUND"


# ----- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) -----
class TaxYear(TypedDict):
    id: str
    year: int
    millage_rate: float
    first_installment_due_date: str
    second_installment_due_date: str
    created_at: str
    updated_at: str
    version: int


class EscrowAgent(TypedDict):
    id: str
    name: str
    servicer_code: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    parcel_number: str
    owner_name: str
    situs_address: str
    assessed_value_cents: int
    property_class: str
    homestead: bool
    escrow_agent_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxBill(TypedDict):
    id: str
    parcel_id: str
    tax_year_id: str
    gross_tax_cents: int
    exemption_credit_cents: int
    net_tax_cents: int
    abatement_credit_cents: int
    total_charged_cents: int
    total_paid_cents: int
    total_applied_cents: int
    balance_cents: int
    overpayment_cents: int
    delinquent_principal_cents: int
    collection_status: str
    sale_status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    bill_id: str
    sequence: int
    principal_due_cents: int
    due_date: str
    penalty_cents: int
    interest_cents: int
    paid_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxReliefApplication(TypedDict):
    id: str
    parcel_id: str
    tax_year_id: str
    relief_class: str
    relief_type: str
    claimed_amount_cents: int
    effective_from: str
    effective_to: str
    status: str
    approved_credit_cents: int
    info_request_count: int
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    bill_id: str
    amount_cents: int
    tender_type: str
    source: str
    escrow_agent_id: Optional[str]
    status: str
    allocation: List[dict]
    overpayment_applied_cents: int
    posted_by_user_id: str
    reversed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, id + created_at only (no updated_at, no version)
class LedgerEntry(TypedDict):
    id: str
    bill_id: str
    installment_sequence: Optional[int]
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str


class Refund(TypedDict):
    id: str
    bill_id: str
    amount_cents: int
    mode: str
    status: str
    approved_amount_cents: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxSaleReferral(TypedDict):
    id: str
    bill_id: str
    referral_date: str
    redemption_deadline: str
    delinquent_principal_at_referral_cents: int
    status: str
    created_by_user_id: str
    sold_by_user_id: Optional[str]
    sale_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
