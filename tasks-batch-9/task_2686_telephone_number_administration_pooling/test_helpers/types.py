"""Domain types for the telephone number administration and pooling API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CARRIER_REPRESENTATIVE = "CarrierRepresentative"
    NUMBERING_ADMINISTRATOR = "NumberingAdministrator"
    REGULATORY_APPROVER = "RegulatoryApprover"
    PORTING_OPERATIONS = "PortingOperations"
    PUBLIC_COMMENTER = "PublicCommenter"


class CarrierType(str, Enum):
    ILEC = "ILEC"
    CLEC = "CLEC"
    WIRELESS = "WIRELESS"
    VOIP_INTERCONNECTED = "VOIP_INTERCONNECTED"


class LicenseStatus(str, Enum):
    NONE = "NONE"
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class LicenseAction(str, Enum):
    GRANT = "GRANT"
    RENEW = "RENEW"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    REVOKE = "REVOKE"


class FacilitiesReadinessStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    ATTESTED = "ATTESTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class ReadinessEvent(str, Enum):
    ATTEST = "ATTEST"
    VERIFY = "VERIFY"
    FAIL = "FAIL"


class EligibilityStatus(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class NpaType(str, Enum):
    GEOGRAPHIC = "GEOGRAPHIC"
    OVERLAY = "OVERLAY"


class NpaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    JEOPARDY = "JEOPARDY"
    RELIEF_PLANNED = "RELIEF_PLANNED"
    EXHAUSTED = "EXHAUSTED"
    RETIRED = "RETIRED"


class PoolingStatus(str, Enum):
    NON_POOLED = "NON_POOLED"
    TRANSITIONAL = "TRANSITIONAL"
    POOLED = "POOLED"


class PoolingTransition(str, Enum):
    BEGIN_POOLING = "BEGIN_POOLING"
    COMPLETE_POOLING = "COMPLETE_POOLING"
    REVERT = "REVERT"


class AllocationStatus(str, Enum):
    POOL_AVAILABLE = "POOL_AVAILABLE"
    RESERVED = "RESERVED"
    ASSIGNED = "ASSIGNED"
    RECLAMATION_PENDING = "RECLAMATION_PENDING"
    AGING = "AGING"
    RETIRED = "RETIRED"


class RoutingStatus(str, Enum):
    UNROUTED = "UNROUTED"
    ROUTING_PENDING = "ROUTING_PENDING"
    LERG_PUBLISHED = "LERG_PUBLISHED"
    PORT_LOCKED = "PORT_LOCKED"
    ROUTING_WITHDRAWN = "ROUTING_WITHDRAWN"


class RequestType(str, Enum):
    INITIAL = "INITIAL"
    GROWTH = "GROWTH"
    POOL_REPLENISH = "POOL_REPLENISH"
    SAFETY_VALVE = "SAFETY_VALVE"


class AllocationRequestStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ReviewAction(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_INFO = "REQUEST_INFO"
    DENY = "DENY"
    WITHDRAW = "WITHDRAW"


class DenialReason(str, Enum):
    UTILIZATION_BELOW_THRESHOLD = "UTILIZATION_BELOW_THRESHOLD"
    POOL_INSUFFICIENT = "POOL_INSUFFICIENT"
    CARRIER_PROBATION = "CARRIER_PROBATION"
    REVIEWER_DENIED = "REVIEWER_DENIED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FindingType(str, Enum):
    NO_DISCREPANCY = "NO_DISCREPANCY"
    UNDERSTATED_UTILIZATION = "UNDERSTATED_UTILIZATION"
    OVERSTATED_UTILIZATION = "OVERSTATED_UTILIZATION"
    MISSING_DATA = "MISSING_DATA"


class PenaltyAction(str, Enum):
    NONE = "NONE"
    PROBATION = "PROBATION"
    RECLAMATION_REFERRAL = "RECLAMATION_REFERRAL"


class AuditFindingStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Disposition(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class ReclamationReason(str, Enum):
    ACTIVATION_DEADLINE_MISSED = "ACTIVATION_DEADLINE_MISSED"
    UTILIZATION_SHORTFALL = "UTILIZATION_SHORTFALL"
    LICENSE_REVOKED = "LICENSE_REVOKED"
    VOLUNTARY_RETURN = "VOLUNTARY_RETURN"


class ReclamationOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    SURRENDER_ACKNOWLEDGED = "SURRENDER_ACKNOWLEDGED"
    APPEAL_PENDING = "APPEAL_PENDING"
    WITHDRAWN = "WITHDRAWN"
    EXECUTED = "EXECUTED"


class ReclamationOrderAction(str, Enum):
    SURRENDER = "SURRENDER"
    APPEAL = "APPEAL"
    EXECUTE = "EXECUTE"
    WITHDRAW = "WITHDRAW"


class ReliefType(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    ALL_SERVICES_OVERLAY = "ALL_SERVICES_OVERLAY"
    GEOGRAPHIC_SPLIT = "GEOGRAPHIC_SPLIT"


class ReliefPlanStatus(str, Enum):
    PLANNING = "PLANNING"
    PUBLIC_COMMENT = "PUBLIC_COMMENT"
    OVERLAY_RECOMMENDED = "OVERLAY_RECOMMENDED"
    SPLIT_RECOMMENDED = "SPLIT_RECOMMENDED"
    ORDERED = "ORDERED"
    WITHDRAWN = "WITHDRAWN"


class ReliefPlanTransition(str, Enum):
    OPEN_COMMENT = "OPEN_COMMENT"
    CLOSE_AND_RECOMMEND = "CLOSE_AND_RECOMMEND"
    ORDER = "ORDER"
    WITHDRAW = "WITHDRAW"


class CommenterType(str, Enum):
    CONSUMER = "CONSUMER"
    BUSINESS = "BUSINESS"
    CARRIER = "CARRIER"
    GOVERNMENT = "GOVERNMENT"


class CommentPosition(str, Enum):
    SUPPORT_OVERLAY = "SUPPORT_OVERLAY"
    SUPPORT_SPLIT = "SUPPORT_SPLIT"
    OPPOSE_BOTH = "OPPOSE_BOTH"


class PortRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONCURRED = "CONCURRED"
    ACTIVATED = "ACTIVATED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    SNAPPED_BACK = "SNAPPED_BACK"


class PortRequestAction(str, Enum):
    CONCUR = "CONCUR"
    REJECT = "REJECT"
    ACTIVATE = "ACTIVATE"
    CANCEL = "CANCEL"


class RoutingRecordStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


# --- Entity shapes -----------------------------------------------------------
# Carrier, NPA, RateCenter, NumberBlock, AllocationRequest, UtilizationFiling,
# AuditFinding, ReclamationOrder, ReliefPlan and PortRequest all carry the
# mutable-identity quartet: id, created_at, updated_at, version.
# PublicComment and RoutingRecord are append-only: id and created_at only.


class Carrier(TypedDict):
    id: str
    ocn: str
    legal_name: str
    carrier_type: str
    home_state_code: str
    months_in_operation: int
    license_status: str
    license_expires_on: Optional[str]
    facilities_readiness_status: str
    switch_clli: Optional[str]
    interconnection_ready: bool
    eligibility_status: str
    blocks_held_count: int
    reclamation_strike_count: int
    safety_valve_grant_count: int
    probation_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NPA(TypedDict):
    id: str
    npa_code: str
    state_code: str
    npa_type: str
    relief_parent_npa_id: Optional[str]
    status: str
    available_block_count: int
    total_block_count: int
    exhaust_projection_months: float
    jeopardy_declared_at: Optional[str]
    permissive_dialing_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateCenter(TypedDict):
    id: str
    npa_id: str
    name: str
    state_code: str
    lata_code: str
    pooling_status: str
    pooling_effective_at: Optional[str]
    available_block_count: int
    assigned_block_count: int
    aggregate_utilization_pct: Optional[float]
    jeopardy_flag: bool
    accepts_initial_requests: bool
    pending_request_count: int
    last_donation_block_count: int
    donation_shortfall_count: int
    created_at: str
    updated_at: str
    version: int


class NumberBlock(TypedDict):
    id: str
    npa_id: str
    rate_center_id: str
    nxx_code: str
    thousands_digit: int
    block_label: str
    allocation_status: str
    routing_status: str
    holder_carrier_id: Optional[str]
    assigned_at: Optional[str]
    activation_due_at: Optional[str]
    activated_at: Optional[str]
    aging_release_at: Optional[str]
    contaminated_count: int
    is_pooling_eligible: bool
    current_lrn: Optional[str]
    npac_db_version: int
    created_at: str
    updated_at: str
    version: int


class AllocationRequest(TypedDict):
    id: str
    carrier_id: str
    rate_center_id: str
    request_type: str
    requested_block_count: int
    justification: Optional[str]
    status: str
    info_request_count: int
    utilization_pct_at_submission: Optional[float]
    months_to_exhaust_at_submission: Optional[float]
    granted_block_count: int
    assigned_block_ids: List[str]
    reviewer_user_id: Optional[str]
    approver_user_id: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    superseded_by_request_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilizationFiling(TypedDict):
    id: str
    carrier_id: str
    rate_center_id: str
    reporting_period: str
    numbers_assigned: int
    numbers_intermediate: int
    numbers_reserved: int
    numbers_aging: int
    numbers_administrative: int
    blocks_held_at_period_end: int
    forecast_quarters: List[int]
    status: str
    claimed_utilization_pct: Optional[float]
    strict_utilization_pct: Optional[float]
    audited_utilization_pct: Optional[float]
    submitted_at: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    utilization_filing_id: str
    auditor_user_id: str
    finding_type: str
    adjusted_numbers_assigned: Optional[int]
    adjusted_numbers_administrative: Optional[int]
    adjusted_utilization_pct: Optional[float]
    penalty_action: str
    status: str
    disposed_by_user_id: Optional[str]
    disposition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReclamationOrder(TypedDict):
    id: str
    number_block_id: str
    carrier_id: str
    reason: str
    status: str
    issued_at: str
    response_due_at: str
    executed_at: Optional[str]
    appeal_note: Optional[str]
    strike_applied: bool
    created_at: str
    updated_at: str
    version: int


class ReliefPlan(TypedDict):
    id: str
    npa_id: str
    planned_relief_type: str
    status: str
    comment_window_days: int
    comment_window_open_at: Optional[str]
    comment_window_close_at: Optional[str]
    recommended_relief_type: Optional[str]
    support_overlay_weight: Optional[float]
    support_split_weight: Optional[float]
    comment_count: int
    recommender_user_id: Optional[str]
    ordering_user_id: Optional[str]
    new_npa_code: Optional[str]
    effective_at: Optional[str]
    permissive_dialing_end_at: Optional[str]
    successor_npa_id: Optional[str]
    window_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortRequest(TypedDict):
    id: str
    telephone_number: str
    number_block_id: str
    from_carrier_id: str
    to_carrier_id: str
    requested_lrn: str
    desired_due_at: str
    status: str
    concurred_at: Optional[str]
    activated_at: Optional[str]
    closed_at: Optional[str]
    reject_reason: Optional[str]
    npac_db_version_at_activation: Optional[int]
    supersedes_port_request_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    """Append-only: carries id and created_at, never updated_at or version."""

    id: str
    relief_plan_id: str
    commenter_type: str
    position: str
    body: str
    weight: float
    submitted_at: str
    created_at: str


class RoutingRecord(TypedDict):
    """Append-only ledger row: carries id and created_at, never updated_at or version."""

    id: str
    number_block_id: str
    lrn: str
    ocn: str
    switch_clli: str
    effective_at: str
    end_at: Optional[str]
    record_status: str
    npac_db_version: int
    created_at: str
