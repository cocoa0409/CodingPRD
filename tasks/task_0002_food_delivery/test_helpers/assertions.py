"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Primary entities with common fields (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

def assert_restaurant(data: dict):
    """Assert all expected fields on a Restaurant resource."""
    assert is_valid_uuid(data.get("id", "")), "Restaurant id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["name"], str) and len(data["name"]) > 0, "name must be a non-empty string"
    assert isinstance(data["cuisine_type"], str), "cuisine_type must be a string"
    assert isinstance(data["address"], str), "address must be a string"
    assert isinstance(data["latitude"], (int, float)), "latitude must be a number"
    assert isinstance(data["longitude"], (int, float)), "longitude must be a number"
    assert isinstance(data["commission_rate"], (int, float)), "commission_rate must be a number"
    assert 0.10 <= data["commission_rate"] <= 0.30, f"commission_rate must be 0.10-0.30, got {data['commission_rate']}"
    assert isinstance(data["average_prep_time_minutes"], int), "average_prep_time_minutes must be an integer"
    assert data["status"] in [
        "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "CLOSED"
    ], f"Invalid restaurant status: {data['status']}"
    assert isinstance(data.get("rating_average"), (int, float)), "rating_average must be a number"
    assert isinstance(data.get("rating_count"), int), "rating_count must be an integer"
    assert isinstance(data.get("total_orders_completed"), int), "total_orders_completed must be an integer"
    assert isinstance(data.get("balance_pending_cents"), int), "balance_pending_cents must be an integer"
    assert isinstance(data.get("balance_settled_cents"), int), "balance_settled_cents must be an integer"
    assert isinstance(data.get("is_accepting_orders"), bool), "is_accepting_orders must be a boolean"


def assert_menu_item(data: dict):
    """Assert all expected fields on a MenuItem resource."""
    assert is_valid_uuid(data.get("id", "")), "MenuItem id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("restaurant_id", "")), "restaurant_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0, "name must be a non-empty string"
    assert isinstance(data["base_price_cents"], int), "base_price_cents must be an integer"
    assert data["base_price_cents"] >= 100, f"base_price_cents must be >= 100, got {data['base_price_cents']}"
    assert isinstance(data["category"], str), "category must be a string"
    assert isinstance(data["is_available"], bool), "is_available must be a boolean"
    assert isinstance(data["prep_time_minutes"], int), "prep_time_minutes must be an integer"


def assert_customer(data: dict):
    """Assert all expected fields on a Customer resource."""
    assert is_valid_uuid(data.get("id", "")), "Customer id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["name"], str) and len(data["name"]) > 0, "name must be a non-empty string"
    assert isinstance(data["phone"], str), "phone must be a string"
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DELETED"], f"Invalid customer status: {data['status']}"
    assert isinstance(data.get("wallet_balance_cents"), int), "wallet_balance_cents must be an integer"
    assert isinstance(data.get("loyalty_points"), int), "loyalty_points must be an integer"
    assert isinstance(data.get("total_orders"), int), "total_orders must be an integer"


def assert_rider(data: dict):
    """Assert all expected fields on a Rider resource."""
    assert is_valid_uuid(data.get("id", "")), "Rider id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["name"], str) and len(data["name"]) > 0, "name must be a non-empty string"
    assert isinstance(data["phone"], str), "phone must be a string"
    assert data["vehicle_type"] in ["BICYCLE", "MOTORCYCLE", "CAR"], f"Invalid vehicle_type: {data['vehicle_type']}"
    assert data["status"] in [
        "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "DEACTIVATED"
    ], f"Invalid rider status: {data['status']}"
    assert isinstance(data.get("active_delivery_count"), int), "active_delivery_count must be an integer"
    assert isinstance(data.get("max_concurrent_deliveries"), int), "max_concurrent_deliveries must be an integer"
    assert isinstance(data.get("is_at_capacity"), bool), "is_at_capacity must be a boolean"
    assert isinstance(data.get("is_online"), bool), "is_online must be a boolean"
    assert isinstance(data.get("rating_average"), (int, float)), "rating_average must be a number"
    assert isinstance(data.get("rating_count"), int), "rating_count must be an integer"
    assert isinstance(data.get("total_deliveries_completed"), int), "total_deliveries_completed must be an integer"
    assert isinstance(data.get("cancellation_count"), int), "cancellation_count must be an integer"
    assert isinstance(data.get("cancellation_rate"), (int, float)), "cancellation_rate must be a number"
    assert isinstance(data.get("earnings_balance_cents"), int), "earnings_balance_cents must be an integer"
    assert isinstance(data.get("earnings_settled_cents"), int), "earnings_settled_cents must be an integer"
    assert isinstance(data.get("penalty_points"), int), "penalty_points must be an integer"


