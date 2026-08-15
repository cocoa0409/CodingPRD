"""Domain types: entity TypedDicts, status enums, role enum.

Every status enum value and entity field name follows the PRD exactly.
WithholdingEntry is an immutable ledger row: it carries only id + created_at
(no updated_at, no version) per the PRD common-resource rules.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    AP_CLERK = "APClerk"
    TAX_SPECIALIST = "TaxSpecialist"
    TAX_TRANSMITTER = "TaxTransmitter"
    TAX_ADMIN = "TaxAdmin"
    IRS_SYSTEM = "IRSSystem"
    VENDOR_PORTAL = "VendorPortal"


# ---------------------------------------------------------------------------
# Status / enum families
# ---------------------------------------------------------------------------

class TaxYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    DEACTIVATED = "DEACTIVATED"


class TinMatchStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING_MATCH = "PENDING_MATCH"
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"


class BNoticeStage(str, Enum):
    NONE = "NONE"
    FIRST = "FIRST"
    SECOND = "SECOND"


class TinType(str, Enum):
    SSN = "SSN"
    EIN = "EIN"


class EntityClassification(str, Enum):
    INDIVIDUAL_SOLE_PROP = "INDIVIDUAL_SOLE_PROP"
    C_CORP = "C_CORP"
    S_CORP = "S_CORP"
    PARTNERSHIP = "PARTNERSHIP"
    LLC_C = "LLC_C"
    LLC_S = "LLC_S"
    LLC_P = "LLC_P"
    TRUST_ESTATE = "TRUST_ESTATE"
    TAX_EXEMPT = "TAX_EXEMPT"


class MatchResult(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"


class SourceSystem(str, Enum):
    AP_ERP = "AP_ERP"
    CORP_CARD = "CORP_CARD"
    MANUAL = "MANUAL"
    FIELD_OFFICE = "FIELD_OFFICE"


class PaymentType(str, Enum):
    SERVICE = "SERVICE"
    RENT = "RENT"
    ROYALTY = "ROYALTY"
    ATTORNEY_FEE = "ATTORNEY_FEE"
    MEDICAL_HEALTH = "MEDICAL_HEALTH"
    PRIZE_AWARD = "PRIZE_AWARD"
    GOODS = "GOODS"
    REIMBURSEMENT = "REIMBURSEMENT"


class ReportableBox(str, Enum):
    NEC_1 = "NEC_1"
    MISC_1 = "MISC_1"
    MISC_2 = "MISC_2"
    MISC_3 = "MISC_3"
    MISC_6 = "MISC_6"
    NONE = "NONE"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class WithholdingEntryType(str, Enum):
    DEBIT_WITHHELD = "DEBIT_WITHHELD"
    REVERSAL = "REVERSAL"


class WithholdingEntryStatus(str, Enum):
    UNREMITTED = "UNREMITTED"
    REMITTED = "REMITTED"
    REVERSED = "REVERSED"


class RemittanceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"


class FormType(str, Enum):
    NEC = "NEC"
    MISC = "MISC"


class AmountBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FederalStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class RecipientCopyStatus(str, Enum):
    PENDING = "PENDING"
    E_DELIVERED = "E_DELIVERED"
    POSTAL_SENT = "POSTAL_SENT"
    UNDELIVERABLE = "UNDELIVERABLE"


class DeliveryChannel(str, Enum):
    POSTAL = "POSTAL"
    ELECTRONIC = "ELECTRONIC"


class FilingChannel(str, Enum):
    EFILE = "EFILE"
    PAPER = "PAPER"


class TransmittalStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RequiredChannel(str, Enum):
    CFSF_FORWARD = "CFSF_FORWARD"
    DIRECT_FILE = "DIRECT_FILE"
    NOT_REQUIRED = "NOT_REQUIRED"


class StateObligationStatus(str, Enum):
    PENDING = "PENDING"
    FILED_VIA_CFSF = "FILED_VIA_CFSF"
    FILED_DIRECT = "FILED_DIRECT"
    NOT_REQUIRED = "NOT_REQUIRED"


class BNoticeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class MergeRequestStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class FeedOutcome(str, Enum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true unless noted)
# ---------------------------------------------------------------------------

class TaxYear(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tax_year: int
    period_start: str
    period_end_exclusive: str
    efiling_threshold_count: int
    nec_reportable_threshold_cents: int
    misc_reportable_threshold_cents: int
    recipient_copy_deadline: str
    backup_withholding_rate_bps: int
    status: str


class Vendor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    tin: Optional[str]
    tin_type: Optional[str]
    entity_classification: str
    address_line1: str
    address_city: str
    address_state: str
    address_postal: str
    e_delivery_consent: bool
    tin_match_status: str
    mismatch_count_3yr: int
    b_notice_stage: str
    backup_withholding_flag: bool
    withholding_balance_cents: int
    merged_into_vendor_id: Optional[str]
    status: str


class W9Submission(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    submitted_legal_name: str
    submitted_tin: str
    submitted_tin_type: str
    signature_name: str
    match_result: str
    mismatch_reason_code: Optional[str]


class Payment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    source_system: str
    payment_type: str
    amount_cents: int
    payment_date: str
    tax_year: int
    is_reportable: bool
    reportable_box: str
    withheld_cents: int
    status: str


class WithholdingEntry(TypedDict, total=False):
    # Immutable ledger row: ONLY id + created_at system fields (no updated_at, no version).
    id: str
    created_at: str
    vendor_id: str
    payment_id: str
    reverses_entry_id: Optional[str]
    remittance_id: Optional[str]
    tax_year: int
    quarter: int
    entry_type: str
    amount_cents: int
    status: str


class Remittance(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tax_year: int
    quarter: int
    amount_cents: int
    statutory_expected_cents: Optional[int]
    created_by_user_id: str
    submitted_by_user_id: Optional[str]
    status: str


class TaxReturn(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    tax_year: int
    form_type: str
    box_amounts: Dict[str, int]
    provisional_box_amounts: Dict[str, int]
    amount_basis: str
    is_correction: bool
    corrects_return_id: Optional[str]
    transmittal_id: Optional[str]
    federal_status: str
    recipient_copy_status: str
    copy_delivered_at: Optional[str]


class Transmittal(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tax_year: int
    form_type: str
    filing_channel: Optional[str]
    return_count: int
    sealed_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    status: str


class StateRule(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    state_code: str
    participates_in_cfsf: bool
    direct_reporting_threshold_cents: int
    effective_from: str
    effective_to: str


class StateObligation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    state_rule_id: str
    tax_year: int
    required_channel: str
    reportable_amount_cents: int
    status: str


class BNotice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    notice_year: int
    stage: str
    status: str
    resolved_by_user_id: Optional[str]


class VendorMergeRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    source_vendor_id: str
    target_vendor_id: str
    reason: str
    requested_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
