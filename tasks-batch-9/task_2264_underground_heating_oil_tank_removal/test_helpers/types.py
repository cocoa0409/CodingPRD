"""Domain types for the Oil Tank Remediation API.

The role enum, every status and enum member the PRD declares, and one TypedDict
per collection.  All twelve collections carry the same four system-managed
properties — ``id``, ``created_at``, ``updated_at`` and ``version`` — because the
PRD states that no entity in this system is exempt.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PROJECT_COORDINATOR = "ProjectCoordinator"
    FIELD_TECHNICIAN = "FieldTechnician"
    LAB_ANALYST = "LabAnalyst"
    HOMEOWNER = "Homeowner"
    LICENSED_SITE_PROFESSIONAL = "LicensedSiteProfessional"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class StateCode(str, Enum):
    NJ = "NJ"
    NY = "NY"
    CT = "CT"


class TankProjectStatus(str, Enum):
    INTAKE = "INTAKE"
    SURVEYED = "SURVEYED"
    DISCLOSED = "DISCLOSED"
    PERMITTED = "PERMITTED"
    DECOMMISSIONING = "DECOMMISSIONING"
    SAMPLING = "SAMPLING"
    ASSESSED = "ASSESSED"
    REMEDIATION_ACTIVE = "REMEDIATION_ACTIVE"
    CLEARED = "CLEARED"
    CLOSED_NFA = "CLOSED_NFA"
    CLOSED_SETTLED = "CLOSED_SETTLED"
    VOID = "VOID"


class ContaminationClass(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    CLEAN = "CLEAN"
    ELEVATED = "ELEVATED"
    GROSS = "GROSS"


class SurveyMethod(str, Enum):
    GPR = "GPR"
    MAGNETOMETER = "MAGNETOMETER"
    PROBE_ROD = "PROBE_ROD"


class TankMaterial(str, Enum):
    STEEL = "STEEL"
    FIBERGLASS = "FIBERGLASS"


class DecommissionMethod(str, Enum):
    REMOVAL = "REMOVAL"
    ABANDONMENT_IN_PLACE = "ABANDONMENT_IN_PLACE"


class RemediationVolumeBasis(str, Enum):
    PROVISIONAL_GRID = "PROVISIONAL_GRID"
    FINAL_SURVEYED = "FINAL_SURVEYED"


class DisclosureKind(str, Enum):
    SWEEP_FINDINGS = "SWEEP_FINDINGS"
    CONTAMINATION_FINDINGS = "CONTAMINATION_FINDINGS"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class DisclosureResponse(str, Enum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECLINED = "DECLINED"


class ResponseChannel(str, Enum):
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"
    WET_SIGNATURE = "WET_SIGNATURE"


class PermitType(str, Enum):
    MUNICIPAL_DECOMMISSION = "MUNICIPAL_DECOMMISSION"
    FIRE_MARSHAL_NOTIFICATION = "FIRE_MARSHAL_NOTIFICATION"


class PermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PermitDecision(str, Enum):
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class CertLevel(str, Enum):
    TANK_TECH_I = "TANK_TECH_I"
    TANK_TECH_II = "TANK_TECH_II"
    LSP_SUPERVISED = "LSP_SUPERVISED"


class WorkOrderFieldStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MOBILIZED = "MOBILIZED"
    IN_PROGRESS = "IN_PROGRESS"
    FIELD_COMPLETE = "FIELD_COMPLETE"
    ABORTED = "ABORTED"


class WorkOrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    RECONCILED = "RECONCILED"
    WRITTEN_OFF = "WRITTEN_OFF"


class FieldEvent(str, Enum):
    MOBILIZE = "MOBILIZE"
    START = "START"
    COMPLETE = "COMPLETE"
    ABORT = "ABORT"


class BillingEvent(str, Enum):
    INVOICE = "INVOICE"
    RECONCILE = "RECONCILE"
    WRITE_OFF = "WRITE_OFF"


class SamplePoint(str, Enum):
    TANK_BOTTOM = "TANK_BOTTOM"
    NORTH_SIDEWALL = "NORTH_SIDEWALL"
    SOUTH_SIDEWALL = "SOUTH_SIDEWALL"
    STOCKPILE = "STOCKPILE"
    CONFIRMATION_FLOOR = "CONFIRMATION_FLOOR"


class SampleStatus(str, Enum):
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_LAB = "AT_LAB"
    RESULTED = "RESULTED"
    INVALIDATED = "INVALIDATED"
    VOIDED = "VOIDED"


class CustodyEvent(str, Enum):
    DISPATCH = "DISPATCH"
    RECEIVE = "RECEIVE"
    VOID = "VOID"


class QcFlag(str, Enum):
    NONE = "NONE"
    HOLDING_TIME_EXCEEDED = "HOLDING_TIME_EXCEEDED"
    RESULT_RETRACTED = "RESULT_RETRACTED"


class DisposalClass(str, Enum):
    NON_HAZARDOUS = "NON_HAZARDOUS"
    HAZARDOUS = "HAZARDOUS"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ChangeOrderDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimVariant(str, Enum):
    PRELIMINARY_ESTIMATE = "PRELIMINARY_ESTIMATE"
    FINAL_SETTLEMENT = "FINAL_SETTLEMENT"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


class ClaimDecision(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class NfaLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"


class NotificationKind(str, Enum):
    FIRST_PARTY = "FIRST_PARTY"
    THIRD_PARTY_LIABILITY = "THIRD_PARTY_LIABILITY"


class NotificationStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    THIRD_PARTY_REVIEW = "THIRD_PARTY_REVIEW"
    CLOSED = "CLOSED"


class RevocationReason(str, Enum):
    HOMEOWNER_DECLINED = "HOMEOWNER_DECLINED"


class AbortReason(str, Enum):
    PROJECT_VOIDED = "PROJECT_VOIDED"
    PERMIT_REVOKED = "PERMIT_REVOKED"


# --------------------------------------------------------------------------- #
# The four system-managed properties every collection carries
# --------------------------------------------------------------------------- #
class SystemFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #
class Property(SystemFields):
    street_address: str
    state_code: str
    county_code: str
    homeowner_name: str
    homeowner_email: str
    insurance_carrier_code: str
    first_party_coverage_limit_cents: int
    third_party_sublimit_cents: int
    trust_fund_deductible_cents: int
    open_project_count: int


class TankProject(SystemFields):
    property_id: str
    status: str
    baseline_scope_cubic_yards: float
    excavation_limit_cubic_yards: float
    survey_method: Optional[str]
    tanks_detected_count: Optional[int]
    survey_completed_at: Optional[str]
    tank_capacity_gallons: Optional[int]
    tank_depth_to_top_inches: Optional[int]
    tank_distance_to_foundation_inches: Optional[int]
    tank_under_structure: Optional[bool]
    tank_material: Optional[str]
    method_score: Optional[float]
    recommended_method: Optional[str]
    decommission_method: Optional[str]
    sampling_round: int
    contamination_class: str
    max_tph_mg_kg: Optional[float]
    max_benzene_mg_kg: Optional[float]
    approved_scope_cubic_yards: float
    remediation_volume_cubic_yards: Optional[float]
    remediation_volume_basis: Optional[str]
    remediation_cost_cents: int
    remediation_started: bool
    contamination_disclosure_required: bool
    actual_excavated_cubic_yards: Optional[float]
    hauled_tons: Optional[float]
    nfa_blockers: List[str]


class TankProjectSummary(TypedDict):
    """The computed posture snapshot; not a stored row, so no system fields."""

    status: str
    contamination_class: str
    approved_scope_cubic_yards: float
    remediation_volume_cubic_yards: Optional[float]
    remediation_volume_basis: Optional[str]
    remediation_cost_cents: int
    nfa_blockers: List[str]
    version: int
    open_change_order_count: int
    current_round_sample_count: int


class HomeownerDisclosure(SystemFields):
    tank_project_id: str
    disclosure_kind: str
    status: str
    sent_at: str
    expires_at: str
    response: Optional[str]
    response_channel: Optional[str]
    responded_at: Optional[str]


class Permit(SystemFields):
    tank_project_id: str
    permit_type: str
    status: str
    submitted_at: str
    issued_at: Optional[str]
    expires_at: Optional[str]
    notice_effective_at: Optional[str]
    denial_reason: Optional[str]
    revocation_reason: Optional[str]


class Crew(SystemFields):
    crew_name: str
    cert_level: str
    mobilization_buffer_minutes: int


class DecommissionWorkOrder(SystemFields):
    tank_project_id: str
    crew_id: str
    method: str
    method_override_reason: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    field_status: str
    billing_status: str
    actual_excavated_cubic_yards: Optional[float]
    hauled_tons: Optional[float]
    abort_reason: Optional[str]


class Laboratory(SystemFields):
    lab_name: str
    accredited: bool
    committed_turnaround_hours: int
    holding_time_hours: int
    max_concurrent_analyses: int


class SoilSample(SystemFields):
    tank_project_id: str
    work_order_id: str
    laboratory_id: str
    sample_point: str
    depth_inches: int
    retest_of_sample_id: Optional[str]
    status: str
    sampling_round: int
    collected_at: str
    collected_by_user_id: str
    dispatched_at: Optional[str]
    received_at: Optional[str]
    reported_at: Optional[str]
    tph_mg_kg: Optional[float]
    benzene_mg_kg: Optional[float]
    holding_time_elapsed_hours: Optional[float]
    turnaround_hours: Optional[float]
    turnaround_breach: Optional[bool]
    qc_flag: str


class RemediationChangeOrder(SystemFields):
    tank_project_id: str
    additional_cubic_yards: float
    unit_rate_cents: int
    disposal_class: str
    status: str
    supersedes_change_order_id: Optional[str]
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    line_amount_cents: Optional[int]


class TrustFundClaim(SystemFields):
    tank_project_id: str
    variant: str
    claimed_costs_cents: int
    state_code: str
    status: str
    deductible_cents: int
    cap_cents: int
    admin_fee_cents: int
    eligible_amount_cents: int
    reimbursed_amount_cents: int
    unreimbursed_balance_cents: int
    eligibility_findings: List[str]
    info_request_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    paid_at: Optional[str]
    decision_note: Optional[str]


class NFALetter(SystemFields):
    tank_project_id: str
    closing_date: str
    status: str
    drafted_by_user_id: str
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    rescinded_at: Optional[str]
    rescission_reason: Optional[str]


class InsuranceNotification(SystemFields):
    tank_project_id: str
    notification_kind: str
    status: str
    carrier_code: str
    notified_at: str
    first_party_allocated_cents: int
    third_party_allocated_cents: int
    homeowner_out_of_pocket_cents: int
    reserve_amount_cents: int
