"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 common-fields split:

- Top-level resources (Borrower, Property, SeniorLien, Heloc) carry id +
  created_at + updated_at + version. PRD §2.4: "The version field is an
  integer that begins at 1 on creation and increments by exactly one
  with every mutation to the resource."

- Ledger-style child resources of a HELOC (Draw, Payment, RateReset,
  Fee, DefaultEvent) and audit-log entities (InsuranceEvent,
  SeniorLienDefaultEvent, BankruptcyEvent) are written-once and
  immutable. PRD §2.4: "Each of these still carries an id (server-minted
  UUID) and a created_at timestamp, but they do not carry updated_at or
  version — both fields are absent from their responses because no
  in-place mutation is ever performed on them."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ORIGINATOR = "Originator"
    SERVICER = "Servicer"
    BORROWER = "Borrower"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Heloc lifecycle status — PRD §3.2, §3.6, §3.9
# ---------------------------------------------------------------------------
class HelocStatus(str, Enum):
    PENDING = "PENDING"
    DRAW = "DRAW"
    REPAY = "REPAY"
    DEFAULT = "DEFAULT"
    CLOSED = "CLOSED"


class DefaultTrigger(str, Enum):
    DELINQUENCY_90 = "DELINQUENCY_90"
    INSURANCE_LAPSE = "INSURANCE_LAPSE"
    SENIOR_LIEN_DEFAULT = "SENIOR_LIEN_DEFAULT"
    BANKRUPTCY = "BANKRUPTCY"


# ---------------------------------------------------------------------------
# Property — PRD §3.1
# ---------------------------------------------------------------------------
class Occupancy(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    INVESTMENT = "INVESTMENT"


class InsuranceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class InsuranceEventType(str, Enum):
    LAPSE = "LAPSE"
    REINSTATE = "REINSTATE"


# ---------------------------------------------------------------------------
# SeniorLien — PRD §3.1, §3.6
# ---------------------------------------------------------------------------
class SeniorLienStatus(str, Enum):
    CURRENT = "CURRENT"
    DEFAULTED = "DEFAULTED"


# ---------------------------------------------------------------------------
# Fee — PRD §3.8, §3.9
# ---------------------------------------------------------------------------
class FeeType(str, Enum):
    ANNUAL = "ANNUAL"
    EARLY_CLOSURE = "EARLY_CLOSURE"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================

# --- Top-level resources: carry id + created_at + updated_at + version ---


class Borrower(TypedDict, total=False):
    """PRD §3.1 Borrower."""
    id: str
    full_name: str
    email: str
    bankruptcy_flag: bool
    bankruptcy_filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    """PRD §3.1 Property."""
    id: str
    borrower_id: str
    address: str
    appraised_value_cents: int
    occupancy: str
    insurance_status: str
    insurance_lapsed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeniorLien(TypedDict, total=False):
    """PRD §3.1 SeniorLien."""
    id: str
    property_id: str
    holder_name: str
    principal_balance_cents: int
    status: str
    defaulted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Heloc(TypedDict, total=False):
    """PRD §3.2, §3.3, §3.4, §3.5, §3.6, §3.7, §3.8, §3.9, §3.10 Heloc."""
    id: str
    borrower_id: str
    property_id: str
    credit_limit_cents: int
    margin_bps: int
    periodic_cap_bps: int
    lifetime_cap_bps: int
    lifetime_floor_bps: int
    initial_rate_bps: int
    current_rate_bps: int
    origination_date: Optional[str]
    draw_period_end_date: Optional[str]
    repayment_period_end_date: Optional[str]
    repayment_term_years: int
    principal_balance_cents: int
    available_credit_cents: int
    accrued_interest_cents: int
    minimum_payment_due_cents: int
    status: str
    delinquency_days: int
    annual_fee_cents: int
    annual_fee_waived_first_year: bool
    early_closure_fee_cents: int
    defaulted_at: Optional[str]
    default_trigger: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Ledger / audit-log resources: carry ONLY id + created_at ---


class Draw(TypedDict, total=False):
    """PRD §3.3 Draw (immutable ledger entry)."""
    id: str
    heloc_id: str
    amount_cents: int
    drawn_at: str
    created_at: str


class Payment(TypedDict, total=False):
    """PRD §3.4 Payment (immutable ledger entry)."""
    id: str
    heloc_id: str
    amount_cents: int
    interest_component_cents: int
    principal_component_cents: int
    posted_at: str
    created_at: str


class RateReset(TypedDict, total=False):
    """PRD §3.5 RateReset (immutable ledger entry)."""
    id: str
    heloc_id: str
    prime_rate_bps: int
    requested_rate_bps: int
    applied_rate_bps: int
    reset_at: str
    created_at: str


class Fee(TypedDict, total=False):
    """PRD §3.8, §3.9 Fee (immutable ledger entry)."""
    id: str
    heloc_id: str
    fee_type: str
    amount_cents: int
    status: str
    assessed_at: str
    created_at: str


class DefaultEvent(TypedDict, total=False):
    """PRD §3.6 DefaultEvent (immutable audit log)."""
    id: str
    heloc_id: str
    trigger: str
    source_event_id: Optional[str]
    recorded_at: str
    created_at: str


class InsuranceEvent(TypedDict, total=False):
    """PRD §3.6 InsuranceEvent (immutable audit log)."""
    id: str
    property_id: str
    event_type: str
    recorded_at: str
    created_at: str


class SeniorLienDefaultEvent(TypedDict, total=False):
    """PRD §3.6 SeniorLienDefaultEvent (immutable audit log)."""
    id: str
    senior_lien_id: str
    recorded_at: str
    created_at: str


class BankruptcyEvent(TypedDict, total=False):
    """PRD §3.6 BankruptcyEvent (immutable audit log)."""
    id: str
    borrower_id: str
    recorded_at: str
    created_at: str


__all__ = [
    "UserRole",
    "HelocStatus",
    "DefaultTrigger",
    "Occupancy",
    "InsuranceStatus",
    "InsuranceEventType",
    "SeniorLienStatus",
    "FeeType",
    "FeeStatus",
    "Borrower",
    "Property",
    "SeniorLien",
    "Heloc",
    "Draw",
    "Payment",
    "RateReset",
    "Fee",
    "DefaultEvent",
    "InsuranceEvent",
    "SeniorLienDefaultEvent",
    "BankruptcyEvent",
]
