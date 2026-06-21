"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the common fields id, created_at, updated_at,
and version (PRD section 2.4), so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums --------------------------------------------------------

class VisitStatus(str, Enum):
    PREREGISTERED = "PREREGISTERED"
    SCREENING = "SCREENING"
    FLAGGED = "FLAGGED"
    DENIED = "DENIED"
    CLEARED = "CLEARED"
    SIGNED_IN = "SIGNED_IN"
    SIGNED_OUT = "SIGNED_OUT"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    VOID = "VOID"


class ContractorPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class DeliveryLogStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PICKED_UP = "PICKED_UP"


class Department(str, Enum):
    ENGINEERING = "ENGINEERING"
    SALES = "SALES"
    FACILITIES = "FACILITIES"
    EXECUTIVE = "EXECUTIVE"


class MatchType(str, Enum):
    NAME = "NAME"
    COMPANY = "COMPANY"


class Severity(str, Enum):
    REVIEW = "REVIEW"
    DENY = "DENY"


class DocumentKind(str, Enum):
    NDA = "NDA"
    SAFETY_WAIVER = "SAFETY_WAIVER"
    DATA_POLICY = "DATA_POLICY"


class Carrier(str, Enum):
    FEDEX = "FEDEX"
    UPS = "UPS"
    USPS = "USPS"
    DHL = "DHL"
    COURIER = "COURIER"


class TriggeredReason(str, Enum):
    FIRE_DRILL = "FIRE_DRILL"
    FIRE_ALARM = "FIRE_ALARM"
    GAS_LEAK = "GAS_LEAK"
    OTHER = "OTHER"


class UserRole(str, Enum):
    SECURITY_OFFICER = "SecurityOfficer"
    LOBBY_ATTENDANT = "LobbyAttendant"
    HOST = "Host"


# --- Entity TypedDicts ---------------------------------------------------

class Site(TypedDict):
    id: str
    name: str
    timezone: str
    badge_total: int
    badge_in_use: int
    badge_available: int
    created_at: str
    updated_at: str
    version: int


class Floor(TypedDict):
    id: str
    site_id: str
    label: str
    capacity: int
    current_occupancy: int
    available_slots: int
    created_at: str
    updated_at: str
    version: int


class Host(TypedDict):
    id: str
    site_id: str
    full_name: str
    email: str
    department: str
    notify_count: int
    created_at: str
    updated_at: str
    version: int


class WatchlistEntry(TypedDict):
    id: str
    site_id: str
    match_type: str
    match_value_normalized: str
    severity: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class MeetingRoom(TypedDict):
    id: str
    floor_id: str
    name: str
    seats: int
    created_at: str
    updated_at: str
    version: int


class ParkingSpace(TypedDict):
    id: str
    site_id: str
    bay_label: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    site_id: str
    host_id: str
    floor_id: str
    room_id: Optional[str]
    parking_space_id: Optional[str]
    contractor_pass_id: Optional[str]
    visitor_full_name: str
    visitor_company: str
    scheduled_start: str
    scheduled_end: str
    id_scanned: bool
    status: str
    risk_score: int
    sign_in_at: Optional[str]
    sign_out_at: Optional[str]
    visit_duration_minutes: Optional[int]
    badge_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict):
    id: str
    visit_id: str
    document_kind: str
    document_version: str
    status: str
    signed_at: Optional[str]
    signer_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractorPass(TypedDict):
    id: str
    host_id: str
    contractor_name: str
    contractor_company: str
    access_valid_from: str
    access_valid_until: str
    status: str
    covered_visit_count: int
    created_at: str
    updated_at: str
    version: int


class DeliveryLog(TypedDict):
    id: str
    host_id: str
    carrier: str
    parcel_fees_cents: List[int]
    status: str
    handling_invoice_cents: int
    picked_up_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvacuationEvent(TypedDict):
    id: str
    floor_id: str
    triggered_reason: str
    roster_visit_ids: List[str]
    roster_head_count: int
    created_at: str
    updated_at: str
    version: int
