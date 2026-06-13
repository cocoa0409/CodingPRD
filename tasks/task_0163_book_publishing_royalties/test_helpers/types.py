"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TitleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    OUT_OF_PRINT = "OUT_OF_PRINT"


class FormatType(str, Enum):
    HARDCOVER = "HARDCOVER"
    PAPERBACK = "PAPERBACK"
    EBOOK = "EBOOK"
    AUDIO = "AUDIO"


class SalesPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STATEMENTED = "STATEMENTED"


class ReturnsReserveStatus(str, Enum):
    HELD = "HELD"
    LIQUIDATED = "LIQUIDATED"


class SubsidiaryRightType(str, Enum):
    FOREIGN = "FOREIGN"
    AUDIO = "AUDIO"
    FILM = "FILM"


class SubsidiaryRightStatus(str, Enum):
    REGISTERED = "REGISTERED"
    STATEMENTED = "STATEMENTED"
    VOID = "VOID"


class AuthorStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class StatementLineType(str, Enum):
    ROYALTY = "ROYALTY"
    RESERVE_WITHHELD = "RESERVE_WITHHELD"
    RESERVE_RELEASED = "RESERVE_RELEASED"
    SUBSIDIARY = "SUBSIDIARY"
    ADVANCE_RECOUP = "ADVANCE_RECOUP"
    AGENT_COMMISSION = "AGENT_COMMISSION"
    TAX_WITHHELD = "TAX_WITHHELD"
    NET_PAYABLE = "NET_PAYABLE"


class UserRole(str, Enum):
    PUBLISHER = "Publisher"
    AUTHOR = "Author"
    AGENT = "Agent"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
class Author(TypedDict):
    id: str
    full_name: str
    email: str
    tax_withholding_pct: float
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict):
    id: str
    agency_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    author_id: str
    agent_id: Optional[str]
    advance_cents: int
    unrecouped_advance_cents: int
    agent_commission_pct: float
    reserve_pct: float
    reserve_hold_periods: int
    status: str
    lifetime_net_units: int
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    contract_id: str
    name: str
    edition: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Format(TypedDict):
    id: str
    title_id: str
    format_type: str
    list_price_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, id + created_at only
class RoyaltyTier(TypedDict):
    id: str
    contract_id: str
    lower_unit: int
    upper_unit: Optional[int]
    rate: float
    created_at: str


class SalesPeriod(TypedDict):
    id: str
    contract_id: str
    label: str
    sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesRecord(TypedDict):
    id: str
    period_id: str
    format_id: str
    units_sold: int
    units_returned: int
    created_at: str
    updated_at: str
    version: int


class ReturnsReserve(TypedDict):
    id: str
    contract_id: str
    origin_statement_id: str
    reserve_units: int
    reserve_held_cents: int
    reserve_unit_value_cents: float
    eligible_sequence: int
    released_cents: int
    consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubsidiaryRight(TypedDict):
    id: str
    contract_id: str
    right_type: str
    proceeds_cents: int
    author_share_pct: float
    author_income_cents: int
    status: str
    statement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuthorStatement(TypedDict):
    id: str
    contract_id: str
    period_id: str
    gross_royalty_cents: int
    reserve_held_cents: int
    royalty_credited_cents: int
    reserve_released_cents: int
    subsidiary_income_cents: int
    period_earnings_cents: int
    advance_recouped_cents: int
    payable_before_commission_cents: int
    agent_commission_cents: int
    tax_withheld_cents: int
    net_to_author_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable ledger artifact, id + created_at only
class StatementLine(TypedDict):
    id: str
    statement_id: str
    line_type: str
    amount_cents: int
    memo: str
    created_at: str
