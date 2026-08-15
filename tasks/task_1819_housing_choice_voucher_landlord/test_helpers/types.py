"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class LandlordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class UnitStatus(str, Enum):
    LISTED = "LISTED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SUSPENDED_ABATEMENT = "SUSPENDED_ABATEMENT"
    DELISTED = "DELISTED"


class VoucherFamilyStatus(str, Enum):
    SEARCHING = "SEARCHING"
    LEASED = "LEASED"
    PORTED_OUT = "PORTED_OUT"
    EXITED = "EXITED"


class HAPContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_INSPECTION = "PENDING_INSPECTION"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    ABATED = "ABATED"
    TERMINATED = "TERMINATED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REPAIR_VERIFICATION = "REPAIR_VERIFICATION"
    CLOSED = "CLOSED"


class InspectionType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    REINSPECTION = "REINSPECTION"
    COMPLAINT = "COMPLAINT"


class RepairItemStatus(str, Enum):
    OPEN = "OPEN"
    REPAIRED = "REPAIRED"
    VERIFIED = "VERIFIED"
    FAILED_VERIFICATION = "FAILED_VERIFICATION"


class RentIncreaseRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class RecertificationStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    ABATED_HELD = "ABATED_HELD"
    VOID = "VOID"


class PortabilityActionStatus(str, Enum):
    INITIATED = "INITIATED"
    BILLING_ACCEPTED = "BILLING_ACCEPTED"
    ABSORBED = "ABSORBED"
    TERMINATED = "TERMINATED"


class PortabilityActionType(str, Enum):
    PORT_IN = "PORT_IN"
    PORT_OUT = "PORT_OUT"


class UserRole(str, Enum):
    HOUSING_AUTHORITY_ADMIN = "HousingAuthorityAdmin"
    LANDLORD = "Landlord"
    INSPECTOR = "Inspector"


# Common-fields entities (id + created_at + updated_at + version) — PRD §2.4

class Landlord(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    landlord_id: str
    address: str
    zip_code: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    property_id: str
    unit_label: str
    bedroom_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VoucherFamily(TypedDict, total=False):
    id: str
    family_code: str
    voucher_bedroom_size: int
    annual_income_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentStandard(TypedDict, total=False):
    id: str
    zip_code: str
    bedroom_count: int
    amount_cents: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HAPContract(TypedDict, total=False):
    id: str
    unit_id: str
    family_id: str
    contract_rent_cents: int
    approved_rent_cents: int
    hap_portion_cents: int
    tenant_portion_cents: int
    lease_start_date: str
    status: str
    next_recert_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    contract_id: str
    inspection_type: str
    scheduled_date: str
    status: str
    result_recorded_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairItem(TypedDict, total=False):
    id: str
    inspection_id: str
    description: str
    is_life_threatening: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RentComparable(TypedDict, total=False):
    id: str
    zip_code: str
    bedroom_count: int
    rent_cents: int
    survey_date: str
    created_at: str
    updated_at: str
    version: int


class RentIncreaseRequest(TypedDict, total=False):
    id: str
    contract_id: str
    requested_rent_cents: int
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recertification(TypedDict, total=False):
    id: str
    contract_id: str
    due_date: str
    new_family_income_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PortabilityAction(TypedDict, total=False):
    id: str
    family_id: str
    destination_zip: str
    action_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


# HAPPayment is the exception in PRD §2.4: it carries ONLY id and created_at;
# both updated_at and version are absent on HAPPayment rows.
class HAPPayment(TypedDict, total=False):
    id: str
    contract_id: str
    period_month: str
    hap_amount_cents: int
    disbursement_status: str
    created_at: str
