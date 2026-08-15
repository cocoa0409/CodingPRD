"""Error catalog — error IDs and HTTP statuses from SCAFFOLD section 1.6 / PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_missing_user_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID or X-User-Role header missing or malformed")


def err_insufficient_permissions():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role not permitted for this operation")


def err_invalid_request(msg="Malformed body, invalid enum value, or missing required field"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_not_found(resource_error_id, message):
    return ApiError(resource_error_id, 404, message)


def err_invalid_state(msg="Entity in a state that does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


NOT_FOUND_IDS = {
    "vessel": "ERR_VESSEL_NOT_FOUND",
    "dock": "ERR_DOCK_NOT_FOUND",
    "menu_tier": "ERR_MENU_TIER_NOT_FOUND",
    "cruise": "ERR_CRUISE_NOT_FOUND",
    "booking": "ERR_BOOKING_NOT_FOUND",
    "passenger": "ERR_PASSENGER_NOT_FOUND",
    "manifest": "ERR_MANIFEST_NOT_FOUND",
    "provision_order": "ERR_PROVISION_ORDER_NOT_FOUND",
    "staff_member": "ERR_STAFF_MEMBER_NOT_FOUND",
    "assignment": "ERR_ASSIGNMENT_NOT_FOUND",
    "customer": "ERR_CUSTOMER_NOT_FOUND",
    "credit": "ERR_CREDIT_NOT_FOUND",
    "inquiry": "ERR_INQUIRY_NOT_FOUND",
    "weather_event": "ERR_WEATHER_EVENT_NOT_FOUND",
    "dock_slot": "ERR_DOCK_SLOT_NOT_FOUND",
    "parking_pass": "ERR_PARKING_PASS_NOT_FOUND",
}
