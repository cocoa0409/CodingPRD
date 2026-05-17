"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Top-level participant-facing resources — Participant, Account,
  ConversionRequest, BeneficiaryClaim — carry id, created_at,
  updated_at, version.
- Append-once event records — ContributionEvent, DistributionEvent,
  Form1099R, ExcessPenalty — carry ONLY id and created_at. They have
  no updated_at and no version. A ContributionEvent later reversed
  records the reversal timestamp in reversed_at; a DistributionEvent
  records settled_at; an ExcessPenalty records assessed_at.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PARTICIPANT = "Participant"
    CUSTODIAN = "Custodian"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Participant — PRD §3.1
# ---------------------------------------------------------------------------
class TaxStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


# ---------------------------------------------------------------------------
# Account — PRD §3.2
# ---------------------------------------------------------------------------
class AccountType(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    ROTH = "ROTH"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# ContributionEvent — PRD §3.3
# ---------------------------------------------------------------------------
class ContributionType(str, Enum):
    REGULAR = "REGULAR"
    CATCHUP = "CATCHUP"
    BACKDOOR_NONDEDUCTIBLE = "BACKDOOR_NONDEDUCTIBLE"


class ContributionStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# DistributionEvent — PRD §3.4
# ---------------------------------------------------------------------------
class DistributionReason(str, Enum):
    NORMAL = "NORMAL"
    EARLY = "EARLY"
    RMD = "RMD"
    DEATH = "DEATH"
    CONVERSION = "CONVERSION"
    EXCESS_REMOVAL = "EXCESS_REMOVAL"


# ---------------------------------------------------------------------------
# ConversionRequest — PRD §3.7
# ---------------------------------------------------------------------------
class ConversionRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


# ---------------------------------------------------------------------------
# BeneficiaryClaim — PRD §3.6
# ---------------------------------------------------------------------------
class BeneficiaryClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    SUSPENDED = "SUSPENDED"
    DRAINED = "DRAINED"
    FORFEITED = "FORFEITED"


# ---------------------------------------------------------------------------
# Form1099R — PRD §3.9
# ---------------------------------------------------------------------------
class Form1099RStatus(str, Enum):
    ISSUED = "ISSUED"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


class Form1099RSourceEventType(str, Enum):
    DISTRIBUTION = "DISTRIBUTION"
    EXCESS_PENALTY = "EXCESS_PENALTY"
    CONVERSION = "CONVERSION"


class Box7DistributionCode(str, Enum):
    """PRD §3.9 box7_distribution_code enumeration: 1 | 2 | 7 | 4 | G | 8."""
    EARLY = "1"
    EARLY_NO_PENALTY = "2"
    NORMAL = "7"
    DEATH = "4"
    CONVERSION = "G"
    EXCESS_PENALTY = "8"


# ===========================================================================
# Top-level participant-facing resources (common_fields: true) — PRD §2.4
# Carry id + created_at + updated_at + version.
# ===========================================================================
class Participant(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    tax_status: str
    is_deceased: bool
    date_of_death: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    participant_id: str
    account_type: str
    status: str
    balance_cents: int
    ytd_contribution_cents: int
    tax_year: int
    prior_year_end_balance_cents: int
    inherited_from_participant_id: Optional[str]
    inheritance_start_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConversionRequest(TypedDict, total=False):
    id: str
    participant_id: str
    source_account_id: str
    destination_account_id: str
    amount_cents: int
    backdoor_flag: bool
    status: str
    approver_role_id: Optional[str]
    completed_distribution_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficiaryClaim(TypedDict, total=False):
    id: str
    account_id: str
    beneficiary_participant_id: str
    claim_date: str
    deadline_date: str
    status: str
    drained_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-once event records (common_fields: false) — PRD §2.4
# Carry ONLY id + created_at. No updated_at, no version.
# ===========================================================================
class ContributionEvent(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    contribution_type: str
    tax_year: int
    status: str
    reversed_at: Optional[str]
    created_at: str


class DistributionEvent(TypedDict, total=False):
    id: str
    account_id: str
    gross_amount_cents: int
    distribution_reason: str
    federal_withholding_cents: int
    net_amount_cents: int
    tax_year: int
    settled_at: str
    created_at: str


class Form1099R(TypedDict, total=False):
    id: str
    tax_year: int
    recipient_participant_id: str
    source_event_type: str
    source_event_id: str
    box1_gross_distribution_cents: int
    box2a_taxable_amount_cents: int
    box4_federal_withholding_cents: int
    box7_distribution_code: str
    status: str
    created_at: str


class ExcessPenalty(TypedDict, total=False):
    id: str
    account_id: str
    tax_year: int
    excess_amount_cents: int
    penalty_amount_cents: int
    assessed_at: str
    created_at: str


# ---------------------------------------------------------------------------
# Read-only projections — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
class RMDQuote(TypedDict, total=False):
    required_amount_cents: int


class DrawdownProjection(TypedDict, total=False):
    remaining_years: int
    projected_rmd_cents: int
    projected_total_drawdown_cents: int


class ClockState(TypedDict, total=False):
    current_date: str
    clock_year: int


__all__ = [
    "UserRole",
    "TaxStatus",
    "AccountType",
    "AccountStatus",
    "ContributionType",
    "ContributionStatus",
    "DistributionReason",
    "ConversionRequestStatus",
    "BeneficiaryClaimStatus",
    "Form1099RStatus",
    "Form1099RSourceEventType",
    "Box7DistributionCode",
    "Participant",
    "Account",
    "ConversionRequest",
    "BeneficiaryClaim",
    "ContributionEvent",
    "DistributionEvent",
    "Form1099R",
    "ExcessPenalty",
    "RMDQuote",
    "DrawdownProjection",
    "ClockState",
]
