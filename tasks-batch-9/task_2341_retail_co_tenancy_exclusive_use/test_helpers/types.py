"""Domain types for the Retail Co-Tenancy & Exclusive Use Administration API.

Entity shapes, status enums and the role enum, all drawn from the PRD.
Records that expose ``updated_at``/``version`` are distinguished from the one
immutable record (``AnchorRequirement``), which carries only ``id`` and
``created_at`` per PRD §2.4.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    LEASE_ADMINISTRATOR = "LeaseAdministrator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ASSET_MANAGER = "AssetManager"
    TENANT_REP = "TenantRep"
    LENDER_REP = "LenderRep"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    BREACH = "BREACH"
    FROZEN = "FROZEN"


class RedevelopmentStatus(str, Enum):
    NONE = "NONE"
    PLANNED = "PLANNED"
    RECORDED = "RECORDED"


class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    BANKRUPT = "BANKRUPT"


class PremisesStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    OPEN = "OPEN"
    DARK = "DARK"
    TERMINATED = "TERMINATED"


class RemedyStatus(str, Enum):
    NONE = "NONE"
    ELIGIBLE = "ELIGIBLE"
    REMEDY_ACTIVE = "REMEDY_ACTIVE"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED_BY_REMEDY = "TERMINATED_BY_REMEDY"


class UseComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    UNDER_NOTICE = "UNDER_NOTICE"
    IN_VIOLATION = "IN_VIOLATION"


class ParcelKind(str, Enum):
    INLINE = "INLINE"
    ANCHOR_BOX = "ANCHOR_BOX"
    PAD = "PAD"


class ConditionKind(str, Enum):
    OPENING = "OPENING"
    ONGOING = "ONGOING"


class MeasurementBasis(str, Enum):
    GLA_PCT = "GLA_PCT"
    STORE_COUNT = "STORE_COUNT"


class RemedyType(str, Enum):
    RENT_REDUCTION_ONLY = "RENT_REDUCTION_ONLY"
    RENT_REDUCTION_THEN_TERMINATION = "RENT_REDUCTION_THEN_TERMINATION"
    TERMINATION_ONLY = "TERMINATION_ONLY"


class ConditionStatus(str, Enum):
    SATISFIED = "SATISFIED"
    BREACHED = "BREACHED"
    CURED = "CURED"
    WAIVED = "WAIVED"


class ExclusivityScope(str, Enum):
    CENTER_WIDE = "CENTER_WIDE"
    PAD_EXCLUDED = "PAD_EXCLUDED"
    RADIUS_INCLUSIVE = "RADIUS_INCLUSIVE"


class ClauseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class MeasuredFrom(str, Enum):
    CENTER_BOUNDARY = "CENTER_BOUNDARY"
    PREMISES_CENTROID = "PREMISES_CENTROID"


class RecaptureBasis(str, Enum):
    GROSS_SALES = "GROSS_SALES"
    INCREMENTAL_SALES = "INCREMENTAL_SALES"


class RestrictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class NoticeKind(str, Enum):
    EXCLUSIVE_USE = "EXCLUSIVE_USE"
    PROHIBITED_USE = "PROHIBITED_USE"
    RADIUS = "RADIUS"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class DisputeGrounds(str, Enum):
    NO_PROHIBITED_USE = "NO_PROHIBITED_USE"
    CARVE_OUT_APPLIES = "CARVE_OUT_APPLIES"
    CLAUSE_EXPIRED = "CLAUSE_EXPIRED"
    SCOPE_INAPPLICABLE = "SCOPE_INAPPLICABLE"


class DisputeStatus(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ElectionKind(str, Enum):
    RENT_REDUCTION = "RENT_REDUCTION"
    TERMINATION = "TERMINATION"
    SUBSTITUTE_RENT = "SUBSTITUTE_RENT"


class ElectionStatus(str, Enum):
    ELECTED = "ELECTED"
    REDUCTION_ACTIVE = "REDUCTION_ACTIVE"
    TERMINATION_SCHEDULED = "TERMINATION_SCHEDULED"
    RESCINDED = "RESCINDED"
    CONSUMMATED = "CONSUMMATED"


class MeasurementVariant(str, Enum):
    SNAPSHOT_STRICT = "SNAPSHOT_STRICT"
    TRAILING_GRACE = "TRAILING_GRACE"


class MeasurementStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class CertificateStatus(str, Enum):
    REQUESTED = "REQUESTED"
    TENANT_SIGNED = "TENANT_SIGNED"
    LENDER_ACCEPTED = "LENDER_ACCEPTED"
    STALE = "STALE"
    REJECTED = "REJECTED"


class PlanKind(str, Enum):
    PAD_SALE = "PAD_SALE"
    REDEMISE = "REDEMISE"
    EXPANSION = "EXPANSION"


class PlanStatus(str, Enum):
    PLANNED = "PLANNED"
    CONSENT_PENDING = "CONSENT_PENDING"
    RECORDED = "RECORDED"
    ABANDONED = "ABANDONED"


class ScreenDecision(str, Enum):
    CLEAR = "CLEAR"
    CONFLICT = "CONFLICT"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class ShoppingCenter(TypedDict):
    id: str
    name: str
    total_gla_sqft: int
    occupancy_grace_days: int
    occupied_gla_sqft: int
    open_occupancy_pct: float
    operating_store_count: int
    open_anchor_count: int
    protected_exclusive_count: int
    aggregate_effective_rent_cents: int
    open_violation_count: int
    compliance_posture: str
    redevelopment_status: str
    last_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    legal_name: str
    notice_email: str
    primary_use_code: str
    is_national_chain: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    center_id: str
    tenant_id: str
    replacement_for_lease_id: Optional[str]
    suite_code: str
    gla_sqft: int
    parcel_kind: str
    is_anchor: bool
    primary_use_code: str
    incidental_use_codes: List[str]
    projected_incidental_sales_pct: float
    base_rent_monthly_cents: int
    commencement_date: str
    expiration_date: str
    premises_status: str
    remedy_status: str
    use_compliance_status: str
    opened_at: Optional[str]
    dark_since: Optional[str]
    remedy_eligible_at: Optional[str]
    effective_rent_monthly_cents: int
    total_abated_cents: int
    created_at: str
    updated_at: str
    version: int


class CoTenancyCondition(TypedDict):
    id: str
    lease_id: str
    condition_kind: str
    measurement_basis: str
    required_occupancy_pct: Optional[float]
    required_open_store_count: Optional[int]
    required_anchor_count: int
    grace_period_days: int
    cure_period_days: int
    remedy_type: str
    max_reduction_pct: float
    status: str
    breach_detected_at: Optional[str]
    consecutive_breach_days: int
    last_evaluated_measurement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnchorRequirement(TypedDict):
    """Immutable record: PRD §2.4 pins it to ``id`` and ``created_at`` only."""

    id: str
    condition_id: str
    anchor_lease_id: str
    substitution_allowed: bool
    min_substitute_gla_sqft: int
    created_at: str


class ExclusiveUseClause(TypedDict):
    id: str
    lease_id: str
    protected_use_codes: List[str]
    exclusivity_scope: str
    gla_carve_out_sqft: int
    incidental_sales_pct_cap: float
    effective_from_date: str
    effective_through_date: str
    status: str
    suspended_by_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RadiusRestriction(TypedDict):
    id: str
    lease_id: str
    radius_miles: float
    measured_from: str
    recapture_basis: str
    recapture_pct: float
    protected_baseline_cents: int
    window_from_date: str
    window_through_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UseViolationNotice(TypedDict):
    id: str
    violating_lease_id: str
    clause_id: Optional[str]
    radius_restriction_id: Optional[str]
    notice_kind: str
    narrative: str
    issued_by_user_id: str
    issued_at: str
    cure_period_days: int
    cure_deadline_at: str
    cure_restart_count: int
    reported_offending_sales_cents: int
    recapture_assessed_cents: int
    status: str
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UseViolationDispute(TypedDict):
    id: str
    notice_id: str
    filed_by_tenant_id: str
    grounds_code: str
    narrative: str
    cure_extension_days: int
    status: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemedyElection(TypedDict):
    id: str
    lease_id: str
    condition_id: Optional[str]
    source_notice_id: Optional[str]
    election_kind: str
    window_from_date: str
    window_through_date: str
    elected_at: str
    shortfall_pct_at_election: float
    anchor_bonus_applied: bool
    reduction_pct: float
    reduced_rent_monthly_cents: int
    termination_effective_date: Optional[str]
    abated_to_date_cents: int
    status: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OccupancyMeasurement(TypedDict):
    id: str
    center_id: str
    variant: str
    window_from_date: str
    window_through_date: str
    measured_at: str
    total_gla_sqft: int
    occupied_gla_sqft: int
    gla_occupancy_pct: float
    open_store_count: int
    open_anchor_count: int
    counted_lease_count: int
    excluded_lease_count: int
    breached_condition_count: int
    status: str
    created_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstoppelCertificate(TypedDict):
    id: str
    lease_id: str
    measurement_id: Optional[str]
    requested_by_user_id: str
    pinned_lease_version: int
    expedite_requested: bool
    disclosed_cotenancy_breach: bool
    disclosed_exclusive_count: int
    disclosed_effective_rent_cents: int
    base_fee_cents: int
    total_fee_cents: int
    lender_conditions_met: bool
    status: str
    signed_at: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedevelopmentPlan(TypedDict):
    id: str
    center_id: str
    pad_parcel_lease_id: Optional[str]
    plan_kind: str
    removed_gla_sqft: int
    gla_after_sqft: int
    impacted_clause_count: int
    impacted_condition_count: int
    consent_required: bool
    status: str
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
