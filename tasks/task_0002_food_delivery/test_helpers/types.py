"""Domain types derived from scaffold Tables 1, 2, 7."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums (Table 2 — state machines)
# ---------------------------------------------------------------------------

class RestaurantStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RiderStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    PREPARING = "PREPARING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED_BY_CUSTOMER = "CANCELLED_BY_CUSTOMER"
    CANCELLED_BY_RESTAURANT = "CANCELLED_BY_RESTAURANT"
    CANCELLED_BY_PLATFORM = "CANCELLED_BY_PLATFORM"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class DeliveryStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    HEADING_TO_RESTAURANT = "HEADING_TO_RESTAURANT"
    AT_RESTAURANT = "AT_RESTAURANT"
    PICKED_UP = "PICKED_UP"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED_BY_RIDER = "CANCELLED_BY_RIDER"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    DISABLED = "DISABLED"


class RatingStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_CREDIT = "RESOLVED_CREDIT"
    RESOLVED_NO_ACTION = "RESOLVED_NO_ACTION"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class SurgeZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ---------------------------------------------------------------------------
# Domain enums
# ---------------------------------------------------------------------------

class VehicleType(str, Enum):
    BICYCLE = "BICYCLE"
    MOTORCYCLE = "MOTORCYCLE"
    CAR = "CAR"


class DiscountType(str, Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED_AMOUNT = "FIXED_AMOUNT"
    FREE_DELIVERY = "FREE_DELIVERY"


class RaterType(str, Enum):
    CUSTOMER_TO_RESTAURANT = "CUSTOMER_TO_RESTAURANT"
    CUSTOMER_TO_RIDER = "CUSTOMER_TO_RIDER"
    RESTAURANT_TO_RIDER = "RESTAURANT_TO_RIDER"


class ComplaintCategory(str, Enum):
    WRONG_ITEMS = "WRONG_ITEMS"
    MISSING_ITEMS = "MISSING_ITEMS"
    COLD_FOOD = "COLD_FOOD"
    LATE_DELIVERY = "LATE_DELIVERY"
    RUDE_BEHAVIOR = "RUDE_BEHAVIOR"
    DAMAGED_PACKAGING = "DAMAGED_PACKAGING"
    OTHER = "OTHER"


class FiledBy(str, Enum):
    CUSTOMER = "CUSTOMER"
    RESTAURANT = "RESTAURANT"
    RIDER = "RIDER"


class WalletTransactionType(str, Enum):
    TOP_UP = "TOP_UP"
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    CREDIT = "CREDIT"
    LOYALTY_REDEMPTION = "LOYALTY_REDEMPTION"


class PenaltyReason(str, Enum):
    LATE_DELIVERY = "LATE_DELIVERY"
    CANCELLATION = "CANCELLATION"
    COMPLAINT_UPHELD = "COMPLAINT_UPHELD"
    NO_SHOW = "NO_SHOW"


class SettlementEntityType(str, Enum):
    RESTAURANT = "RESTAURANT"
    RIDER = "RIDER"


class ResolutionType(str, Enum):
    REFUND = "REFUND"
    CREDIT = "CREDIT"
    NO_ACTION = "NO_ACTION"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    RESTAURANT = "restaurant"
    CUSTOMER = "customer"
    RIDER = "rider"
    CUSTOMER_SERVICE = "customer_service"
