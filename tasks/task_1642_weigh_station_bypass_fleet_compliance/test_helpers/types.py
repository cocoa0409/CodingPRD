"""Domain types: entity TypedDicts, status enums, role enum.

Carriers, state program configs, stations, vehicles, bypass credentials,
vehicle subscriptions, bypass disputes, eligibility overrides, and invoices
carry the full identity block (id, created_at, updated_at, version).
Safety-score snapshots, bypass events, and inspection reports are append-only
records and carry only id and created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class CarrierStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EligibilityStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    ELIGIBLE = "ELIGIBLE"
    CONDITIONAL = "CONDITIONAL"
    INELIGIBLE = "INELIGIBLE"


class SafetyRating(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    CONDITIONAL = "CONDITIONAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class SnapshotSource(str, Enum):
    FMCSA_FEED = "FMCSA_FEED"
    MANUAL_AUDIT = "MANUAL_AUDIT"


class ParticipationStatus(str, Enum):
    PILOT = "PILOT"
    PARTICIPATING = "PARTICIPATING"
    SUSPENDED = "SUSPENDED"


class StationType(str, Enum):
    FIXED_SCALE = "FIXED_SCALE"
    WIM_ONLY = "WIM_ONLY"
    MOBILE_PATROL = "MOBILE_PATROL"


class SupportedChannel(str, Enum):
    TRANSPONDER = "TRANSPONDER"
    MOBILE_APP = "MOBILE_APP"
    BOTH = "BOTH"


class OperationalStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    CLOSED_TEMP = "CLOSED_TEMP"
    CLOSED_PERM = "CLOSED_PERM"


class ServiceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class DeviceType(str, Enum):
    TRANSPONDER = "TRANSPONDER"
    MOBILE_APP = "MOBILE_APP"


class CredentialStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class CredentialStatusReason(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    SAFETY_INELIGIBLE = "SAFETY_INELIGIBLE"
    VEHICLE_RETIRED = "VEHICLE_RETIRED"
    CARRIER_TERMINATED = "CARRIER_TERMINATED"


class SubscriptionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class PaymentStanding(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


class ClosedReason(str, Enum):
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    TERMINATED_CARRIER = "TERMINATED_CARRIER"
    VEHICLE_RETIRED = "VEHICLE_RETIRED"


class Decision(str, Enum):
    BYPASS_GRANTED = "BYPASS_GRANTED"
    PULL_IN = "PULL_IN"


class DecisionReason(str, Enum):
    STATION_NOT_OPERATIONAL = "STATION_NOT_OPERATIONAL"
    STATION_TYPE_NO_BYPASS = "STATION_TYPE_NO_BYPASS"
    STATE_NOT_PARTICIPATING = "STATE_NOT_PARTICIPATING"
    CARRIER_NOT_ACTIVE = "CARRIER_NOT_ACTIVE"
    CARRIER_INELIGIBLE = "CARRIER_INELIGIBLE"
    ISS_ABOVE_STATE_THRESHOLD = "ISS_ABOVE_STATE_THRESHOLD"
    VEHICLE_OUT_OF_SERVICE = "VEHICLE_OUT_OF_SERVICE"
    NO_ACTIVE_CREDENTIAL = "NO_ACTIVE_CREDENTIAL"
    CHANNEL_UNSUPPORTED = "CHANNEL_UNSUPPORTED"
    PILOT_APP_ONLY = "PILOT_APP_ONLY"
    HAZMAT_NOT_PERMITTED = "HAZMAT_NOT_PERMITTED"
    OVERWEIGHT = "OVERWEIGHT"
    WEIGHT_NOT_CLEARED = "WEIGHT_NOT_CLEARED"
    CREDENTIALS_INCOMPLETE = "CREDENTIALS_INCOMPLETE"
    RANDOM_SCREEN = "RANDOM_SCREEN"
    RATE_CAP_EXCEEDED = "RATE_CAP_EXCEEDED"


class CredentialSet(str, Enum):
    IFTA = "IFTA"
    IRP = "IRP"
    UCR = "UCR"
    HOS_LOG = "HOS_LOG"


class DisputeStatus(str, Enum):
    OPENED = "OPENED"
    UPHELD = "UPHELD"
    APPEALED = "APPEALED"
    OVERTURNED = "OVERTURNED"
    UPHELD_FINAL = "UPHELD_FINAL"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class OverrideStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    STALE = "STALE"


class OverrideOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVOKE = "REVOKE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"


class TierApplied(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class InspectionLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class LedgerReason(str, Enum):
    DISPUTE_OVERTURN_CREDIT = "DISPUTE_OVERTURN_CREDIT"
    INVOICE_CREDIT_APPLICATION = "INVOICE_CREDIT_APPLICATION"


class RoiVariant(str, Enum):
    STANDARD = "STANDARD"
    CONSERVATIVE = "CONSERVATIVE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STATE_PROGRAM_MANAGER = "StateProgramManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CARRIER_MANAGER = "CarrierManager"
    SAFETY_DATA_FEED = "SafetyDataFeed"
    TELEMATICS_GATEWAY = "TelematicsGateway"
    FINANCE_ADMIN = "FinanceAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts — full identity block (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class CreditLedgerEntry(TypedDict, total=False):
    amount_cents: int
    reason: str
    reference_id: str
    recorded_at: str


class Carrier(TypedDict, total=False):
    id: str
    dot_number: str
    legal_name: str
    status: str
    eligibility_status: str
    latest_snapshot_id: Optional[str]
    latest_iss_score: Optional[int]
    latest_safety_rating: Optional[str]
    credit_balance_cents: int
    credit_ledger: List[CreditLedgerEntry]
    closed_billing_periods: List[str]
    created_at: str
    updated_at: str
    version: int


class StateProgramConfig(TypedDict, total=False):
    id: str
    state_code: str
    participation_status: str
    iss_refusal_threshold: int
    random_pull_in_rate_bps: int
    bypass_rate_cap_bps: int
    hazmat_bypass_allowed: bool
    requires_weight_clearance: bool
    credential_sets_required: List[str]
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict, total=False):
    id: str
    state_program_config_id: str
    station_code: str
    station_type: str
    supported_channel: str
    operational_status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    carrier_id: str
    vin: str
    plate_number: str
    plate_state: str
    home_state_code: str
    gvwr_lbs: int
    hazmat_endorsed: bool
    service_status: str
    created_at: str
    updated_at: str
    version: int


class BypassCredential(TypedDict, total=False):
    id: str
    vehicle_id: str
    carrier_id: str
    device_type: str
    device_serial: str
    status: str
    status_reason: str
    created_at: str
    updated_at: str
    version: int


class VehicleSubscription(TypedDict, total=False):
    id: str
    carrier_id: str
    vehicle_id: str
    service_start_date: str
    service_end_date: str
    status: str
    payment_standing: str
    paused_at: Optional[str]
    paused_days_current_period: int
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BypassDispute(TypedDict, total=False):
    id: str
    bypass_event_id: str
    carrier_id: str
    reason: str
    claimed_credit_cents: int
    status: str
    first_reviewer_id: Optional[str]
    appeal_reviewer_id: Optional[str]
    granted_credit_cents: Optional[int]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityOverride(TypedDict, total=False):
    id: str
    carrier_id: str
    reason: str
    start_date: str
    end_date: str
    status: str
    decided_by: Optional[str]
    approved_against_snapshot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    vehicle_id: str
    subscription_id: str
    tier_rate_cents: int
    surcharge_cents: int
    billable_days: int
    line_net_cents: int


class Invoice(TypedDict, total=False):
    id: str
    carrier_id: str
    period_year: int
    period_month: int
    lines: List[InvoiceLine]
    billed_line_count: int
    tier_applied: str
    gross_cents: int
    credit_applied_cents: int
    amount_due_cents: int
    due_date: str
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records — only id + created_at from the identity block
# ---------------------------------------------------------------------------

class SafetyScoreSnapshot(TypedDict, total=False):
    id: str
    carrier_id: str
    iss_score: int
    safety_rating: str
    source: str
    effective_date: str
    created_at: str


class BypassEvent(TypedDict, total=False):
    id: str
    vehicle_id: str
    station_id: str
    carrier_id: str
    approach_at: str
    measured_weight_lbs: Optional[int]
    credentials_presented: List[str]
    hazmat_load: bool
    decision: str
    decision_reasons: List[str]
    selected_credential_id: Optional[str]
    ruleset_version: int
    weight_verified: bool
    credentials_complete: bool
    screen_index: Optional[int]
    cap_granted_before: int
    cap_total_before: int
    created_at: str


class InspectionReport(TypedDict, total=False):
    id: str
    carrier_id: str
    vehicle_id: str
    inspection_level: str
    inspected_at: str
    violations_found: int
    out_of_service_order: bool
    created_at: str
