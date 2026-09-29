"""Typed shapes for the Motor Fuel Tax Licensing & Distributor Reporting API.

Every TypedDict below mirrors the resource contract described in the PRD.
Resources listed in the PRD as mutable state carry ``id``, ``created_at``,
``updated_at`` and ``version``; the three append-only observation records
(rack removals, schedule lines and ledger entries) carry only ``id`` and
``created_at``.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

Role = Literal[
    "LicenseeAgent",
    "LicensingOfficer",
    "ReturnsExaminer",
    "TaxSupervisor",
    "AuditManager",
    "FieldInspector",
]

LicenseType = Literal["SUPPLIER", "DISTRIBUTOR", "BLENDER", "TRANSPORTER", "RETAILER"]
LicenseeStatus = Literal["PENDING_BOND", "ACTIVE", "SUSPENDED", "REVOKED"]
GrossNetElection = Literal["NET", "GROSS"]
RetailChannel = Literal["HIGHWAY", "MARINE", "FARM", "NOT_APPLICABLE"]

ProductCode = Literal[
    "GASOLINE",
    "UNDYED_DIESEL",
    "DYED_DIESEL",
    "JET_FUEL",
    "AVIATION_GAS",
    "ETHANOL_E100",
    "BIODIESEL_B100",
]

BondStatusValue = Literal["ACTIVE", "RELEASED", "FORFEITED"]
ReleaseReason = Literal["SUPERSEDED_BY_NEW_BOND", "OPERATOR_RELEASE", "LICENSE_REVOKED"]

ExemptionType = Literal["GOVERNMENT", "AGRICULTURE", "EXPORT"]
CertificateStatus = Literal["ACTIVE", "REVOKED"]

ImpositionPoint = Literal["TERMINAL_RACK", "DEFERRED_TO_PURCHASER", "NONE_EXEMPT"]
BasisUsed = Literal["NET", "GROSS"]

FilingStatus = Literal["DRAFT", "FILED", "SUPERSEDED"]
MatchStatus = Literal["NOT_MATCHED", "MATCH_CLEAN", "MATCH_VARIANCE", "MATCH_RESOLVED"]

ScheduleCode = Literal[
    "SCH_1_RECEIVED_TAX_PAID",
    "SCH_2_RECEIVED_TAX_UNPAID",
    "SCH_5_DELIVERED_TAX_COLLECTED",
    "SCH_6_EXEMPT_SALES",
    "SCH_7_EXPORTS",
    "SCH_10_DYED_SALES",
]

TransactionType = Literal["PURCHASE", "SALE", "EXPORT", "IMPORT", "BLEND", "TRANSFER"]

RunStatus = Literal["COMPLETED"]
DiscrepancyDirection = Literal[
    "UNREPORTED_BY_PURCHASER",
    "OVERSTATED_BY_PURCHASER",
    "MISSING_COUNTERPARTY_RETURN",
]
DiscrepancyStatus = Literal[
    "OPEN",
    "INQUIRY_SENT",
    "RESPONSE_RECEIVED",
    "RESOLVED_EXPLAINED",
    "WRITTEN_OFF",
    "ESCALATED_TO_AUDIT",
]
Resolution = Literal["EXPLAINED", "WRITTEN_OFF", "ESCALATE_TO_AUDIT"]

ClaimType = Literal["OFF_ROAD", "PTO", "REFRIGERATION_UNIT", "EXPORT"]
EquipmentClass = Literal["CONCRETE_MIXER", "REFUSE_PACKER", "BULK_TANKER_PUMP"]
RefundStatus = Literal[
    "SUBMITTED", "REVIEWED", "HELD", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "PAID"
]
Recommendation = Literal["APPROVE", "PARTIAL", "DENY"]
Decision = Literal["APPROVED", "PARTIALLY_APPROVED", "DENIED"]
HoldReason = Literal["BOND_DEFICIENCY", "OPEN_AUDIT"]

DyeTestResult = Literal["NEGATIVE", "POSITIVE"]
InspectionStatus = Literal["RECORDED", "PENALTY_ASSESSED", "DISMISSED"]

SelectionMethod = Literal["RISK_SCORE", "CROSS_MATCH_ESCALATION", "ROADSIDE_REFERRAL"]
RiskScoreVariant = Literal["VARIANCE_WEIGHTED", "FREQUENCY_WEIGHTED"]
CaseStatus = Literal["OPEN", "FIELDWORK", "PRELIM_FINDINGS", "TAXPAYER_RESPONSE", "CLOSED"]
AssessmentStatus = Literal["NONE", "ISSUED", "PROTESTED", "FINAL", "ABATED"]

EntryType = Literal[
    "RETURN_TAX",
    "RETURN_TAX_ADJUSTMENT",
    "PENALTY",
    "INTEREST",
    "ASSESSMENT",
    "ABATEMENT",
    "REFUND",
    "PAYMENT",
    "PENALTY_REVERSAL",
]
SourceEntityType = Literal[
    "MonthlyReturn", "RefundClaim", "AuditCase", "RoadsideInspection", "Payment"
]

Json = Dict[str, Any]


# --------------------------------------------------------------------------
# Mutable resources: id + created_at + updated_at + version
# --------------------------------------------------------------------------


class Licensee(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    license_type: LicenseType
    mailing_state: str
    gross_net_election: GrossNetElection
    retail_channel: RetailChannel
    parent_licensee_id: Optional[str]
    status: LicenseeStatus
    balance_cents: int
    avg_monthly_tax_liability_cents: int
    required_bond_cents: int
    posted_bond_cents: int
    bond_deficiency_cents: int
    dyed_violation_count: int
    late_filing_count: int
    open_audit_count: int
    open_discrepancy_count: int
    unreported_gallons_total: float
    effective_taxable_gallons_ytd: float
    risk_score_variance_weighted: int
    risk_score_frequency_weighted: int
    created_at: str
    updated_at: str
    version: int


class BondInstrument(TypedDict, total=False):
    id: str
    licensee_id: str
    amount_cents: int
    surety_name: str
    effective_date: str
    status: BondStatusValue
    release_reason: Optional[ReleaseReason]
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict, total=False):
    id: str
    terminal_control_number: str
    name: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class ExemptionCertificate(TypedDict, total=False):
    id: str
    purchaser_licensee_id: str
    exemption_type: ExemptionType
    document_number: str
    valid_from: str
    valid_to: str
    status: CertificateStatus
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonthlyReturn(TypedDict, total=False):
    id: str
    licensee_id: str
    period_month: str
    filing_status: FilingStatus
    match_status: MatchStatus
    due_at: str
    filed_at: Optional[str]
    attest_name: Optional[str]
    taxable_gallons_total: float
    tax_due_cents: int
    interest_cents: int
    penalty_cents: int
    total_remittance_cents: int
    days_late: int
    amends_return_id: Optional[str]
    amendment_sequence: int
    amendment_count: int
    amendment_delta_cents: int
    created_at: str
    updated_at: str
    version: int


class ReturnSchedule(TypedDict, total=False):
    id: str
    return_id: str
    schedule_code: ScheduleCode
    product_code: ProductCode
    total_gallons: float
    line_count: int
    created_at: str
    updated_at: str
    version: int


class CrossMatchRun(TypedDict, total=False):
    id: str
    period_month: str
    run_status: RunStatus
    tolerance_gallons: float
    matched_cells_count: int
    discrepancy_count: int
    gross_unreported_gallons_total: float
    unreported_gallons_total: float
    written_off_gallons_total: float
    escalated_count: int
    escalation_skipped_count: int
    created_at: str
    updated_at: str
    version: int


class MatchDiscrepancy(TypedDict, total=False):
    id: str
    run_id: str
    supplier_licensee_id: str
    distributor_licensee_id: str
    product_code: ProductCode
    supplier_gallons: float
    distributor_gallons: float
    variance_gallons: float
    direction: DiscrepancyDirection
    supplier_return_id: str
    distributor_return_id: Optional[str]
    status: DiscrepancyStatus
    inquiry_round: int
    last_question: Optional[str]
    last_explanation: Optional[str]
    response_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict, total=False):
    id: str
    licensee_id: str
    claim_type: ClaimType
    period_month: str
    claimed_gallons: float
    equipment_class: Optional[EquipmentClass]
    allowable_gallons: float
    refund_amount_cents: int
    status: RefundStatus
    status_before_hold: Optional[RefundStatus]
    hold_reason: Optional[HoldReason]
    recommendation: Optional[Recommendation]
    recommended_gallons: Optional[float]
    reviewer_user_id: Optional[str]
    decider_user_id: Optional[str]
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoadsideInspection(TypedDict, total=False):
    id: str
    inspected_licensee_id: str
    inspection_date: str
    dye_test_result: DyeTestResult
    gallons_in_tank: float
    vehicle_identifier: str
    location_description: Optional[str]
    prior_positive_count: int
    penalty_cents: int
    status: InspectionStatus
    dismissal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    subject_licensee_id: str
    selection_method: SelectionMethod
    risk_score_variant: RiskScoreVariant
    selection_score: int
    source_discrepancy_id: Optional[str]
    period_start_month: str
    period_end_month: str
    case_status: CaseStatus
    assessment_status: AssessmentStatus
    response_rounds: int
    additional_tax_cents: int
    assessment_penalty_cents: int
    assessment_interest_cents: int
    assessed_total_cents: int
    evasion_indicator: bool
    opened_by_user_id: str
    assessed_by_user_id: Optional[str]
    protest_grounds: Optional[str]
    abatement_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only observations: id + created_at only
# --------------------------------------------------------------------------


class RackRemoval(TypedDict, total=False):
    id: str
    terminal_id: str
    position_holder_licensee_id: str
    purchaser_licensee_id: str
    exemption_certificate_id: Optional[str]
    product_code: ProductCode
    gross_gallons: float
    net_gallons: float
    removal_date: str
    destination_state: str
    bill_of_lading_number: str
    basis_used: BasisUsed
    imposition_point: ImpositionPoint
    taxable_gallons: float
    tax_imposed: bool
    tax_amount_cents: int
    deferred_tax_cents: int
    created_at: str


class ScheduleLine(TypedDict, total=False):
    id: str
    schedule_id: str
    counterparty_licensee_id: str
    exemption_certificate_id: Optional[str]
    transaction_type: TransactionType
    gallons: float
    document_date: str
    bill_of_lading_number: str
    created_at: str


class LedgerEntry(TypedDict, total=False):
    id: str
    licensee_id: str
    entry_type: EntryType
    amount_cents: int
    source_entity_type: SourceEntityType
    source_entity_id: str
    effective_date: str
    memo: Optional[str]
    created_at: str


# --------------------------------------------------------------------------
# Computed reads
# --------------------------------------------------------------------------


class BondStatusRead(TypedDict, total=False):
    avg_monthly_tax_liability_cents: int
    required_bond_cents: int
    posted_bond_cents: int
    bond_deficiency_cents: int
    basis_return_count: int


class RiskProfileRead(TypedDict, total=False):
    risk_score_variance_weighted: int
    risk_score_frequency_weighted: int
    unreported_gallons_total: float
    open_discrepancy_count: int
    late_filing_count: int
    dyed_violation_count: int
    audit_selection_threshold: int


__all__ = [
    "Role",
    "LicenseType",
    "LicenseeStatus",
    "GrossNetElection",
    "RetailChannel",
    "ProductCode",
    "BondStatusValue",
    "ReleaseReason",
    "ExemptionType",
    "CertificateStatus",
    "ImpositionPoint",
    "BasisUsed",
    "FilingStatus",
    "MatchStatus",
    "ScheduleCode",
    "TransactionType",
    "RunStatus",
    "DiscrepancyDirection",
    "DiscrepancyStatus",
    "Resolution",
    "ClaimType",
    "EquipmentClass",
    "RefundStatus",
    "Recommendation",
    "Decision",
    "HoldReason",
    "DyeTestResult",
    "InspectionStatus",
    "SelectionMethod",
    "RiskScoreVariant",
    "CaseStatus",
    "AssessmentStatus",
    "EntryType",
    "SourceEntityType",
    "Json",
    "Licensee",
    "BondInstrument",
    "Terminal",
    "ExemptionCertificate",
    "MonthlyReturn",
    "ReturnSchedule",
    "CrossMatchRun",
    "MatchDiscrepancy",
    "RefundClaim",
    "RoadsideInspection",
    "AuditCase",
    "RackRemoval",
    "ScheduleLine",
    "LedgerEntry",
    "BondStatusRead",
    "RiskProfileRead",
    "List",
]
