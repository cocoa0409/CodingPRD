"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CITY_REGISTRAR = "CityRegistrar"
    TAX_OFFICER = "TaxOfficer"
    HOST = "Host"
    PLATFORM = "Platform"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    LOTTERY_PENDING = "LOTTERY_PENDING"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class PermitType(str, Enum):
    PRIMARY_RESIDENCE = "PRIMARY_RESIDENCE"
    WHOLE_HOME = "WHOLE_HOME"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    DISMISSED = "DISMISSED"
    UPHELD = "UPHELD"


class ComplaintCategory(str, Enum):
    NOISE = "NOISE"
    TRASH = "TRASH"
    OVER_OCCUPANCY = "OVER_OCCUPANCY"
    UNPERMITTED = "UNPERMITTED"


class TaxFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    REMITTED = "REMITTED"
    DELINQUENT = "DELINQUENT"


class LotteryRoundStatus(str, Enum):
    OPEN = "OPEN"
    DRAWN = "DRAWN"


class HostStanding(str, Enum):
    GOOD = "GOOD"
    BARRED = "BARRED"


class MatchResult(str, Enum):
    MATCHED = "MATCHED"
    ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
    NO_PERMIT = "NO_PERMIT"
    PERMIT_INACTIVE = "PERMIT_INACTIVE"


# --- Entities (common_fields: true carry id/created_at/updated_at/version) ---

class Zone(TypedDict):
    id: str
    zone_code: str
    str_eligible: bool
    whole_home_allowed: bool
    permit_cap: int
    active_permit_count: int
    lottery_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Host(TypedDict):
    id: str
    email: str
    full_name: str
    primary_residence_property_id: Optional[str]
    strike_total: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    host_id: str
    zone_id: str
    street_address: str
    bedroom_count: int
    is_primary_residence: bool
    max_occupancy: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    property_id: str
    host_id: str
    zone_id: str
    permit_type: str
    attested_occupancy: int
    safety_attested: bool
    issued_at: Optional[str]
    expires_at: Optional[str]
    nightly_base_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LotteryRound(TypedDict):
    id: str
    zone_id: str
    seats_available: int
    awarded_permit_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    permit_id: str
    category: str
    strike_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxFiling(TypedDict):
    id: str
    permit_id: str
    period_year: int
    period_month: int
    nights_booked: int
    gross_revenue_cents: int
    tot_due_cents: Optional[int]
    penalty_cents: int
    amount_remitted_cents: int
    due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Platform(TypedDict):
    id: str
    platform_name: str
    api_key: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ListingReport(TypedDict):
    id: str
    platform_id: str
    claimed_permit_number: Optional[str]
    street_address: str
    reported_nights: int
    match_result: str
    matched_permit_id: Optional[str]
    created_at: str
