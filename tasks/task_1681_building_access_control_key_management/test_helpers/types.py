"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    SECURITY_ADMIN = "SecurityAdmin"
    SECURITY_OFFICER = "SecurityOfficer"
    FRONT_DESK = "FrontDesk"
    RESIDENT = "Resident"
    VENDOR = "Vendor"


class KeyNodeLevel(str, Enum):
    GRAND_MASTER = "GRAND_MASTER"
    MASTER = "MASTER"
    SUB_MASTER = "SUB_MASTER"
    CHANGE = "CHANGE"


class KeyNodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPROMISED = "COMPROMISED"
    RETIRED = "RETIRED"


class HardwareStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"


class CoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REKEY_REQUIRED = "REKEY_REQUIRED"


class PersonKind(str, Enum):
    RESIDENT = "RESIDENT"
    STAFF = "STAFF"
    VENDOR = "VENDOR"


class PersonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MOVED_OUT = "MOVED_OUT"
    TERMINATED = "TERMINATED"


class CredentialType(str, Enum):
    METAL_KEY = "METAL_KEY"
    FOB = "FOB"
    CARD = "CARD"


class CredentialStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ISSUED = "ISSUED"
    LOST = "LOST"
    DEACTIVATED = "DEACTIVATED"


class DeactivatedReason(str, Enum):
    MOVE_OUT = "MOVE_OUT"
    TERMINATION = "TERMINATION"
    EXPIRED = "EXPIRED"
    REKEY = "REKEY"
    INCIDENT = "INCIDENT"


class AccessOutcome(str, Enum):
    GRANTED = "GRANTED"
    DENIED_CREDENTIAL_NOT_ISSUED = "DENIED_CREDENTIAL_NOT_ISSUED"
    DENIED_CREDENTIAL_EXPIRED = "DENIED_CREDENTIAL_EXPIRED"
    DENIED_NOT_AUTHORIZED = "DENIED_NOT_AUTHORIZED"
    DENIED_OUTSIDE_WINDOW = "DENIED_OUTSIDE_WINDOW"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ResolvedReason(str, Enum):
    MANUAL = "MANUAL"
    DOOR_CLOSED = "DOOR_CLOSED"


class IncidentType(str, Enum):
    LOST_CREDENTIAL = "LOST_CREDENTIAL"
    PROPPED_DOOR = "PROPPED_DOOR"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ResolutionAction(str, Enum):
    NONE = "NONE"
    REQUEST_REKEY = "REQUEST_REKEY"
    DEACTIVATE_CREDENTIAL = "DEACTIVATE_CREDENTIAL"


class CampaignStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillTo(str, Enum):
    BUILDING = "BUILDING"
    PERSON = "PERSON"


class WorkOrderType(str, Enum):
    HARDWARE_REPAIR = "HARDWARE_REPAIR"
    INSPECTION = "INSPECTION"
    BATTERY_REPLACE = "BATTERY_REPLACE"
    REKEY = "REKEY"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChargeKind(str, Enum):
    MOVE_OUT_SETTLEMENT = "MOVE_OUT_SETTLEMENT"
    REKEY_CAMPAIGN = "REKEY_CAMPAIGN"
    KEY_REISSUE = "KEY_REISSUE"


class ChargeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class Building(TypedDict, total=False):
    id: str
    name: str
    audit_retention_days: int
    alert_escalation_minutes: int
    vendor_badge_pool_max: int
    default_propped_threshold_seconds: int
    base_fee_cents: int
    per_door_fee_cents: int
    per_key_reissue_fee_cents: int
    emergency_surcharge_pct: int
    business_open_utc: str
    business_close_utc: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class KeyNode(TypedDict, total=False):
    id: str
    building_id: str
    parent_id: Optional[str]
    level: str
    label: str
    status: str
    supersedes_node_id: Optional[str]
    seq: int
    stock_credential_count: int
    issued_credential_count: int
    lost_credential_count: int
    created_at: str
    updated_at: str
    version: int


class Door(TypedDict, total=False):
    id: str
    building_id: str
    door_code: str
    key_node_id: str
    bitting_code: str
    hardware_status: str
    core_status: str
    open_since: Optional[str]
    propped_threshold_seconds: int
    seq: int
    created_at: str
    updated_at: str
    version: int


class Person(TypedDict, total=False):
    id: str
    building_id: str
    full_name: str
    kind: str
    unit_label: Optional[str]
    employer_name: Optional[str]
    key_deposit_cents: int
    status: str
    moved_out_at: Optional[str]
    seq: int
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict, total=False):
    id: str
    building_id: str
    key_node_id: str
    serial_no: str
    type: str
    status: str
    holder_person_id: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str]
    lost_at: Optional[str]
    deactivated_reason: Optional[str]
    seq: int
    created_at: str
    updated_at: str
    version: int


class AccessGroup(TypedDict, total=False):
    id: str
    building_id: str
    name: str
    door_ids: List[str]
    person_ids: List[str]
    days_of_week: List[str]
    window_start_utc: str
    window_end_utc: str
    seq: int
    created_at: str
    updated_at: str
    version: int


class AccessEvent(TypedDict, total=False):
    # Append-only audit row: carries ONLY id + created_at from the common set;
    # no updated_at, no version.
    id: str
    building_id: str
    credential_id: str
    door_id: str
    occurred_at: str
    outcome: str
    archived: bool
    seq: int
    created_at: str


class ProppedDoorAlert(TypedDict, total=False):
    id: str
    building_id: str
    door_id: str
    opened_at: str
    status: str
    resolved_reason: Optional[str]
    incident_id: Optional[str]
    seq: int
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    building_id: str
    type: str
    status: str
    credential_id: Optional[str]
    door_id: Optional[str]
    alert_id: Optional[str]
    responsible_person_id: Optional[str]
    resolution_action: Optional[str]
    resolution_note: Optional[str]
    campaign_id: Optional[str]
    seq: int
    created_at: str
    updated_at: str
    version: int


class RekeyCampaign(TypedDict, total=False):
    id: str
    building_id: str
    key_node_id: str
    incident_id: Optional[str]
    status: str
    bill_to: str
    bill_person_id: Optional[str]
    rekey_seq: int
    affected_door_count: int
    affected_credential_count: int
    estimated_cost_cents: int
    final_cost_cents: Optional[int]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict, total=False):
    id: str
    building_id: str
    door_id: str
    campaign_id: Optional[str]
    target_key_node_id: Optional[str]
    type: str
    status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    actual_cost_cents: Optional[int]
    bill_person_id: Optional[str]
    seq: int
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict, total=False):
    id: str
    building_id: str
    person_id: Optional[str]
    campaign_id: Optional[str]
    kind: str
    amount_cents: int
    deposit_cents: Optional[int]
    provisional_refund_cents: Optional[int]
    final_forfeit_total_cents: Optional[int]
    final_refund_cents: Optional[int]
    line_items: List[dict]
    moved_out_at: Optional[str]
    status: str
    seq: int
    created_at: str
    updated_at: str
    version: int
