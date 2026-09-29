"""Typed vocabulary for the Health Plan Transparency Compliance API.

Status literals mirror the enumerations named in the PRD; the TypedDicts mirror
the response shapes described for each resource. ``PenaltyLedgerEntry`` carries
only ``id`` and ``created_at`` from the common identity block, because the PRD
states a ledger entry "has no ``updated_at`` and no ``version``".
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

UserRole = Literal[
    "PlanSponsorAdmin",
    "ComplianceOfficer",
    "ExternalAuditor",
    "VendorContact",
    "PlatformOperator",
]

ROLE_PLAN_SPONSOR_ADMIN: UserRole = "PlanSponsorAdmin"
ROLE_COMPLIANCE_OFFICER: UserRole = "ComplianceOfficer"
ROLE_EXTERNAL_AUDITOR: UserRole = "ExternalAuditor"
ROLE_VENDOR_CONTACT: UserRole = "VendorContact"
ROLE_PLATFORM_OPERATOR: UserRole = "PlatformOperator"

ALL_ROLES: tuple[UserRole, ...] = (
    ROLE_PLAN_SPONSOR_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_EXTERNAL_AUDITOR,
    ROLE_VENDOR_CONTACT,
    ROLE_PLATFORM_OPERATOR,
)

# ---------------------------------------------------------------------------
# Plan year dimensions
# ---------------------------------------------------------------------------

PlanYearLifecycleStatus = Literal["SETUP", "ACTIVE", "REPORTING_CLOSED"]

LIFECYCLE_SETUP: PlanYearLifecycleStatus = "SETUP"
LIFECYCLE_ACTIVE: PlanYearLifecycleStatus = "ACTIVE"
LIFECYCLE_REPORTING_CLOSED: PlanYearLifecycleStatus = "REPORTING_CLOSED"

CompliancePosture = Literal["COMPLIANT", "AT_RISK", "DEFICIENT", "FROZEN"]

POSTURE_COMPLIANT: CompliancePosture = "COMPLIANT"
POSTURE_AT_RISK: CompliancePosture = "AT_RISK"
POSTURE_DEFICIENT: CompliancePosture = "DEFICIENT"
POSTURE_FROZEN: CompliancePosture = "FROZEN"

PlanYearAttestationStatus = Literal[
    "NOT_STARTED",
    "DRAFT",
    "SUBMITTED",
    "ACCEPTED",
    "REJECTED",
    "VOIDED",
]

ATTESTATION_MIRROR_NOT_STARTED: PlanYearAttestationStatus = "NOT_STARTED"

# ---------------------------------------------------------------------------
# Vendor / contract dimensions
# ---------------------------------------------------------------------------

VendorType = Literal["TPA", "PBM", "BROKER", "CONSULTANT", "NETWORK_VENDOR"]

VENDOR_TYPE_TPA: VendorType = "TPA"
VENDOR_TYPE_PBM: VendorType = "PBM"
VENDOR_TYPE_BROKER: VendorType = "BROKER"
VENDOR_TYPE_CONSULTANT: VendorType = "CONSULTANT"
VENDOR_TYPE_NETWORK_VENDOR: VendorType = "NETWORK_VENDOR"

ContractType = VendorType

GagReviewStatus = Literal[
    "NOT_REVIEWED",
    "IN_REVIEW",
    "REMEDIATION_REQUESTED",
    "COMPLIANT",
    "NON_COMPLIANT",
]

GAG_NOT_REVIEWED: GagReviewStatus = "NOT_REVIEWED"
GAG_IN_REVIEW: GagReviewStatus = "IN_REVIEW"
GAG_REMEDIATION_REQUESTED: GagReviewStatus = "REMEDIATION_REQUESTED"
GAG_COMPLIANT: GagReviewStatus = "COMPLIANT"
GAG_NON_COMPLIANT: GagReviewStatus = "NON_COMPLIANT"

DataRightsStatus = Literal["NOT_SECURED", "PENDING_AMENDMENT", "SECURED"]

DATA_RIGHTS_NOT_SECURED: DataRightsStatus = "NOT_SECURED"
DATA_RIGHTS_PENDING_AMENDMENT: DataRightsStatus = "PENDING_AMENDMENT"
DATA_RIGHTS_SECURED: DataRightsStatus = "SECURED"

# ---------------------------------------------------------------------------
# Amendment dimensions
# ---------------------------------------------------------------------------

AmendmentType = Literal["DATA_RIGHTS", "GAG_CLAUSE_REMOVAL", "COOPERATION_SLA"]

AMENDMENT_TYPE_DATA_RIGHTS: AmendmentType = "DATA_RIGHTS"
AMENDMENT_TYPE_GAG_CLAUSE_REMOVAL: AmendmentType = "GAG_CLAUSE_REMOVAL"
AMENDMENT_TYPE_COOPERATION_SLA: AmendmentType = "COOPERATION_SLA"

AmendmentStatus = Literal[
    "PROPOSED",
    "COUNTERED",
    "EXECUTED",
    "WITHDRAWN",
    "LAPSED",
]

AMENDMENT_PROPOSED: AmendmentStatus = "PROPOSED"
AMENDMENT_COUNTERED: AmendmentStatus = "COUNTERED"
AMENDMENT_EXECUTED: AmendmentStatus = "EXECUTED"
AMENDMENT_WITHDRAWN: AmendmentStatus = "WITHDRAWN"
AMENDMENT_LAPSED: AmendmentStatus = "LAPSED"

WithdrawalReason = Literal["SUPERSEDED_BY_NEWER_AMENDMENT"]

WITHDRAWAL_SUPERSEDED: WithdrawalReason = "SUPERSEDED_BY_NEWER_AMENDMENT"

# ---------------------------------------------------------------------------
# Compensation disclosure dimensions
# ---------------------------------------------------------------------------

DisclosureStatus = Literal["RECEIVED", "REASONABLE", "UNREASONABLE"]

DISCLOSURE_RECEIVED: DisclosureStatus = "RECEIVED"
DISCLOSURE_REASONABLE: DisclosureStatus = "REASONABLE"
DISCLOSURE_UNREASONABLE: DisclosureStatus = "UNREASONABLE"

CompensationVariant = Literal["TOTAL_WITH_INDIRECT", "DIRECT_ONLY"]

VARIANT_TOTAL_WITH_INDIRECT: CompensationVariant = "TOTAL_WITH_INDIRECT"
VARIANT_DIRECT_ONLY: CompensationVariant = "DIRECT_ONLY"

# ---------------------------------------------------------------------------
# Machine-readable file dimensions
# ---------------------------------------------------------------------------

MrfFileType = Literal["IN_NETWORK_RATES", "ALLOWED_AMOUNTS"]

FILE_TYPE_IN_NETWORK_RATES: MrfFileType = "IN_NETWORK_RATES"
FILE_TYPE_ALLOWED_AMOUNTS: MrfFileType = "ALLOWED_AMOUNTS"

REQUIRED_FILE_TYPES: tuple[MrfFileType, MrfFileType] = (
    FILE_TYPE_IN_NETWORK_RATES,
    FILE_TYPE_ALLOWED_AMOUNTS,
)

MrfStatus = Literal["DRAFT", "VALIDATING", "PUBLISHED", "REJECTED", "SUPERSEDED"]

MRF_DRAFT: MrfStatus = "DRAFT"
MRF_VALIDATING: MrfStatus = "VALIDATING"
MRF_PUBLISHED: MrfStatus = "PUBLISHED"
MRF_REJECTED: MrfStatus = "REJECTED"
MRF_SUPERSEDED: MrfStatus = "SUPERSEDED"

# ---------------------------------------------------------------------------
# Refresh cycle dimensions
# ---------------------------------------------------------------------------

RefreshCycleStatus = Literal["PENDING", "CERTIFIED", "LATE_CERTIFIED", "MISSED"]

CYCLE_PENDING: RefreshCycleStatus = "PENDING"
CYCLE_CERTIFIED: RefreshCycleStatus = "CERTIFIED"
CYCLE_LATE_CERTIFIED: RefreshCycleStatus = "LATE_CERTIFIED"
CYCLE_MISSED: RefreshCycleStatus = "MISSED"

# ---------------------------------------------------------------------------
# Price comparison tool dimensions
# ---------------------------------------------------------------------------

ToolStatus = Literal["PENDING_LAUNCH", "LIVE"]

TOOL_PENDING_LAUNCH: ToolStatus = "PENDING_LAUNCH"
TOOL_LIVE: ToolStatus = "LIVE"

# ---------------------------------------------------------------------------
# Prescription-drug submission dimensions
# ---------------------------------------------------------------------------

RxSubmissionStatus = Literal["OPEN", "ASSEMBLING", "RECONCILED", "SUBMITTED"]

RX_OPEN: RxSubmissionStatus = "OPEN"
RX_ASSEMBLING: RxSubmissionStatus = "ASSEMBLING"
RX_RECONCILED: RxSubmissionStatus = "RECONCILED"
RX_SUBMITTED: RxSubmissionStatus = "SUBMITTED"

DataSection = Literal[
    "D2_SPENDING",
    "D6_RX_TOTALS",
    "D7_RX_REBATES",
    "D8_PREMIUM_IMPACT",
]

SECTION_D2_SPENDING: DataSection = "D2_SPENDING"
SECTION_D6_RX_TOTALS: DataSection = "D6_RX_TOTALS"
SECTION_D7_RX_REBATES: DataSection = "D7_RX_REBATES"
SECTION_D8_PREMIUM_IMPACT: DataSection = "D8_PREMIUM_IMPACT"

PackageStatus = Literal["EXPECTED", "RECEIVED", "VALIDATED", "REJECTED"]

PACKAGE_EXPECTED: PackageStatus = "EXPECTED"
PACKAGE_RECEIVED: PackageStatus = "RECEIVED"
PACKAGE_VALIDATED: PackageStatus = "VALIDATED"
PACKAGE_REJECTED: PackageStatus = "REJECTED"

# ---------------------------------------------------------------------------
# Attestation dimensions
# ---------------------------------------------------------------------------

AttestationType = Literal["GAG_CLAUSE_CEE"]

ATTESTATION_TYPE_GAG_CLAUSE_CEE: AttestationType = "GAG_CLAUSE_CEE"

AttestationStatus = Literal["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "VOIDED"]

ATTESTATION_DRAFT: AttestationStatus = "DRAFT"
ATTESTATION_SUBMITTED: AttestationStatus = "SUBMITTED"
ATTESTATION_ACCEPTED: AttestationStatus = "ACCEPTED"
ATTESTATION_REJECTED: AttestationStatus = "REJECTED"
ATTESTATION_VOIDED: AttestationStatus = "VOIDED"

VoidReason = Literal["POSTURE_DEFICIENT", "SUPERSEDED_BY_NEWER_DRAFT"]

VOID_POSTURE_DEFICIENT: VoidReason = "POSTURE_DEFICIENT"
VOID_SUPERSEDED_BY_NEWER_DRAFT: VoidReason = "SUPERSEDED_BY_NEWER_DRAFT"

# ---------------------------------------------------------------------------
# Penalty ledger dimensions
# ---------------------------------------------------------------------------

EntryType = Literal["ACCRUAL", "ABATEMENT"]

ENTRY_ACCRUAL: EntryType = "ACCRUAL"
ENTRY_ABATEMENT: EntryType = "ABATEMENT"

DeficiencyType = Literal[
    "MRF_REFRESH",
    "TOOL_SLA",
    "RXDC_LATE",
    "GAG_CLAUSE",
    "ATTESTATION_LATE",
]

DEFICIENCY_MRF_REFRESH: DeficiencyType = "MRF_REFRESH"
DEFICIENCY_TOOL_SLA: DeficiencyType = "TOOL_SLA"
DEFICIENCY_RXDC_LATE: DeficiencyType = "RXDC_LATE"
DEFICIENCY_GAG_CLAUSE: DeficiencyType = "GAG_CLAUSE"
DEFICIENCY_ATTESTATION_LATE: DeficiencyType = "ATTESTATION_LATE"

# ---------------------------------------------------------------------------
# Remediation plan dimensions
# ---------------------------------------------------------------------------

RemediationPlanStatus = Literal["ACTIVE", "COMPLETED"]

REMEDIATION_ACTIVE: RemediationPlanStatus = "ACTIVE"
REMEDIATION_COMPLETED: RemediationPlanStatus = "COMPLETED"


# ---------------------------------------------------------------------------
# Resource shapes
# ---------------------------------------------------------------------------


class PlanYear(TypedDict):
    id: str
    sponsor_name: str
    plan_year_label: str
    start_date: str
    end_date: str
    covered_lives: int
    attestation_deadline_date: str
    rxdc_deadline_date: str
    lifecycle_status: PlanYearLifecycleStatus
    compliance_posture: CompliancePosture
    deficiency_points: int
    penalty_exposure_cents: int
    tool_sla_breach_count: int
    attestation_status: PlanYearAttestationStatus
    freeze_flag: bool
    freeze_reason: str | None
    last_compliance_run_at: str | None
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    legal_name: str
    vendor_type: VendorType
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class ServiceProviderContract(TypedDict):
    id: str
    plan_year_id: str
    vendor_id: str
    contract_type: ContractType
    term_start: str
    term_end: str
    annual_fee_cents: int
    gag_review_status: GagReviewStatus
    data_rights_status: DataRightsStatus
    clause_inventory_count: int
    prohibited_clause_count: int
    remediation_round: int
    gag_non_compliant_since: str | None
    compensation_disclosure_required: bool
    created_at: str
    updated_at: str
    version: int


class ContractAmendment(TypedDict):
    id: str
    contract_id: str
    amendment_type: AmendmentType
    status: AmendmentStatus
    round: int
    proposed_terms_summary: str
    counter_terms_summary: str | None
    data_rights_granted: bool
    expires_at: str
    executed_at: str | None
    executed_terms_note: str | None
    withdrawal_reason: WithdrawalReason | None
    created_at: str
    updated_at: str
    version: int


class CompensationDisclosure(TypedDict):
    id: str
    contract_id: str
    status: DisclosureStatus
    direct_comp_cents: int
    indirect_comp_cents: int
    benchmark_median_cents: int
    services_scope_score: int
    disclosure_completeness_score: int
    variant_applied: CompensationVariant | None
    component_price_score: float | None
    component_scope_score: float | None
    component_disclosure_score: float | None
    unreasonableness_score: float | None
    assessed_at: str | None
    assessed_by_user_id: str | None
    created_at: str
    updated_at: str
    version: int


class MachineReadableFile(TypedDict):
    id: str
    plan_year_id: str
    file_type: MrfFileType
    posting_month: str
    public_url: str
    row_count: int
    schema_version: str
    status: MrfStatus
    validation_error_count: int | None
    published_at: str | None
    superseded_at: str | None
    created_at: str
    updated_at: str
    version: int


class RefreshCycle(TypedDict):
    id: str
    plan_year_id: str
    period_month: str
    period_start: str
    period_end: str
    deadline_at: str
    status: RefreshCycleStatus
    certified_at: str | None
    certified_by_user_id: str | None
    certification_note: str | None
    on_time: bool | None
    created_at: str
    updated_at: str
    version: int


class OutageWindow(TypedDict):
    window_start: str
    window_end: str
    cause: str


class PriceComparisonTool(TypedDict):
    id: str
    plan_year_id: str
    tool_name: str
    covered_items_count: int
    sla_target_uptime_pct: float
    status: ToolStatus
    launched_at: str | None
    outage_windows: list[OutageWindow]
    last_evaluated_month: str | None
    last_uptime_pct: float | None
    last_downtime_minutes: int | None
    sla_breach_open: bool
    breach_onset_date: str | None
    created_at: str
    updated_at: str
    version: int


class RxDataSubmission(TypedDict):
    id: str
    plan_year_id: str
    reference_year: int
    status: RxSubmissionStatus
    assembled_record_count: int
    gross_spend_cents: int | None
    rebate_reported_cents: int | None
    rebate_cap_pct: float | None
    rebate_credit_cents: int | None
    net_plan_spend_cents: int | None
    reconciled_at: str | None
    submitted_at: str | None
    created_at: str
    updated_at: str
    version: int


class VendorDataPackage(TypedDict):
    id: str
    rx_submission_id: str
    vendor_id: str
    data_section: DataSection
    expected_record_count: int
    status: PackageStatus
    record_count: int | None
    plan_paid_cents: int | None
    member_paid_cents: int | None
    rebate_cents: int | None
    delivery_round: int
    rejection_reason: str | None
    validated_at: str | None
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict):
    id: str
    plan_year_id: str
    attestation_type: AttestationType
    status: AttestationStatus
    contract_terms_doc_count: int
    prepared_by_user_id: str
    submitted_by_user_id: str | None
    submitted_at: str | None
    signature_statement: str | None
    rejection_reason: str | None
    void_reason: VoidReason | None
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class PenaltyLedgerEntry(TypedDict):
    """The one resource that carries only ``id`` and ``created_at``.

    The PRD states a ledger entry "carries only ``id`` and ``created_at``. It
    has no ``updated_at`` and no ``version``, because it is immutable".
    """

    id: str
    plan_year_id: str
    entry_type: EntryType
    deficiency_type: DeficiencyType
    signed_amount_cents: int
    daily_rate_cents: int
    days_open: int
    size_multiplier: float
    onset_date: str | None
    reverses_entry_id: str | None
    remediation_plan_id: str | None
    reason: str | None
    posted_by_user_id: str | None
    created_at: str


class RemediationPlan(TypedDict):
    id: str
    plan_year_id: str
    target_deficiency_type: DeficiencyType
    status: RemediationPlanStatus
    milestone_count: int
    completed_milestone_count: int
    last_milestone_label: str | None
    plan_summary: str
    abatement_posted_cents: int | None
    completed_at: str | None
    created_at: str
    updated_at: str
    version: int


class ComplianceRunSummary(TypedDict):
    run_id: str
    cycles_missed_count: int
    amendments_lapsed_count: int
    accruals_posted_count: int
    posture_before: CompliancePosture
    posture_after: CompliancePosture
    deficiency_points: int
    penalty_exposure_cents: int


class PenaltyProjection(TypedDict):
    statutory_maximum_cents: int
    accrued_to_date_cents: int
    open_deficiency_count: int
    size_multiplier: float


class ClockValue(TypedDict):
    current_utc: str


JsonDict = dict[str, Any]
