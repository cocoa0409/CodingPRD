"""Error classes with the catalog's exact error_id values and HTTP statuses."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth / request ---
def missing_context(msg="Missing or invalid user context headers"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_time_window(msg="Window end is not strictly after start"):
    return ApiError("ERR_INVALID_TIME_WINDOW", 400, msg)


def unauthorized_role(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def forbidden(msg="Resource is outside the caller's ownership scope"):
    return ApiError("ERR_FORBIDDEN_RESOURCE", 403, msg)


def segregation(msg="Adjudicator must differ from the case filer"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


# --- existence (404) ---
def salon_not_found(msg="SalonAccount not found"):
    return ApiError("ERR_SALON_ACCOUNT_NOT_FOUND", 404, msg)


def license_not_found(msg="ProfessionalLicense not found"):
    return ApiError("ERR_LICENSE_NOT_FOUND", 404, msg)


def brand_not_found(msg="Brand not found"):
    return ApiError("ERR_BRAND_NOT_FOUND", 404, msg)


def product_not_found(msg="Product not found"):
    return ApiError("ERR_PRODUCT_NOT_FOUND", 404, msg)


def consultant_not_found(msg="SalesConsultant not found"):
    return ApiError("ERR_CONSULTANT_NOT_FOUND", 404, msg)


def route_plan_not_found(msg="RoutePlan not found"):
    return ApiError("ERR_ROUTE_PLAN_NOT_FOUND", 404, msg)


def route_stop_not_found(msg="RouteStop not found"):
    return ApiError("ERR_ROUTE_STOP_NOT_FOUND", 404, msg)


def order_not_found(msg="Order not found"):
    return ApiError("ERR_ORDER_NOT_FOUND", 404, msg)


def order_item_not_found(msg="OrderItem not found"):
    return ApiError("ERR_ORDER_ITEM_NOT_FOUND", 404, msg)


def shipment_not_found(msg="Shipment not found"):
    return ApiError("ERR_SHIPMENT_NOT_FOUND", 404, msg)


def promotion_not_found(msg="Promotion not found"):
    return ApiError("ERR_PROMOTION_NOT_FOUND", 404, msg)


def redemption_not_found(msg="PromotionRedemption not found"):
    return ApiError("ERR_REDEMPTION_NOT_FOUND", 404, msg)


def diversion_case_not_found(msg="DiversionCase not found"):
    return ApiError("ERR_DIVERSION_CASE_NOT_FOUND", 404, msg)


# --- state (409) ---
def invalid_account_state(msg="Salon transition attempted from a non-matching status"):
    return ApiError("ERR_INVALID_ACCOUNT_STATE", 409, msg)


def account_not_active(msg="SalonAccount is not ACTIVE"):
    return ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, msg)


def no_valid_license(msg="Salon has no VERIFIED license valid after the logical clock"):
    return ApiError("ERR_NO_VALID_LICENSE", 409, msg)


def invalid_license_state(msg="License is not SUBMITTED"):
    return ApiError("ERR_INVALID_LICENSE_STATE", 409, msg)


def license_date_invalid(msg="License valid_until is not after the logical clock"):
    return ApiError("ERR_LICENSE_DATE_INVALID", 400, msg)


def invalid_product_state(msg="Product lifecycle forbids the operation"):
    return ApiError("ERR_INVALID_PRODUCT_STATE", 409, msg)


def invalid_order_state(msg="Order transition attempted from a non-matching status"):
    return ApiError("ERR_INVALID_ORDER_STATE", 409, msg)


def invalid_shipment_state(msg="Shipment transition attempted from a non-matching status"):
    return ApiError("ERR_INVALID_SHIPMENT_STATE", 409, msg)


def invalid_promotion_state(msg="Promotion transition attempted from a non-matching status"):
    return ApiError("ERR_INVALID_PROMOTION_STATE", 409, msg)


def invalid_diversion_case_state(msg="Diversion case transition attempted from a non-matching status"):
    return ApiError("ERR_INVALID_DIVERSION_CASE_STATE", 409, msg)


def invalid_route_plan_state(msg="Route plan transition attempted from a non-matching status"):
    return ApiError("ERR_INVALID_ROUTE_PLAN_STATE", 409, msg)


def invalid_route_stop_state(msg="Route stop transition attempted from a non-matching status"):
    return ApiError("ERR_INVALID_ROUTE_STOP_STATE", 409, msg)


def invalid_consultant_state(msg="Consultant is not ACTIVE"):
    return ApiError("ERR_INVALID_CONSULTANT_STATE", 409, msg)


# --- business ---
def hazmat_air_forbidden(msg="Hazmat items require GROUND shipping"):
    return ApiError("ERR_HAZMAT_AIR_FORBIDDEN", 422, msg)


def shipment_held_diversion(msg="Shipment blocked by an open diversion hold"):
    return ApiError("ERR_SHIPMENT_HELD_DIVERSION", 409, msg)


def shipment_quantity_exceeds(msg="Shipment quantities exceed remaining unshipped units"):
    return ApiError("ERR_SHIPMENT_QUANTITY_EXCEEDS_ORDER", 409, msg)


def brand_territory_restricted(msg="Brand exclusivity does not cover the salon territory"):
    return ApiError("ERR_BRAND_TERRITORY_RESTRICTED", 422, msg)


def backbar_quota_exceeded(msg="Projected backbar units exceed 2.0x projected retail units"):
    return ApiError("ERR_BACKBAR_QUOTA_EXCEEDED", 422, msg)


def duplicate_code(msg="Name/SKU/code already in use"):
    return ApiError("ERR_DUPLICATE_CODE", 409, msg)


def territory_window_overlap(msg="Exclusivity window overlaps an existing window"):
    return ApiError("ERR_TERRITORY_WINDOW_OVERLAP", 409, msg)


def route_stop_buffer_violation(msg="Stops must keep a >= 30 minute gap"):
    return ApiError("ERR_ROUTE_STOP_BUFFER_VIOLATION", 409, msg)


def consultant_territory_mismatch(msg="Stop salon territory not covered by the consultant"):
    return ApiError("ERR_CONSULTANT_TERRITORY_MISMATCH", 422, msg)


def promotion_not_active(msg="Logical clock is outside the promotion window"):
    return ApiError("ERR_PROMOTION_NOT_ACTIVE", 409, msg)


def promotion_tier_ineligible(msg="Salon tier is not eligible for this promotion"):
    return ApiError("ERR_PROMOTION_TIER_INELIGIBLE", 422, msg)


def promotion_already_applied(msg="Promotion already applied to this order"):
    return ApiError("ERR_PROMOTION_ALREADY_APPLIED", 409, msg)


def bundle_requirement_not_met(msg="Order lacks the required qualifying units"):
    return ApiError("ERR_BUNDLE_REQUIREMENT_NOT_MET", 422, msg)


def insufficient_credit_balance(msg="Requested points exceed redeemable balance"):
    return ApiError("ERR_INSUFFICIENT_CREDIT_BALANCE", 422, msg)


def credit_redemption_exceeds_cap(msg="Requested credit exceeds 50% of merchandise total"):
    return ApiError("ERR_CREDIT_REDEMPTION_EXCEEDS_CAP", 422, msg)


def promotion_budget_exhausted(msg="Promotion remaining budget is insufficient"):
    return ApiError("ERR_PROMOTION_BUDGET_EXHAUSTED", 422, msg)


def per_salon_cap_exceeded(msg="Redemption would exceed the per-salon cap"):
    return ApiError("ERR_PER_SALON_CAP_EXCEEDED", 422, msg)


# --- concurrency ---
def stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
