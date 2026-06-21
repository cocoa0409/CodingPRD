"""Domain types: status enums and role enum (commercial fleet leasing).

Note: FuelTransaction and TelematicsReading are append-style records carrying
only id + created_at (PRD §2.4) — they have no updated_at and no version.
"""
from enum import Enum


class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    LESSEE = "Lessee"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TELEMATICS_GATEWAY = "TelematicsGateway"


class LesseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DriverLicenseStatus(str, Enum):
    VALID = "VALID"
    SUSPENDED = "SUSPENDED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    IN_REPAIR = "IN_REPAIR"
    RETIRED = "RETIRED"


class VehicleClass(str, Enum):
    LIGHT_DUTY = "LIGHT_DUTY"
    MEDIUM_DUTY = "MEDIUM_DUTY"
    HEAVY_DUTY = "HEAVY_DUTY"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETURN_INITIATED = "RETURN_INITIATED"
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class OverageModel(str, Enum):
    CONTRACT_FLAT = "CONTRACT_FLAT"
    TIERED_EXCESS = "TIERED_EXCESS"


class WaterfallModel(str, Enum):
    DEDUCTIBLE_FIRST = "DEDUCTIBLE_FIRST"
    INSURANCE_FIRST = "INSURANCE_FIRST"


class AllocationStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class FuelCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class FuelTransactionStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    TOTAL_LOSS = "TOTAL_LOSS"
    TOTAL_LOSS_SETTLED = "TOTAL_LOSS_SETTLED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class IftaStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