def assert_order(data: dict):
    """Assert all expected fields on an Order resource."""
    assert is_valid_uuid(data.get("id", "")), "Order id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_valid_uuid(data.get("restaurant_id", "")), "restaurant_id must be a valid UUID"
    assert isinstance(data["delivery_address"], str), "delivery_address must be a string"
    assert isinstance(data["delivery_latitude"], (int, float)), "delivery_latitude must be a number"
    assert isinstance(data["delivery_longitude"], (int, float)), "delivery_longitude must be a number"
    assert data["status"] in [
        "PLACED", "CONFIRMED", "PREPARING", "READY_FOR_PICKUP", "PICKED_UP",
        "DELIVERED", "CANCELLED_BY_CUSTOMER", "CANCELLED_BY_RESTAURANT", "CANCELLED_BY_PLATFORM",
    ], f"Invalid order status: {data['status']}"
    assert data["payment_status"] in [
        "PENDING", "AUTHORIZED", "CAPTURED", "REFUNDED", "PARTIALLY_REFUNDED",
    ], f"Invalid payment_status: {data['payment_status']}"
    assert isinstance(data["subtotal_cents"], int), "subtotal_cents must be an integer"
    assert isinstance(data["delivery_fee_cents"], int), "delivery_fee_cents must be an integer"
    assert isinstance(data["service_fee_cents"], int), "service_fee_cents must be an integer"
    assert isinstance(data["small_order_fee_cents"], int), "small_order_fee_cents must be an integer"
    assert isinstance(data["discount_cents"], int), "discount_cents must be an integer"
    assert isinstance(data["tip_cents"], int), "tip_cents must be an integer"
    assert isinstance(data["total_cents"], int), "total_cents must be an integer"
    assert data["total_cents"] >= 0, f"total_cents must be >= 0, got {data['total_cents']}"
    assert is_iso8601_timestamp(data.get("placed_at", "")), "placed_at must be ISO 8601"


def assert_order_item(data: dict):
    """Assert all expected fields on an OrderItem resource."""
    assert is_valid_uuid(data.get("id", "")), "OrderItem id must be a valid UUID"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert is_valid_uuid(data.get("menu_item_id", "")), "menu_item_id must be a valid UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1, "quantity must be >= 1"
    assert isinstance(data["unit_price_cents"], int), "unit_price_cents must be an integer"
    assert isinstance(data["item_total_cents"], int), "item_total_cents must be an integer"


def assert_delivery(data: dict):
    """Assert all expected fields on a Delivery resource."""
    assert is_valid_uuid(data.get("id", "")), "Delivery id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert is_valid_uuid(data.get("rider_id", "")), "rider_id must be a valid UUID"
    assert data["status"] in [
        "ASSIGNED", "HEADING_TO_RESTAURANT", "AT_RESTAURANT", "PICKED_UP",
        "EN_ROUTE", "DELIVERED", "FAILED", "CANCELLED_BY_RIDER",
    ], f"Invalid delivery status: {data['status']}"
    assert isinstance(data["distance_km"], (int, float)), "distance_km must be a number"
    assert isinstance(data["rider_earnings_cents"], int), "rider_earnings_cents must be an integer"
    assert is_iso8601_timestamp(data.get("assigned_at", "")), "assigned_at must be ISO 8601"


def assert_promotion(data: dict):
    """Assert all expected fields on a Promotion resource."""
    assert is_valid_uuid(data.get("id", "")), "Promotion id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["code"], str), "code must be a string"
    assert data["discount_type"] in ["PERCENTAGE", "FIXED_AMOUNT", "FREE_DELIVERY"], \
        f"Invalid discount_type: {data['discount_type']}"
    assert isinstance(data["discount_value"], int), "discount_value must be an integer"
    assert isinstance(data["minimum_order_cents"], int), "minimum_order_cents must be an integer"
    assert isinstance(data["max_uses"], int), "max_uses must be an integer"
    assert isinstance(data["current_uses"], int), "current_uses must be an integer"
    assert data["status"] in ["ACTIVE", "EXPIRED", "EXHAUSTED", "DISABLED"], \
        f"Invalid promotion status: {data['status']}"


