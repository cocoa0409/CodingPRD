"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry id, created_at, updated_at, and version
(the PRD states there are no version-free or timestamp-free entities).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    CLERK = "Clerk"
    PROBATE_JUDGE = "ProbateJudge"
    PERSONAL_REPRESENTATIVE = "PersonalRepresentative"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class EstateStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    INVENTORIED = "INVENTORIED"
    ACCOUNTING = "ACCOUNTING"
    DISTRIBUTING = "DISTRIBUTING"
    CLOSED = "CLOSED"


class SupervisionLevel(str, Enum):
    FULL = "FULL"
    LIMITED = "LIMITED"
    INDEPENDENT = "INDEPENDENT"


class EstateType(str, Enum):
    TESTATE = "TESTATE"
    INTESTATE = "INTESTATE"


class PetitionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class RepresentativeStatus(str, Enum):
    NOMINATED = "NOMINATED"
    APPOINTED = "APPOINTED"
    SUSPENDED = "SUSPENDED"
    DISCHARGED = "DISCHARGED"
    REMOVED = "REMOVED"


class BondStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    EXONERATED = "EXONERATED"
    FORFEITED = "FORFEITED"


class BeneficiaryRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    HEIR = "HEIR"
    DEVISEE = "DEVISEE"
    CREDITOR_RESIDUAL = "CREDITOR_RESIDUAL"


class ClaimClass(str, Enum):
    SECURED = "SECURED"
    FUNERAL = "FUNERAL"
    ADMIN = "ADMIN"
    TAX = "TAX"
    GENERAL = "GENERAL"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    ALLOWED = "ALLOWED"
    REJECTED = "REJECTED"
    BARRED = "BARRED"
    PAID = "PAID"


class AssetClass(str, Enum):
    REAL_PROPERTY = "REAL_PROPERTY"
    CASH = "CASH"
    SECURITY = "SECURITY"
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"


class AssetStatus(str, Enum):
    LISTED = "LISTED"
    APPRAISED = "APPRAISED"
    MARSHALED = "MARSHALED"
    LIQUIDATED = "LIQUIDATED"
    DISTRIBUTED = "DISTRIBUTED"


class DistributionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    RETURNED = "RETURNED"


class ReportType(str, Enum):
    INVENTORY = "INVENTORY"
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class AccountingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class HearingType(str, Enum):
    PETITION = "PETITION"
    ACCOUNTING = "ACCOUNTING"
    REMOVAL = "REMOVAL"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    VACATED = "VACATED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all common_fields: true)
# --------------------------------------------------------------------------- #
class Estate(TypedDict):
    id: str
    decedent_name: str
    date_of_death: str
    county_code: str
    estate_type: str
    gross_estate_value_cents: int
    status: str
    supervision_level: str
    claim_period_opened_at: Optional[str]
    claim_bar_date: Optional[str]
    inventory_total_cents: int
    marshaled_cash_cents: int
    allowed_claims_total_cents: int
    residue_cents: int
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict):
    id: str
    estate_id: str
    petitioner_name: str
    will_lodged: bool
    will_date: Optional[str]
    nominated_representative_name: str
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PersonalRepresentative(TypedDict):
    id: str
    estate_id: str
    petition_id: str
    full_name: str
    representative_user_id: str
    bond_required: bool
    bond_id: Optional[str]
    status: str
    letters_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    estate_id: str
    representative_id: str
    surety_name: str
    penal_amount_cents: int
    required_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    estate_id: str
    full_name: str
    relationship: str
    share_bps: int
    distributed_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditorClaim(TypedDict):
    id: str
    estate_id: str
    creditor_name: str
    claim_class: str
    claimed_amount_cents: int
    allowed_amount_cents: Optional[int]
    filed_at: str
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    estate_id: str
    description: str
    asset_class: str
    declared_value_cents: int
    appraised_value_cents: Optional[int]
    liquidation_proceeds_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    estate_id: str
    beneficiary_id: str
    proposed_amount_cents: int
    receipt_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountingReport(TypedDict):
    id: str
    estate_id: str
    report_type: str
    snapshot_inventory_cents: int
    snapshot_allowed_claims_cents: int
    snapshot_distributed_cents: int
    balances: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    estate_id: str
    hearing_type: str
    courtroom_code: str
    judge_user_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
