"""Domain types for the Open Access Publishing Fee & Repository Deposit API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Two entities are append-only ledger rows (an ``AgreementCoverage``
and an ``EligibilityDetermination``): the PRD states that both ``updated_at`` and
``version`` are absent from those rows, so their TypedDicts carry only ``id`` and
``created_at`` beside their own fields.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    AGREEMENT_ADMIN = "AgreementAdmin"
    SCHOL_COMM_LIBRARIAN = "ScholCommLibrarian"
    FUND_MANAGER = "FundManager"
    REPOSITORY_CURATOR = "RepositoryCurator"
    CORRESPONDING_AUTHOR = "CorrespondingAuthor"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class ScreeningStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    CLEARED = "CLEARED"
    WATCHLIST = "WATCHLIST"
    PREDATORY_FLAGGED = "PREDATORY_FLAGGED"
    BLOCKED = "BLOCKED"


class OaModel(str, Enum):
    FULLY_OA = "FULLY_OA"
    HYBRID = "HYBRID"
    SUBSCRIPTION = "SUBSCRIPTION"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class CoverageType(str, Enum):
    FULL_APC = "FULL_APC"
    CAPPED_APC = "CAPPED_APC"
    READ_ONLY = "READ_ONLY"


class AffiliationStatus(str, Enum):
    ELIGIBLE_FACULTY = "ELIGIBLE_FACULTY"
    ELIGIBLE_POSTDOC = "ELIGIBLE_POSTDOC"
    ELIGIBLE_GRAD = "ELIGIBLE_GRAD"
    VISITING = "VISITING"
    EMERITUS = "EMERITUS"
    UNAFFILIATED = "UNAFFILIATED"


class MandateType(str, Enum):
    NONE = "NONE"
    GREEN_OA = "GREEN_OA"
    GOLD_OA = "GOLD_OA"
    IMMEDIATE_CC_BY = "IMMEDIATE_CC_BY"


class LicenseRequired(str, Enum):
    ANY = "ANY"
    CC_BY = "CC_BY"
    CC_BY_OR_NC = "CC_BY_OR_NC"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MandateStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SATISFIED = "SATISFIED"
    BREACHED = "BREACHED"


class FundStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class FundingStatus(str, Enum):
    DRAFT = "DRAFT"
    ELIGIBILITY_CHECKED = "ELIGIBILITY_CHECKED"
    FUNDING_REQUESTED = "FUNDING_REQUESTED"
    FUNDED = "FUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    SELF_FUNDED = "SELF_FUNDED"
    DECLINED = "DECLINED"


class ComplianceStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    EMBARGOED = "EMBARGOED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    EXEMPT = "EXEMPT"


class DeterminationBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class EligibilityRoute(str, Enum):
    TA_FULL = "TA_FULL"
    TA_CAPPED = "TA_CAPPED"
    FUND_APC = "FUND_APC"
    AUTHOR_PAYS = "AUTHOR_PAYS"


class DeterminationReason(str, Enum):
    TA_FULL_COVERAGE = "TA_FULL_COVERAGE"
    TA_CAPPED_COVERAGE = "TA_CAPPED_COVERAGE"
    NO_COVERAGE_FUND_ELIGIBLE = "NO_COVERAGE_FUND_ELIGIBLE"
    NO_COVERAGE_AUTHOR_PAYS = "NO_COVERAGE_AUTHOR_PAYS"
    PREDATORY_FLAGGED_NO_INSTITUTIONAL_FUNDS = "PREDATORY_FLAGGED_NO_INSTITUTIONAL_FUNDS"


class FundRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    PAID = "PAID"


class FundDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AllocationStatus(str, Enum):
    ENCUMBERED = "ENCUMBERED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class InvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    DISPUTED = "DISPUTED"
    APPROVED_FOR_PAYMENT = "APPROVED_FOR_PAYMENT"
    PAID = "PAID"


class ValidationOutcome(str, Enum):
    MATCH = "MATCH"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    AMOUNT_VARIANCE = "AMOUNT_VARIANCE"
    DISCOUNT_SHORTFALL = "DISCOUNT_SHORTFALL"


class DepositStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INGESTED = "INGESTED"
    SUPERSEDED = "SUPERSEDED"


class VersionLabel(str, Enum):
    ACCEPTED_MANUSCRIPT = "ACCEPTED_MANUSCRIPT"
    VERSION_OF_RECORD = "VERSION_OF_RECORD"


class DepositLicense(str, Enum):
    CC_BY = "CC_BY"
    CC_BY_NC = "CC_BY_NC"
    CC_BY_NC_ND = "CC_BY_NC_ND"
    ALL_RIGHTS_RESERVED = "ALL_RIGHTS_RESERVED"


class CurationDecision(str, Enum):
    INGEST = "INGEST"
    RETURN = "RETURN"


class ReportBasis(str, Enum):
    ENCUMBRANCE = "ENCUMBRANCE"
    CASH = "CASH"


# --------------------------------------------------------------------------- #
# Entities carrying id / created_at / updated_at / version
# --------------------------------------------------------------------------- #
class Publisher(TypedDict, total=False):
    id: str
    name: str
    publisher_code: str
    country_code: str
    screening_status: str
    predatory_score: Optional[int]
    doaj_indexed: Optional[bool]
    cope_member: Optional[bool]
    editorial_board_verified: Optional[bool]
    retraction_rate_per_1000: Optional[float]
    peer_review_days_median: Optional[int]
    apc_transparency_score: Optional[int]
    author_guidance: Optional[str]
    last_screened_at: Optional[str]
    active_agreement_count: int
    created_at: str
    updated_at: str
    version: int


class Journal(TypedDict, total=False):
    id: str
    publisher_id: str
    issn: str
    title: str
    oa_model: str
    list_apc_cents: int
    required_embargo_months: int
    created_at: str
    updated_at: str
    version: int


class TransformativeAgreement(TypedDict, total=False):
    id: str
    publisher_id: str
    agreement_code: str
    effective_from: str
    effective_until: str
    article_quota: int
    articles_used: int
    discount_pct: float
    covered_oa_models: List[str]
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Author(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    orcid: Optional[str]
    department_code: str
    affiliation_status: str
    appointment_from: str
    appointment_until: str
    annual_cap_cents: int
    apc_committed_cents: int
    apc_disbursed_cents: int
    linked_output_count: int
    created_at: str
    updated_at: str
    version: int


class Funder(TypedDict, total=False):
    id: str
    name: str
    funder_code: str
    mandate_type: str
    max_embargo_months: int
    deposit_deadline_days: int
    license_required: str
    apc_allowable: bool
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    funder_id: str
    pi_author_id: str
    grant_number: str
    award_from: str
    award_until: str
    apc_budget_cents: int
    status: str
    output_count: int
    compliant_output_count: int
    mandate_status: str
    created_at: str
    updated_at: str
    version: int


class Article(TypedDict, total=False):
    id: str
    journal_id: str
    corresponding_author_id: str
    grant_id: Optional[str]
    manuscript_title: str
    accepted_on: str
    publication_date: Optional[str]
    apc_list_cents: Optional[int]
    doi: Optional[str]
    funding_status: str
    compliance_status: str
    eligibility_route: Optional[str]
    covered_amount_cents: int
    author_share_cents: int
    determination_count: int
    deposit_deadline_on: Optional[str]
    embargo_until: Optional[str]
    latest_deposit_ordinal: int
    created_at: str
    updated_at: str
    version: int


class APCFund(TypedDict, total=False):
    id: str
    fund_code: str
    fiscal_year: int
    period_from: str
    period_to: str
    total_budget_cents: int
    committed_cents: int
    spent_cents: int
    available_cents: int
    priority_rank: int
    eligible_affiliation_statuses: List[str]
    per_article_cap_cents: int
    status: str
    freeze_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundRequest(TypedDict, total=False):
    id: str
    article_id: str
    requested_cents: int
    justification: str
    status: str
    revision_round: int
    info_needed: Optional[str]
    response_note: Optional[str]
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    approved_cents: Optional[int]
    author_share_cents: Optional[int]
    fully_funded: bool
    created_at: str
    updated_at: str
    version: int


class FundAllocation(TypedDict, total=False):
    id: str
    fund_request_id: str
    fund_id: str
    amount_cents: int
    sequence_index: int
    status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublisherInvoice(TypedDict, total=False):
    id: str
    publisher_id: str
    article_id: str
    invoice_number: str
    invoice_amount_cents: int
    currency: str
    claimed_discount_pct: float
    vat_pct: float
    invoice_date: str
    entitled_discount_pct: float
    net_cents: int
    vat_cents: int
    expected_amount_cents: int
    variance_cents: int
    validation_outcome: str
    status: str
    dispute_reason: Optional[str]
    payment_approved_by_user_id: Optional[str]
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepositoryDeposit(TypedDict, total=False):
    id: str
    article_id: str
    version_label: str
    version_ordinal: int
    file_checksum: str
    license: str
    status: str
    persistent_identifier: Optional[str]
    returned_count: int
    curation_note: Optional[str]
    submitted_at: Optional[str]
    ingested_at: Optional[str]
    embargo_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only ledger rows — only id and created_at beside their own fields
# --------------------------------------------------------------------------- #
class AgreementCoverage(TypedDict, total=False):
    id: str
    agreement_id: str
    journal_id: str
    coverage_type: str
    capped_amount_cents: Optional[int]
    covered_from: str
    covered_until: str
    created_at: str


class EligibilityDetermination(TypedDict, total=False):
    id: str
    article_id: str
    sequence_no: int
    basis: str
    reference_date: str
    route: str
    agreement_id: Optional[str]
    coverage_id: Optional[str]
    list_base_cents: int
    discount_pct_applied: float
    covered_amount_cents: int
    author_share_cents: int
    eligible_request_cents: int
    determination_reason: str
    quota_position: Optional[int]
    created_at: str
