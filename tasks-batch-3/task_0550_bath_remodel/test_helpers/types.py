"""Domain types: entity TypedDicts, status enums, role enum for the Bath Remodel API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DESIGNER = "Designer"
    FINANCE_OFFICER = "FinanceOfficer"
    INSTALL_COORDINATOR = "InstallCoordinator"
    PLATFORM_ADMIN = "PlatformAdmin"


class ProjectStatus(str, Enum):
    LEAD = "LEAD"
    DESIGN_SCHEDULED = "DESIGN_SCHEDULED"
    DESIGN_COMPLETE = "DESIGN_COMPLETE"
    QUOTED = "QUOTED"
    SOLD = "SOLD"
    PERMIT_PENDING = "PERMIT_PENDING"
    INSTALL_READY = "INSTALL_READY"
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WarrantyStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class FinancingStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimResolution(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    DENIED = "DENIED"


class ReferralStatus(str, Enum):
    ISSUED = "ISSUED"
    REGISTERED = "REGISTERED"
    REWARDED = "REWARDED"
    VOID = "VOID"


# --- Entity TypedDicts (every entity carries id/created_at/updated_at/version) ---

class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    street_address: str
    city: str
    state_code: str
    postal_code: str
    referral_code_used: Optional[str]
    referral_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Designer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    region_state_code: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    crew_name: str
    home_state_code: str
    max_installs_per_day: int
    accessibility_certified: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    customer_id: str
    designer_id: Optional[str]
    state_code: str
    bathroom_type: str
    status: str
    measured_wall_area_sqft: Optional[float]
    permit_required: Optional[bool]
    requires_accessible_crew: Optional[bool]
    permit_status: str
    accepted_quote_total_cents: Optional[int]
    warranty_status: str
    warranty_issued_date: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DesignAppointment(TypedDict, total=False):
    id: str
    project_id: str
    designer_id: str
    scheduled_start: str
    scheduled_end: str
    measured_wall_area_sqft: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    project_id: str
    wall_system: str
    color: str
    accessibility_addon: str
    wall_area_sqft: float
    promo_code: Optional[str]
    system_price_cents: int
    addon_price_cents: int
    discount_cents: int
    net_price_cents: int
    permit_surcharge_cents: Optional[int]
    final_total_cents: Optional[int]
    status: str
    financing_plan_code: Optional[str]
    financing_status: str
    requested_amount_cents: Optional[int]
    stated_annual_income_cents: Optional[int]
    deposit_cents: Optional[int]
    financed_amount_cents: Optional[int]
    approved_apr_bps: Optional[int]
    monthly_payment_cents: Optional[int]
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class InstallBooking(TypedDict, total=False):
    id: str
    project_id: str
    crew_id: str
    install_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    project_id: str
    defect_type: str
    description: str
    status: str
    resolution: Optional[str]
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    referrer_customer_id: str
    referred_customer_id: Optional[str]
    referred_project_id: Optional[str]
    referral_code: str
    program_tier: str
    status: str
    reward_cents: int
    created_at: str
    updated_at: str
    version: int
