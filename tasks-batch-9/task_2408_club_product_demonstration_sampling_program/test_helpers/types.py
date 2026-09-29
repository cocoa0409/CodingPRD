"""Domain vocabulary for the Club Demo Sampling API.

Every literal here is spelled exactly as the PRD spells it, so tests never
carry a bare string that could drift from the contract.
"""


class Role:
    """The five roles recognised on ``X-User-Role`` (PRD 2.1)."""

    PROGRAM_ADMIN = "ProgramAdmin"
    CLUB_OPERATIONS = "ClubOperations"
    MANUFACTURER = "Manufacturer"
    STAFFING_COORDINATOR = "StaffingCoordinator"
    DEMONSTRATOR = "Demonstrator"


class ProgramTier:
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    STANDARD = "STANDARD"


class AccountStatus:
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"
    SUSPENDED = "SUSPENDED"


class ClubTier:
    FLAGSHIP = "FLAGSHIP"
    STANDARD = "STANDARD"
    SATELLITE = "SATELLITE"


class ClubStatus:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class ProductCategory:
    BAKERY = "BAKERY"
    DAIRY = "DAIRY"
    FROZEN = "FROZEN"
    BEVERAGE = "BEVERAGE"
    SNACK = "SNACK"
    HOUSEHOLD = "HOUSEHOLD"
    ELECTRONICS = "ELECTRONICS"
    APPAREL = "APPAREL"


class DayPart:
    MORNING = "MORNING"
    MIDDAY = "MIDDAY"
    AFTERNOON = "AFTERNOON"


class EventType:
    FOOD_SAMPLING = "FOOD_SAMPLING"
    NON_FOOD_DEMO = "NON_FOOD_DEMO"


class BookingStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StaffingStatus:
    UNSTAFFED = "UNSTAFFED"
    PARTIALLY_STAFFED = "PARTIALLY_STAFFED"
    FULLY_STAFFED = "FULLY_STAFFED"
    EXECUTED = "EXECUTED"
    CLOSED_OUT = "CLOSED_OUT"


class SettlementStatus:
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CREDITED = "CREDITED"


class BookingAction:
    SUBMIT = "SUBMIT"
    REJECT = "REJECT"
    APPROVE = "APPROVE"
    REVOKE_APPROVAL = "REVOKE_APPROVAL"
    CLOSE_OUT = "CLOSE_OUT"
    CANCEL = "CANCEL"


class AssignmentRole:
    LEAD = "LEAD"
    SUPPORT = "SUPPORT"


class AssignmentStatus:
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RELEASED = "RELEASED"


class AssignmentAction:
    CONFIRM = "CONFIRM"
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    NO_SHOW = "NO_SHOW"
    RELEASE = "RELEASE"


class EmploymentStatus:
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class CertType:
    FOOD_HANDLER = "FOOD_HANDLER"
    ALLERGEN_AWARENESS = "ALLERGEN_AWARENESS"
    HEAT_EQUIPMENT = "HEAT_EQUIPMENT"


class CertStatus:
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class EquipmentType:
    CONVECTION_OVEN = "CONVECTION_OVEN"
    INDUCTION_COOKTOP = "INDUCTION_COOKTOP"
    REFRIGERATED_CART = "REFRIGERATED_CART"
    DISPLAY_TABLE = "DISPLAY_TABLE"
    TV_CART = "TV_CART"


class SanitationStatus:
    SANITIZED = "SANITIZED"
    IN_USE = "IN_USE"
    SOILED = "SOILED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReservationStatus:
    HELD = "HELD"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReservationAction:
    ACTIVATE = "ACTIVATE"
    RELEASE = "RELEASE"


class ShipmentStatus:
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    SHORT = "SHORT"
    REJECTED = "REJECTED"


class ReconStatus:
    OPEN = "OPEN"
    BALANCED = "BALANCED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    WRITTEN_OFF = "WRITTEN_OFF"


class MeasurementVariant:
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class WindowBoundary:
    CLOSED = "CLOSED"
    HALF_OPEN = "HALF_OPEN"


class MeasurementStatus:
    POSTED = "POSTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class InvoiceStatus:
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"
    PAID = "PAID"


class InvoiceAction:
    ISSUE = "ISSUE"
    VOID = "VOID"
    REDRAFT = "REDRAFT"
    RECORD_PAYMENT = "RECORD_PAYMENT"


class LineType:
    BASE = "BASE"
    ADDON = "ADDON"
    STAFFING = "STAFFING"
    HANDLING = "HANDLING"


class AddonService:
    EXTRA_TABLE = "EXTRA_TABLE"
    VIDEO_LOOP = "VIDEO_LOOP"
    ALLERGEN_SIGNAGE = "ALLERGEN_SIGNAGE"
    PREMIUM_PLACEMENT = "PREMIUM_PLACEMENT"
    BILINGUAL_DEMONSTRATOR = "BILINGUAL_DEMONSTRATOR"


class CreditReason:
    CLUB_CANCELLED = "CLUB_CANCELLED"
    MANUFACTURER_CANCELLED_EARLY = "MANUFACTURER_CANCELLED_EARLY"
    MANUFACTURER_CANCELLED_LATE = "MANUFACTURER_CANCELLED_LATE"
    PRODUCT_SHORT = "PRODUCT_SHORT"
    DEMONSTRATOR_NO_SHOW = "DEMONSTRATOR_NO_SHOW"


class CreditStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class CreditDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"
