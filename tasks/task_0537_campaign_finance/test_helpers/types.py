"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    TREASURER = "Treasurer"
    REGULATOR_AUDITOR = "RegulatorAuditor"
    LOBBY_REGISTRANT = "LobbyRegistrant"
    PUBLIC_VIEWER = "PublicViewer"


class CommitteeType(str, Enum):
    CANDIDATE = "CANDIDATE"
    PAC = "PAC"
    PARTY = "PARTY"


class ContributorType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    PAC = "PAC"
    PARTY = "PARTY"
    CORPORATION = "CORPORATION"
    UNION = "UNION"
    FOREIGN_NATIONAL = "FOREIGN_NATIONAL"


class CommitteeStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SolvencyStatus(str, Enum):
    SOLVENT = "SOLVENT"
    DEFICIT = "DEFICIT"


class SettlementStatus(str, Enum):
    RECORDED = "RECORDED"
    DEPOSITED = "DEPOSITED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    UNDER_AUDIT = "UNDER_AUDIT"
    SUPERSEDED = "SUPERSEDED"


class PenaltyStatus(str, Enum):
    NONE = "NONE"
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"


class RegistrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ActivityStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


# common_fields: true — carries id + created_at + updated_at + version
class Committee(TypedDict):
    id: str
    name: str
    committee_type: str
    election_cycle: str
    jurisdiction: str
    treasurer_name: str
    status: str
    total_receipts_cents: int
    total_disbursements_cents: int
    total_penalties_cents: int
    cash_on_hand_cents: int
    solvency_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Contribution(TypedDict):
    id: str
    committee_id: str
    contributor_ref: str
    contributor_name: str
    contributor_type: str
    amount_cents: int
    contribution_date: str
    matchable_amount_cents: int
    settlement_status: str
    review_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only immutable, carries ONLY id + created_at
class Expenditure(TypedDict):
    id: str
    committee_id: str
    payee_name: str
    amount_cents: int
    expenditure_date: str
    purpose: str
    created_at: str


# common_fields: true
class ReportingPeriod(TypedDict):
    id: str
    jurisdiction: str
    election_cycle: str
    period_label: str
    period_start: str
    period_end: str
    filing_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Report(TypedDict):
    id: str
    committee_id: str
    period_id: str
    supersedes_report_id: Optional[str]
    amendment_seq: int
    status: str
    total_receipts_cents: int
    total_disbursements_cents: int
    matching_funds_cents: int
    filed_at: Optional[str]
    is_late: bool
    days_late: int
    penalty_status: str
    penalty_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LobbyingRegistrant(TypedDict):
    id: str
    name: str
    registrant_contact: str
    jurisdiction: str
    status: str
    total_committed_spend_cents: int
    total_certified_spend_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Client(TypedDict):
    id: str
    registrant_id: str
    client_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LobbyingReportingPeriod(TypedDict):
    id: str
    jurisdiction: str
    period_label: str
    period_start: str
    period_end: str
    filing_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LobbyingActivity(TypedDict):
    id: str
    registrant_id: str
    client_id: str
    period_id: str
    lobbyist_name: str
    subject: str
    amount_cents: int
    activity_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
