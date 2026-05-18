"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Persisted resources carrying id + created_at + updated_at + version:
  Estate, Asset, Beneficiary, Fiduciary, GuardianshipDirective,
  HIPAAAuthorization, PowerOfAttorney, EndOfLifeDirective,
  ProbateFiling, Distribution.
- Append-only allocation record carrying ONLY id + created_at:
  BeneficiaryDesignation. PRD §2.4: "BeneficiaryDesignation is the
  single append-only allocation record in the model: its rows carry
  only id and created_at — updated_at and version are absent".
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    EXECUTOR = "Executor"
    BENEFICIARY = "Beneficiary"
    COURT_CLERK = "CourtClerk"
    FIDUCIARY = "Fiduciary"


# ---------------------------------------------------------------------------
# Estate enums — PRD §3.1, §3.3, §3.4, §3.8, §3.11, §3.12, §2.8
# ---------------------------------------------------------------------------
class EstateAdminPhase(str, Enum):
    DRAFT = "DRAFT"
    IN_PROBATE = "IN_PROBATE"
    INVENTORIED = "INVENTORIED"
    DISTRIBUTING = "DISTRIBUTING"
    SETTLED = "SETTLED"
    CONTESTED = "CONTESTED"


class ProbatePosture(str, Enum):
    OPEN = "OPEN"
    UNDER_COURT_REVIEW = "UNDER_COURT_REVIEW"
    FROZEN = "FROZEN"


# ---------------------------------------------------------------------------
# Asset enums — PRD §3.1, §3.4
# ---------------------------------------------------------------------------
class AssetStatus(str, Enum):
    DECLARED = "DECLARED"
    INVENTORIED = "INVENTORIED"
    APPRAISED = "APPRAISED"
    DISTRIBUTED = "DISTRIBUTED"
    EXCLUDED = "EXCLUDED"


