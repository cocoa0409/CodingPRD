"""Domain types for the state insurance guaranty association API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    RECEIVER_LIAISON = "ReceiverLiaison"
    COVERAGE_ANALYST = "CoverageAnalyst"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    DEFENSE_COUNSEL = "DefenseCounsel"
    CLAIMS_COMMITTEE_OFFICER = "ClaimsCommitteeOfficer"
    ASSESSMENT_OFFICER = "AssessmentOfficer"
    MEMBER_INSURER_AGENT = "MemberInsurerAgent"


class LineOfBusiness(str, Enum):
    PERSONAL_AUTO = "PERSONAL_AUTO"
    HOMEOWNERS = "HOMEOWNERS"
    COMMERCIAL_GENERAL_LIABILITY = "COMMERCIAL_GENERAL_LIABILITY"
    WORKERS_COMPENSATION = "WORKERS_COMPENSATION"


class CapOrderMode(str, Enum):
    OFFSET_THEN_CAP = "OFFSET_THEN_CAP"
    CAP_THEN_OFFSET = "CAP_THEN_OFFSET"


class InsolvencyStatus(str, Enum):
    DECLARED = "DECLARED"
    TRIGGERED = "TRIGGERED"
    CLOSED = "CLOSED"


class MemberInsurerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IMPAIRED = "IMPAIRED"
    WITHDRAWN = "WITHDRAWN"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SETTLED = "SETTLED"


class BillingStatus(str, Enum):
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


class RecoupmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SURCHARGE_FILED = "SURCHARGE_FILED"
    RECOUPING = "RECOUPING"
    RECOUPED = "RECOUPED"


class ProofOfClaimTransferStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONVERTED = "CONVERTED"
    PARTIALLY_CONVERTED = "PARTIALLY_CONVERTED"
    REJECTED = "REJECTED"


class TransferredPolicyStatus(str, Enum):
    IMPORTED = "IMPORTED"
    CANCELLED_BY_ORDER = "CANCELLED_BY_ORDER"
    EXPIRED_BEFORE_ORDER = "EXPIRED_BEFORE_ORDER"


class CoveredClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENED_ELIGIBLE = "SCREENED_ELIGIBLE"
    DENIED_NOT_COVERED = "DENIED_NOT_COVERED"
    ADJUSTING = "ADJUSTING"
    RECOMMENDED = "RECOMMENDED"
    REFERRAL_PENDING = "REFERRAL_PENDING"
    REFERRED_OUT = "REFERRED_OUT"
    APPROVED = "APPROVED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class CapBinding(str, Enum):
    NONE = "NONE"
    PER_CLAIM = "PER_CLAIM"
    PER_POLICY_AGGREGATE = "PER_POLICY_AGGREGATE"


class OtherInsuranceStatus(str, Enum):
    UNEXHAUSTED = "UNEXHAUSTED"
    PURSUING = "PURSUING"
    EXHAUSTED = "EXHAUSTED"
    CARRIER_DENIED = "CARRIER_DENIED"


class CoverageType(str, Enum):
    PRIMARY = "PRIMARY"
    EXCESS = "EXCESS"
    UMBRELLA = "UMBRELLA"


class VendorType(str, Enum):
    ADJUSTER = "ADJUSTER"
    DEFENSE_COUNSEL = "DEFENSE_COUNSEL"


class VendorAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class RefundMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


class UnearnedPremiumRefundStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class ReferralBasis(str, Enum):
    POLICYHOLDER_RESIDENCE = "POLICYHOLDER_RESIDENCE"
    CLAIMANT_RESIDENCE = "CLAIMANT_RESIDENCE"
    PROPERTY_LOCATION = "PROPERTY_LOCATION"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ScreeningDecision(str, Enum):
    COVERED = "COVERED"
    DENIED = "DENIED"


class ReferralDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class Insolvency(TypedDict):
    """Insolvency file — carries id, created_at, updated_at and version."""

    id: str
    insurer_name: str
    naic_code: str
    domiciliary_state_code: str
    liquidation_order_date: str
    coverage_termination_date: Optional[str]
    proof_of_claim_deadline_utc: Optional[str]
    status: str
    triggered_at_utc: Optional[str]
    estate_remitted_cents: int
    estate_distributed_cents: int
    estate_undistributed_cents: int
    estate_returned_cents: int
    administrative_expense_cents: int
    administrative_paid_cents: int
    reserved_claim_cents: int
    pending_up_liability_cents: int
    referral_pending_count: int
    assessment_shortfall_cents: int
    distribution_sequence: int
    policy_count: int
    created_at: str
    updated_at: str
    version: int


class CoverageProfile(TypedDict):
    """Statutory coverage configuration row.

    The PRD states this row carries only ``id`` and ``created_at`` — there is no
    ``updated_at`` field and no ``version`` field at all.
    """

    id: str
    line_of_business: str
    per_claim_cap_cents: int
    per_policy_aggregate_cap_cents: int
    unearned_premium_cap_cents: int
    statutory_deductible_cents: int
    net_worth_exclusion_threshold_cents: int
    covers_punitive_damages: bool
    refund_priority_class: int
    cap_order_mode: str
    created_at: str


class MemberInsurer(TypedDict):
    id: str
    naic_code: str
    insurer_name: str
    assessable_line: str
    base_year: int
    direct_written_premium_cents: int
    annual_cap_rate_bps: int
    account_status: str
    sequence: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    insolvency_id: str
    assessable_line: str
    base_year: int
    needed_amount_cents: int
    status: str
    levied_amount_cents: int
    shortfall_cents: int
    member_count: int
    collected_amount_cents: int
    certified_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MemberAssessment(TypedDict):
    id: str
    assessment_id: str
    member_insurer_id: str
    premium_base_cents: int
    cap_amount_cents: int
    levied_amount_cents: int
    paid_amount_cents: int
    capped: bool
    billing_status: str
    recoupment_status: str
    surcharge_rate_bps: int
    surcharge_base_cents: int
    projected_recoupment_cents: int
    recouped_amount_cents: int
    sequence: int
    created_at: str
    updated_at: str
    version: int


class ProofOfClaimTransfer(TypedDict):
    id: str
    insolvency_id: str
    receiver_batch_ref: str
    records: List[dict]
    record_count: int
    converted_count: int
    rejected_count: int
    rejection_reasons: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferredPolicy(TypedDict):
    id: str
    insolvency_id: str
    source_transfer_id: Optional[str]
    policy_number: str
    line_of_business: str
    policyholder_name: str
    policyholder_state_code: str
    policyholder_net_worth_cents: int
    effective_date: str
    expiration_date: str
    annual_premium_cents: int
    large_deductible_cents: int
    self_insured_retention_cents: int
    collateral_held_cents: int
    status: str
    cancellation_date: Optional[str]
    unexpired_days: int
    aggregate_paid_cents: int
    up_refund_filed: bool
    created_at: str
    updated_at: str
    version: int


class CoveredClaim(TypedDict):
    id: str
    insolvency_id: str
    policy_id: str
    source_transfer_id: Optional[str]
    claim_number: str
    claimant_name: str
    claimant_state_code: str
    loss_date: str
    filed_at_utc: str
    gross_loss_cents: int
    punitive_damages_cents: int
    covered_basis_cents: int
    other_insurance_recoverable_cents: int
    attachment_point_cents: int
    covered_layer_cents: int
    net_payable_cents: int
    alt_net_payable_cents: int
    cap_binding: str
    paid_amount_cents: int
    status: str
    screened_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    recommended_by_vendor_name: Optional[str]
    recommended_amount_cents: Optional[int]
    recommended_at_utc: Optional[str]
    remand_count: int
    pre_referral_status: Optional[str]
    referred_to_state_code: Optional[str]
    denial_reason: Optional[str]
    sequence: int
    created_at: str
    updated_at: str
    version: int


class OtherInsuranceCoverage(TypedDict):
    id: str
    claim_id: str
    carrier_name: str
    policy_number: str
    coverage_type: str
    stated_limit_cents: int
    recovered_cents: int
    status: str
    sequence: int
    created_at: str
    updated_at: str
    version: int


class VendorAssignment(TypedDict):
    id: str
    claim_id: str
    vendor_type: str
    vendor_name: str
    settlement_authority_cents: int
    hourly_rate_cents: int
    engagement_start: str
    engagement_end: str
    hours_logged: float
    fees_accrued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UnearnedPremiumRefund(TypedDict):
    id: str
    policy_id: str
    refund_method: str
    computed_refund_cents: int
    alt_refund_cents: int
    capped: bool
    priority_class: int
    paid_amount_cents: int
    status: str
    sequence: int
    created_at: str
    updated_at: str
    version: int


class SisterAssociationReferral(TypedDict):
    id: str
    claim_id: str
    target_state_code: str
    basis: str
    basis_state_code: str
    status: str
    response_note: Optional[str]
    responded_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int
