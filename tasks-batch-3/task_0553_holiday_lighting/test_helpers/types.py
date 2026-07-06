"""Domain types: entity status enums and the role enum.

Every persisted resource in this system carries the common system-managed fields
id / created_at / updated_at / version (PRD §2.5), so no entity is append-only.
"""
from enum import Enum


class UserRole(str, Enum):
    SALES_REP = "SalesRep"
    CUSTOMER = "Customer"
    DISPATCHER = "Dispatcher"
    CREW_LEAD = "CrewLead"
    BILLING_ADMIN = "BillingAdmin"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWED = "RENEWED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ContractType(str, Enum):
    SEASONAL_RENTAL = "SEASONAL_RENTAL"
    PERMANENT_PURCHASE = "PERMANENT_PURCHASE"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"


class ProductLine(str, Enum):
    SEASONAL = "SEASONAL"
    PERMANENT = "PERMANENT"


class RooflineComplexity(str, Enum):
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"


class RouteDayStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class RouteAssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    DISPATCHED = "DISPATCHED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class JobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class JobType(str, Enum):
    INSTALL = "INSTALL"
    TAKEDOWN = "TAKEDOWN"
    SERVICE = "SERVICE"


class ServiceCallStatus(str, Enum):
    OPEN = "OPEN"
    CLASSIFIED = "CLASSIFIED"
    SCHEDULED = "SCHEDULED"
    RESOLVED = "RESOLVED"


class ServiceClassification(str, Enum):
    WARRANTY = "WARRANTY"
    BILLABLE = "BILLABLE"


class ServiceCause(str, Enum):
    WEATHER = "WEATHER"
    DEFECT = "DEFECT"
    VANDALISM = "VANDALISM"


class StorageRecordStatus(str, Enum):
    STORED = "STORED"
    RETRIEVED = "RETRIEVED"
    DISPOSED = "DISPOSED"


class FinancingPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class InvoiceSourceType(str, Enum):
    INSTALL = "INSTALL"
    STORAGE = "STORAGE"
    SERVICE = "SERVICE"
    MANUAL = "MANUAL"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"
