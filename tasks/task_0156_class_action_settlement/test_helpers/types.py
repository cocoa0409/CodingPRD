"""Domain types: entity TypedDicts, status enums, role enum for the
Class Action Settlement Administration API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    SETTLEMENT_ADMIN = "SettlementAdmin"
    FUND_CONTROLLER = "FundController"
    CLAIMS_REVIEWER = "ClaimsReviewer"
    CLAIMS_ADMINISTRATOR = "ClaimsAdministrator"
    CLAIMANT = "Claimant"
    COURT = "Court"


# ─── Status enums ─────────────────────────────────────────────────────────
class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    NOTICE_OPEN = "NOTICE_OPEN"
    CLAIMS_OPEN = "CLAIMS_OPEN"
    CLAIMS_CLOSED = "CLAIMS_CLOSED"
    DISTRIBUTING = "DISTRIBUTING"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class DistributionMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    TIERED = "TIERED"


class ClassMemberStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    PARTICIPATING = "PARTICIPATING"
    EXCLUDED = "EXCLUDED"


class ClaimantTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"


class NoticeChannel(str, Enum):
    EMAIL = "EMAIL"
    MAIL = "MAIL"
    PUBLICATION = "PUBLICATION"


class DeliveryStatus(str, Enum):
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    RETURNED = "RETURNED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DEFICIENT = "DEFICIENT"
    CURED = "CURED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class DeficiencyReasonCode(str, Enum):
    MISSING_PROOF = "MISSING_PROOF"
    SIGNATURE_MISSING = "SIGNATURE_MISSING"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    EXPIRED = "EXPIRED"


class OptOutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    EFFECTIVE = "EFFECTIVE"
    REVOKED = "REVOKED"


class ObjectionStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"
    WITHDRAWN = "WITHDRAWN"


class DistributionBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class TaxFormType(str, Enum):
    MISC = "1099_MISC"
    NEC = "1099_NEC"


class TaxFormStatus(str, Enum):
    ISSUED = "ISSUED"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


class CyPresStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    REVOKED = "REVOKED"


class LedgerEntryType(str, Enum):
    FUND_OPEN = "FUND_OPEN"
    FEE_DEBIT = "FEE_DEBIT"
    ADMIN_DEBIT = "ADMIN_DEBIT"
    PAYMENT_DEBIT = "PAYMENT_DEBIT"
    PAYMENT_REVERSAL_CREDIT = "PAYMENT_REVERSAL_CREDIT"
    CY_PRES_DEBIT = "CY_PRES_DEBIT"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Full first-class entities carry id + created_at + updated_at + version.
class Settlement(TypedDict):
    id: str
    case_caption: str
    gross_fund_cents: int
    attorney_fee_cents: int
    admin_cost_cents: int
    distribution_method: str
    tier_a_amount_cents: int
    tier_b_amount_cents: int
    claim_filing_deadline: str
    objection_deadline: str
    cy_pres_floor_cents: int
    status: str
    net_distributable_cents: int
    allocated_cents: int
    residual_cents: int
    created_at: str
    updated_at: str
    version: int


class ClassMember(TypedDict):
    id: str
    settlement_id: str
    full_name: str
    email: str
    claimant_tier: str
    tin_on_file: bool
    status: str
    notice_count: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    settlement_id: str
    class_member_id: str
    supersedes_claim_id: Optional[str]
    claimed_loss_cents: int
    recognized_loss_cents: int
    status: str
    open_deficiency_count: int
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict):
    id: str
    claim_id: str
    reason_code: str
    cure_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OptOutRequest(TypedDict):
    id: str
    settlement_id: str
    class_member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict):
    id: str
    settlement_id: str
    class_member_id: str
    grounds: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionBatch(TypedDict):
    id: str
    settlement_id: str
    sequence_no: int
    status: str
    planned_total_cents: int
    posted_total_cents: int
    residual_after_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    distribution_batch_id: str
    claim_id: str
    gross_amount_cents: int
    withholding_cents: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxForm(TypedDict):
    id: str
    payment_id: str
    class_member_id: str
    form_type: str
    reportable_cents: int
    withheld_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CyPresDesignation(TypedDict):
    id: str
    settlement_id: str
    recipient_name: str
    share_bps: int
    status: str
    funded_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only audit rows (common_fields: false) — id + created_at ONLY.
class NoticeRecord(TypedDict):
    id: str
    class_member_id: str
    channel: str
    delivery_status: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    settlement_id: str
    entry_type: str
    amount_cents: int
    reference_id: str
    created_at: str
