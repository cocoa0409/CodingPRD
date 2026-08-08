"""Domain types: entity TypedDicts, status enums, and the role enum.

Field names and enum values are taken verbatim from the PRD contract.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Enums ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    MUNICIPAL_ADMIN = "MunicipalAdmin"
    COUNTY_CLERK = "CountyClerk"
    DEVELOPER = "Developer"
    TAXING_BODY_REP = "TaxingBodyRep"


class TifDistrictStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    DECERTIFIED = "DECERTIFIED"


class SurplusPolicy(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class BodyType(str, Enum):
    SCHOOL = "SCHOOL"
    COUNTY = "COUNTY"
    MUNICIPAL = "MUNICIPAL"
    PARK = "PARK"
    LIBRARY = "LIBRARY"
    OTHER = "OTHER"


class ProjectFundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ObligationType(str, Enum):
    DEVELOPER_NOTE = "DEVELOPER_NOTE"
    BOND = "BOND"


class Seniority(str, Enum):
    SENIOR = "SENIOR"
    SUBORDINATE = "SUBORDINATE"


class ObligationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REGISTERED = "REGISTERED"
    SATISFIED = "SATISFIED"
    DEFEASED = "DEFEASED"
    DEFAULTED = "DEFAULTED"
    REJECTED = "REJECTED"


class VariantState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class IncrementRecordStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    FINALIZED = "FINALIZED"


class DisbursementStatus(str, Enum):
    PAID = "PAID"
    VOIDED = "VOIDED"


class AnnualReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"


class SurplusSource(str, Enum):
    ANNUAL = "ANNUAL"
    DECERTIFICATION = "DECERTIFICATION"


TERMINATION_TYPES = ("EXPIRATION", "EARLY")


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Audit-bearing entities carry id/created_at/updated_at/version.

class TifDistrict(TypedDict):
    id: str
    name: str
    municipality_name: str
    base_tax_year: int
    base_eav_cents: int
    term_years: int
    surplus_policy: str
    certification_date: Optional[str]
    expiration_tax_year: Optional[int]
    aggregate_tax_rate: Optional[float]
    obligations_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxingBody(TypedDict):
    id: str
    district_id: str
    name: str
    body_type: str
    tax_rate: float
    total_surplus_received_cents: int
    created_at: str
    updated_at: str
    version: int


class Developer(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class ProjectFund(TypedDict):
    id: str
    district_id: str
    balance_cents: int
    lifetime_increment_cents: int
    lifetime_disbursed_cents: int
    lifetime_surplus_cents: int
    lifetime_admin_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Obligation(TypedDict):
    id: str
    district_id: str
    developer_id: Optional[str]
    obligation_type: str
    principal_cents: int
    interest_rate_bps: int
    issue_tax_year: int
    final_maturity_tax_year: int
    annual_cap_cents: Optional[int]
    seniority: Optional[str]
    priority_rank: Optional[int]
    principal_remaining_cents: int
    accrued_interest_cents: int
    outstanding_balance_cents: int
    registered_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncrementRecord(TypedDict):
    id: str
    district_id: str
    tax_year: int
    current_eav_cents: int
    incremental_eav_cents: int
    gross_increment_cents: int
    admin_fee_cents: int
    captured_increment_cents: int
    collection_rate: Optional[float]
    variant_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    obligation_id: str
    amount_cents: int
    interest_portion_cents: int
    principal_portion_cents: int
    disbursement_tax_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict):
    id: str
    district_id: str
    report_tax_year: int
    total_increment_cents: int
    total_disbursed_cents: int
    ending_balance_cents: int
    obligation_reserve_cents: int
    surplus_declared_cents: int
    surplus_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Audit-light entities: id + created_at ONLY (no updated_at, no version).

class SurplusDistribution(TypedDict):
    id: str
    district_id: str
    taxing_body_id: str
    source: str
    report_tax_year: int
    amount_cents: int
    share_ppm: int
    created_at: str


class SurplusAgreement(TypedDict):
    id: str
    district_id: str
    taxing_body_id: str
    start_tax_year: int
    end_tax_year: int
    surplus_share_ppm_override: int
    created_at: str