def assert_rating(data: dict):
    """Assert all expected fields on a Rating resource."""
    assert is_valid_uuid(data.get("id", "")), "Rating id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert data["rater_type"] in [
        "CUSTOMER_TO_RESTAURANT", "CUSTOMER_TO_RIDER", "RESTAURANT_TO_RIDER"
    ], f"Invalid rater_type: {data['rater_type']}"
    assert isinstance(data["score"], int), "score must be an integer"
    assert 1 <= data["score"] <= 5, f"score must be 1-5, got {data['score']}"
    assert data["status"] in ["PENDING", "PUBLISHED", "HIDDEN"], f"Invalid rating status: {data['status']}"


def assert_complaint(data: dict):
    """Assert all expected fields on a Complaint resource."""
    assert is_valid_uuid(data.get("id", "")), "Complaint id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert data["filed_by"] in ["CUSTOMER", "RESTAURANT", "RIDER"], f"Invalid filed_by: {data['filed_by']}"
    assert data["category"] in [
        "WRONG_ITEMS", "MISSING_ITEMS", "COLD_FOOD", "LATE_DELIVERY",
        "RUDE_BEHAVIOR", "DAMAGED_PACKAGING", "OTHER"
    ], f"Invalid complaint category: {data['category']}"
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "RESOLVED_REFUND", "RESOLVED_CREDIT",
        "RESOLVED_NO_ACTION", "ESCALATED", "CLOSED"
    ], f"Invalid complaint status: {data['status']}"


def assert_settlement(data: dict):
    """Assert all expected fields on a Settlement resource (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "Settlement id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entity_type"] in ["RESTAURANT", "RIDER"], f"Invalid entity_type: {data['entity_type']}"
    assert is_valid_uuid(data.get("entity_id", "")), "entity_id must be a valid UUID"
    assert isinstance(data["gross_amount_cents"], int), "gross_amount_cents must be an integer"
    assert isinstance(data["deductions_cents"], int), "deductions_cents must be an integer"
    assert isinstance(data["net_amount_cents"], int), "net_amount_cents must be an integer"
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["deductions_cents"], \
        "net_amount_cents must equal gross_amount_cents - deductions_cents"
    assert data["status"] in ["DRAFT", "CALCULATED", "APPROVED", "PAID", "DISPUTED"], \
        f"Invalid settlement status: {data['status']}"


def assert_surge_zone(data: dict):
    """Assert all expected fields on a SurgeZone resource."""
    assert is_valid_uuid(data.get("id", "")), "SurgeZone id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["zone_name"], str), "zone_name must be a string"
    assert isinstance(data["surge_multiplier"], (int, float)), "surge_multiplier must be a number"
    assert 1.0 <= data["surge_multiplier"] <= 3.0, f"surge_multiplier must be 1.0-3.0, got {data['surge_multiplier']}"
    assert data["status"] in ["ACTIVE", "INACTIVE"], f"Invalid surge zone status: {data['status']}"


def assert_wallet_transaction(data: dict):
    """Assert all expected fields on a WalletTransaction (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "WalletTransaction id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert data["type"] in ["TOP_UP", "PAYMENT", "REFUND", "CREDIT", "LOYALTY_REDEMPTION"], \
        f"Invalid wallet transaction type: {data['type']}"
    assert isinstance(data["amount_cents"], int), "amount_cents must be an integer"
    assert isinstance(data["balance_after_cents"], int), "balance_after_cents must be an integer"


def assert_rider_penalty_log(data: dict):
    """Assert all expected fields on a RiderPenaltyLog (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "RiderPenaltyLog id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("rider_id", "")), "rider_id must be a valid UUID"
    assert data["reason"] in ["LATE_DELIVERY", "CANCELLATION", "COMPLAINT_UPHELD", "NO_SHOW"], \
        f"Invalid penalty reason: {data['reason']}"
    assert isinstance(data["points"], int) and data["points"] > 0, "points must be a positive integer"
    assert isinstance(data["cumulative_points"], int), "cumulative_points must be an integer"
