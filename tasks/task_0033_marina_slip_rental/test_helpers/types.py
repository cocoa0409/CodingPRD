"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status Enums (PRD §3) ───────────────────────────────────────


class SlipStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class LeaseStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class TenantLiveaboardStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class PumpOutRequestStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TowAssistOutcome(str, Enum):
    COVERED = "COVERED"
    OUT_OF_RADIUS = "OUT_OF_RADIUS"
    INSURANCE_INVALID = "INSURANCE_INVALID"


class TransferWaitlistStatus(str, Enum):
    QUEUED = "QUEUED"
    PROMOTED = "PROMOTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PowerAmp(str, Enum):
    NONE = "NONE"
    A30 = "A30"
    A50 = "A50"
    A100 = "A100"


class UserRole(str, Enum):
    HARBOR_MASTER = "HarborMaster"
    MARINA_STAFF = "MarinaStaff"
    TENANT = "Tenant"


# ─── Entity TypedDicts (PRD §2.4, §3.1–§3.9) ─────────────────────
# Marina, Slip, Vessel, Tenant, Lease, PumpOutRequest, TransferWaitlistEntry
# carry the full common-field set (id, created_at, updated_at, version).
# TowAssistEvent is append-only (PRD §2.4): only id + created_at.


class Marina(TypedDict, total=False):
    id: str
    name: str
    harbor_code: str
    liveaboard_cap: int
    liveaboard_current_count: int
    season_summer_start: str
    season_summer_end: str
    tow_assist_radius_nm: float
    created_at: str
    updated_at: str
    version: int


class Slip(TypedDict, total=False):
    id: str
    marina_id: str
    slip_number: str
    length_ft: float
    beam_ft: float
    power_amp: str
    pumpout_available: bool
    liveaboard_allowed: bool
    base_daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    tenant_id: str
    name: str
    loa_ft: float
    beam_ft: float
    insurance_policy_number: str
    insurance_expires_on: str
    insurance_coverage_cents: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    liveaboard_status: str
    liveaboard_approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    marina_id: str
    slip_id: str
    tenant_id: str
    vessel_id: str
    start_date: str
    end_date: str
    is_liveaboard: bool
    nightly_rate_cents: int
    total_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PumpOutRequest(TypedDict, total=False):
    id: str
    lease_id: str
    requested_at: str
    completed_at: Optional[str]
    status: str
    charge_cents: int
    created_at: str
    updated_at: str
    version: int


# TowAssistEvent is append-only (PRD §2.4): no updated_at, no version.
class TowAssistEvent(TypedDict, total=False):
    id: str
    tenant_id: str
    vessel_id: str
    marina_id: str
    incident_distance_nm: float
    outcome: str
    dispatched_at: str
    created_at: str


class TransferWaitlistEntry(TypedDict, total=False):
    id: str
    marina_id: str
    tenant_id: str
    from_lease_id: str
    target_slip_id: str
    requested_at: str
    position: int
    status: str
    created_at: str
    updated_at: str
    version: int
