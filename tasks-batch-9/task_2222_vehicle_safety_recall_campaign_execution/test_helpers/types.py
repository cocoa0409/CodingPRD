"""
Entity shapes, enums and role names for the Vehicle Safety Recall Campaigns API.

Everything here mirrors the PRD exactly: field names are the PRD's field names,
and every enum lists exactly the values the PRD declares.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ─── Roles ────────────────────────────────────────────

class Role:
    """The five recognised role names (PRD §2.1)."""

    SAFETY_ENGINEER = "SafetyEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RECALL_OPERATIONS_MANAGER = "RecallOperationsManager"
    DEALER_SERVICE_MANAGER = "DealerServiceManager"
    CLAIMS_AUDITOR = "ClaimsAuditor"

    ALL = [
        SAFETY_ENGINEER,
        COMPLIANCE_OFFICER,
        RECALL_OPERATIONS_MANAGER,
        DEALER_SERVICE_MANAGER,
        CLAIMS_AUDITOR,
    ]


# ─── Campaign enums ───────────────────────────────────

class CampaignStatus:
    """The regulatory/administrative campaign dimension (PRD §2.5)."""

    DRAFT = "DRAFT"
    DEFECT_DETERMINED = "DEFECT_DETERMINED"
    FILED = "FILED"
    INTERIM_NOTIFIED = "INTERIM_NOTIFIED"
    OWNER_NOTIFIED = "OWNER_NOTIFIED"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"

    TERMINAL = [CLOSED, SUPERSEDED]


class RemedyStatus:
    """The remedy-engineering campaign dimension (PRD §2.5)."""

    REMEDY_UNDER_DEVELOPMENT = "REMEDY_UNDER_DEVELOPMENT"
    INTERIM_ONLY = "INTERIM_ONLY"
    REMEDY_RELEASED = "REMEDY_RELEASED"
    REMEDY_REVISED = "REMEDY_REVISED"

    AVAILABLE = [REMEDY_RELEASED, REMEDY_REVISED]


class DefectType:
    SAFETY_DEFECT = "SAFETY_DEFECT"
    NONCOMPLIANCE = "NONCOMPLIANCE"


class RiskSeverity:
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


# ─── Build record / affected-vehicle enums ────────────

class SaleStatus:
    SOLD = "SOLD"
    IN_DEALER_STOCK = "IN_DEALER_STOCK"
    EXPORTED = "EXPORTED"
    SCRAPPED = "SCRAPPED"


class RegionCode:
    NE = "NE"
    SE = "SE"
    MW = "MW"
    WE = "WE"

    ALL = [NE, SE, MW, WE]


class VehicleRemedyStatus:
    """Per-affected-vehicle-row remedy status (PRD §3.2, §3.9)."""

    UNREPAIRED = "UNREPAIRED"
    SCHEDULED = "SCHEDULED"
    REMEDIED = "REMEDIED"
    UNREACHABLE = "UNREACHABLE"
    REMOVED_FROM_POPULATION = "REMOVED_FROM_POPULATION"


class InclusionMode:
    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"


# ─── Filing enums ─────────────────────────────────────

class FilingType:
    DEFECT_NOTICE = "DEFECT_NOTICE"
    QUARTERLY = "QUARTERLY"
    AMENDMENT = "AMENDMENT"


class FilingStatus:
    SUBMITTED = "SUBMITTED"
    AMENDED = "AMENDED"


# ─── Wave enums ───────────────────────────────────────

class WaveType:
    INTERIM = "INTERIM"
    REMEDY = "REMEDY"
    FOLLOW_UP = "FOLLOW_UP"


class WaveStatus:
    PLANNED = "PLANNED"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    MAILED = "MAILED"
    CANCELLED = "CANCELLED"

    OPEN = [PLANNED, RELEASE_APPROVED]


class CancelReason:
    CAMPAIGN_SUPERSEDED = "CAMPAIGN_SUPERSEDED"


# ─── Dealer / parts enums ─────────────────────────────

class DealerStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RateType:
    WARRANTY = "WARRANTY"
    PREVAILING = "PREVAILING"


class AllocationStatus:
    ALLOCATED = "ALLOCATED"
    REVOKED = "REVOKED"


class RevokedReason:
    """The four paths that retire an allocation (PRD §3.5)."""

    SUPERSEDED = "SUPERSEDED"
    MANUAL = "MANUAL"
    CAMPAIGN_SUPERSEDED = "CAMPAIGN_SUPERSEDED"
    REMEDY_REVISED = "REMEDY_REVISED"

    ALL = [SUPERSEDED, MANUAL, CAMPAIGN_SUPERSEDED, REMEDY_REVISED]


# ─── Claim enums ──────────────────────────────────────

class ClaimStatus:
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class AuditDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ─── Outreach enums ───────────────────────────────────

class OutreachChannel:
    MAIL = "MAIL"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    CANVASS = "CANVASS"


class OutreachOutcome:
    NO_RESPONSE = "NO_RESPONSE"
    BAD_ADDRESS = "BAD_ADDRESS"
    SCHEDULED = "SCHEDULED"
    OWNER_REFUSED = "OWNER_REFUSED"

    UNRESPONSIVE = [NO_RESPONSE, BAD_ADDRESS, OWNER_REFUSED]


# ─── Owner reimbursement enums ────────────────────────

class ReimbursementStatus:
    SUBMITTED = "SUBMITTED"
    DOCUMENTS_REQUESTED = "DOCUMENTS_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AdjudicationDecision:
    APPROVE = "APPROVE"
    DENY = "DENY"


# ─── Entity TypedDicts ────────────────────────────────

class RecallCampaign(TypedDict, total=False):
    id: str
    campaign_number: str
    defect_type: str
    defect_description: str
    risk_severity: str
    campaign_status: str
    remedy_status: str
    supersedes_campaign_id: Optional[str]
    defect_determination_date: Optional[str]
    determined_by_user_id: Optional[str]
    filing_deadline_utc: Optional[str]
    filed_at: Optional[str]
    late_filing_flag: bool
    days_late: int
    stop_sale_flag: bool
    do_not_drive_flag: bool
    remedy_released_at: Optional[str]
    remedy_released_by_user_id: Optional[str]
    remedy_revision_count: int
    quarterly_filing_count: int
    affected_vehicle_count: int
    recall_population_count: int
    remedied_count: int
    completion_rate_pct: float
    remedy_effectiveness_score: float
    reimbursement_obligation_cents: int
    open_followup_wave_count: int
    closure_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    plant_code: str
    model_code: str
    model_year: int
    production_date: str
    suspect_part_number: int
    region_code: str
    sale_status: str
    in_service_date: Optional[str]
    owner_name: Optional[str]
    owner_address_valid: bool
    stop_sale_hold: bool
    created_at: str
    updated_at: str
    version: int


class PopulationRule(TypedDict, total=False):
    id: str
    campaign_id: str
    inclusion_mode: str
    plant_code: str
    model_code: str
    model_year: int
    production_start_date: str
    production_end_date: str
    part_number_low: int
    part_number_high: int
    matched_vehicle_count: int
    created_at: str
    updated_at: str
    version: int


class AffectedVehicle(TypedDict, total=False):
    id: str
    campaign_id: str
    vehicle_id: str
    matched_by_rule_id: Optional[str]
    remedy_status: str
    notification_wave_id: Optional[str]
    dealer_id: Optional[str]
    notice_count: int
    last_notice_type: Optional[str]
    last_notice_date: Optional[str]
    scheduled_repair_date: Optional[str]
    approved_claim_count: int
    outreach_attempt_count: int
    requires_renotification: bool
    created_at: str
    updated_at: str
    version: int


class RegulatoryFiling(TypedDict, total=False):
    id: str
    campaign_id: str
    filing_type: str
    report_period: Optional[str]
    narrative: str
    status: str
    filed_at: str
    filed_by_user_id: str
    completion_rate_snapshot_pct: float
    remedied_count_snapshot: int
    recall_population_snapshot: int
    effectiveness_score_snapshot: float
    amendment_required: bool
    days_late: int
    created_at: str
    updated_at: str
    version: int


class NotificationWave(TypedDict, total=False):
    id: str
    campaign_id: str
    wave_type: str
    target_region_code: str
    scheduled_mail_date: str
    sequence_number: int
    status: str
    auto_created: bool
    eligible_vehicle_count: int
    parts_capacity_qty: int
    provisional_coverage_ratio: float
    coverage_tier_factor: float
    planned_vehicle_count: int
    parts_coverage_ratio: float
    mailed_vehicle_count: int
    actual_mail_date: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    dealer_code: str
    name: str
    region_code: str
    labor_rate_per_hour: float
    monthly_repair_capacity: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemedyPart(TypedDict, total=False):
    id: str
    campaign_id: str
    part_number: str
    unit_cost: float
    total_procured_qty: int
    unallocated_qty: int
    consumed_qty: int
    lead_time_days: int
    created_at: str
    updated_at: str
    version: int


class LaborOperation(TypedDict, total=False):
    id: str
    campaign_id: str
    labor_op_code: str
    description: str
    flat_hours: float
    rate_type: str
    effective_from: str
    effective_to: str
    claim_count: int
    created_at: str
    updated_at: str
    version: int


class PartsAllocation(TypedDict, total=False):
    id: str
    campaign_id: str
    remedy_part_id: str
    dealer_id: str
    requested_qty: int
    allocated_qty: int
    consumed_qty: int
    partially_granted: bool
    status: str
    revoked_reason: Optional[str]
    revoke_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairClaim(TypedDict, total=False):
    id: str
    campaign_id: str
    affected_vehicle_id: str
    dealer_id: str
    labor_operation_id: str
    parts_allocation_id: Optional[str]
    repair_date: str
    claimed_labor_hours: float
    parts_used_qty: int
    is_repeat_repair: bool
    status: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    audit_note: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutreachAttempt(TypedDict, total=False):
    """PRD §2.4: carries only `id` and `created_at` besides its own payload."""

    id: str
    affected_vehicle_id: str
    channel: str
    outcome: str
    note: Optional[str]
    attempt_number: int
    attempted_at: str
    created_at: str


class OwnerReimbursementRequest(TypedDict, total=False):
    id: str
    campaign_id: str
    vehicle_id: str
    invoice_date: str
    invoice_amount: float
    labor_hours_claimed: float
    parts_amount: float
    towing_amount: float
    documentation_complete: bool
    status: str
    document_round: int
    labor_operation_id: Optional[str]
    approved_amount_cents: Optional[int]
    requested_items: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