class AssetClass(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    FINANCIAL = "FINANCIAL"
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"
    DIGITAL = "DIGITAL"


# ---------------------------------------------------------------------------
# Beneficiary enums — PRD §3.1, §3.9
# ---------------------------------------------------------------------------
class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCLAIMED = "DISCLAIMED"
    REMOVED = "REMOVED"


class BeneficiaryRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"
    CHARITY = "CHARITY"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# BeneficiaryDesignation enums — PRD §3.6
# ---------------------------------------------------------------------------
class DesignationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    LOCKED = "LOCKED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Fiduciary enums — PRD §3.1, §3.14, §3.15
# ---------------------------------------------------------------------------
class FiduciaryScopeType(str, Enum):
    EXECUTOR = "EXECUTOR"
    TRUSTEE = "TRUSTEE"
    GUARDIAN = "GUARDIAN"


class FiduciaryStatus(str, Enum):
    NOMINATED = "NOMINATED"
    CONFIRMED = "CONFIRMED"
    RESIGNED = "RESIGNED"
    REMOVED = "REMOVED"


# ---------------------------------------------------------------------------
# GuardianshipDirective enums — PRD §3.1
# ---------------------------------------------------------------------------
class GuardianshipStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# HIPAAAuthorization enums — PRD §3.1, §3.13
# ---------------------------------------------------------------------------
class HipaaScope(str, Enum):
    MEDICAL_RECORDS = "MEDICAL_RECORDS"
    MENTAL_HEALTH = "MENTAL_HEALTH"
    SUBSTANCE_ABUSE = "SUBSTANCE_ABUSE"
    ALL = "ALL"


class HipaaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# PowerOfAttorney enums — PRD §3.1, §3.2, §3.3
# ---------------------------------------------------------------------------
class PoaType(str, Enum):
    FINANCIAL_DURABLE = "FINANCIAL_DURABLE"
    MEDICAL = "MEDICAL"
    LIMITED = "LIMITED"


class PoaStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# EndOfLifeDirective enums — PRD §3.1, §3.13
# ---------------------------------------------------------------------------
class DirectiveType(str, Enum):
    LIVING_WILL = "LIVING_WILL"
    DNR = "DNR"
    DNI = "DNI"
    POLST = "POLST"


class DirectiveStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# ProbateFiling enums — PRD §3.7
# ---------------------------------------------------------------------------
class FilingType(str, Enum):
    PETITION_TO_PROBATE = "PETITION_TO_PROBATE"
    INVENTORY_REPORT = "INVENTORY_REPORT"
    INTERIM_ACCOUNTING = "INTERIM_ACCOUNTING"
    FINAL_ACCOUNTING = "FINAL_ACCOUNTING"
    DISTRIBUTION_PETITION = "DISTRIBUTION_PETITION"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


# ---------------------------------------------------------------------------
# Distribution enums — PRD §3.11
# ---------------------------------------------------------------------------
class DistributionStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Persisted entity TypedDicts — id + created_at + updated_at + version
# PRD §2.4
# ---------------------------------------------------------------------------
class Estate(TypedDict, total=False):
    id: str
    testator_name: str
    domicile_state: str
    filing_court_id: str
    gross_estate_value_cents: int
    net_estate_value_cents: int
    admin_phase: str
    probate_posture: str
    petition_filed_at: Optional[str]
    settlement_due_at: Optional[str]
    contested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    estate_id: str
    asset_class: str
    description: str
    declared_value_cents: int
    appraised_value_cents: Optional[int]
    status: str
    distribution_id: Optional[str]
    requires_poa_for_mutation: bool
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    estate_id: str
    full_name: str
    relationship: str
    is_minor: bool
    guardianship_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Fiduciary(TypedDict, total=False):
    id: str
    estate_id: str
    scope_type: str
    full_name: str
    contact_user_id: str
    status: str
    bond_amount_cents: Optional[int]
    court_confirmation_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuardianshipDirective(TypedDict, total=False):
    id: str
    estate_id: str
    minor_beneficiary_id: str
    guardian_fiduciary_id: str
    effective_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HIPAAAuthorization(TypedDict, total=False):
    id: str
    estate_id: str
    authorized_recipient: str
    scope: str
    signed_at: str
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PowerOfAttorney(TypedDict, total=False):
    id: str
    estate_id: str
    poa_type: str
    agent_fiduciary_id: str
    asset_class_scope: List[str]
    effective_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EndOfLifeDirective(TypedDict, total=False):
    id: str
    estate_id: str
    directive_type: str
    instructions: str
    requires_hipaa_scope: str
    status: str
    supersedes_directive_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProbateFiling(TypedDict, total=False):
    id: str
    estate_id: str
    filing_type: str
    filed_by_fiduciary_id: str
    status: str
    court_response_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict, total=False):
    id: str
    estate_id: str
    beneficiary_id: str
    planned_amount_cents: int
    actual_amount_cents: Optional[int]
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only allocation record — id + created_at ONLY. PRD §2.4.
# ---------------------------------------------------------------------------
class BeneficiaryDesignation(TypedDict, total=False):
    id: str
    estate_id: str
    asset_id: str
    beneficiary_id: str
    share_basis_points: int
    priority_rank: int
    status: str
    created_at: str


__all__ = [
    "UserRole",
    "EstateAdminPhase",
    "ProbatePosture",
    "AssetStatus",
    "AssetClass",
    "BeneficiaryStatus",
    "BeneficiaryRelationship",
    "DesignationStatus",
    "FiduciaryScopeType",
    "FiduciaryStatus",
    "GuardianshipStatus",
    "HipaaScope",
    "HipaaStatus",
    "PoaType",
    "PoaStatus",
    "DirectiveType",
    "DirectiveStatus",
    "FilingType",
    "FilingStatus",
    "DistributionStatus",
    "Estate",
    "Asset",
    "Beneficiary",
    "Fiduciary",
    "GuardianshipDirective",
    "HIPAAAuthorization",
    "PowerOfAttorney",
    "EndOfLifeDirective",
    "ProbateFiling",
    "Distribution",
    "BeneficiaryDesignation",
]
