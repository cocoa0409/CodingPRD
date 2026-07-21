"""Domain types: entity TypedDicts, status enums, role enum for the Subrogation Recovery API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    RECOVERY_SPECIALIST = "RecoverySpecialist"
    RECOVERY_MANAGER = "RecoveryManager"
    CARRIER_USER = "CarrierUser"
    FINANCE_OFFICER = "FinanceOfficer"
    SYSTEM = "System"
    ANY = "Any"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CommissionBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class ClaimStatus(str, Enum):
    REFERRED = "REFERRED"
    LIABILITY_ASSESSED = "LIABILITY_ASSESSED"
    DEMAND_ISSUED = "DEMAND_ISSUED"
    ARBITRATION = "ARBITRATION"
    SETTLED = "SETTLED"
    RECOVERED = "RECOVERED"
    WITHDRAWN = "WITHDRAWN"
    STATUTE_EXPIRED = "STATUTE_EXPIRED"


class DemandStatus(str, Enum):
    ISSUED = "ISSUED"
    HONORED = "HONORED"
    DISPUTED = "DISPUTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ArbitrationStatus(str, Enum):
    FILED = "FILED"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RESPONSE_FILED = "RESPONSE_FILED"
    DECIDED = "DECIDED"
    WITHDRAWN = "WITHDRAWN"


class SettlementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RecoveryPaymentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"
    BOUNCED = "BOUNCED"


class DeductibleReimbursementStatus(str, Enum):
    PENDING = "PENDING"
    DISBURSED = "DISBURSED"
    CLAWED_BACK = "CLAWED_BACK"


class CommissionStatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class DocType(str, Enum):
    POLICE_REPORT = "POLICE_REPORT"
    ESTIMATE = "ESTIMATE"
    POLICY = "POLICY"
    CORRESPONDENCE = "CORRESPONDENCE"
    OTHER = "OTHER"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Carrier(TypedDict):
    id: str
    name: str
    naic_code: str
    commission_rate_bps: int
    commission_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseParty(TypedDict):
    id: str
    name: str
    adverse_carrier_name: str
    is_arbitration_eligible: bool
    policy_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    carrier_id: str
    adverse_party_id: str
    claim_reference: str
    loss_date: str
    referral_date: str
    paid_loss_cents: int
    deductible_cents: int
    total_damages_cents: int
    statute_deadline: str
    liability_pct: Optional[float]
    provisional_recoverable_cents: Optional[int]
    settled_amount_cents: Optional[int]
    final_recovered_cents: int
    deductible_reimbursed_cents: int
    carrier_recovered_cents: int
    accrued_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Demand(TypedDict):
    id: str
    claim_id: str
    amount_demanded_cents: int
    issued_at: str
    response_due_at: str
    disputed_at: Optional[str]
    arbitration_window_due_at: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Arbitration(TypedDict):
    id: str
    claim_id: str
    forum: str
    filed_at: str
    hearing_start: Optional[str]
    hearing_end: Optional[str]
    rounds: List[dict]
    round_count: int
    award_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    claim_id: str
    settled_amount_cents: int
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryPayment(TypedDict):
    id: str
    claim_id: str
    amount_cents: int
    received_at: str
    alloc_deductible_cents: Optional[int]
    alloc_carrier_cents: Optional[int]
    alloc_commission_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeductibleReimbursement(TypedDict):
    id: str
    claim_id: str
    recovery_payment_id: str
    amount_cents: int
    disbursed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    carrier_id: str
    period_label: str
    lines: List[dict]
    total_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only evidence, carries ONLY id + created_at.
class ClaimDocument(TypedDict):
    id: str
    claim_id: str
    doc_type: str
    title: str
    uri: str
    created_at: str
