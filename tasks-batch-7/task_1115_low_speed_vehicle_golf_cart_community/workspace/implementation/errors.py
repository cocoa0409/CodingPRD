"""Error catalog — IDs and HTTP statuses read from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_validation(msg="Malformed request"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="State machine rejects the transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Expected version does not match stored version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_underage(msg="Driver age below community minimum"):
    return ApiError("ERR_UNDERAGE_DRIVER", 422, msg)


def err_license(msg="Driver license class is NONE"):
    return ApiError("ERR_LICENSE_CLASS_INSUFFICIENT", 422, msg)


def err_equipment(msg="Vehicle lacks required safety equipment for its class"):
    return ApiError("ERR_EQUIPMENT_MINIMUM", 422, msg)


def err_duplicate_registration(msg="A non-terminal registration already exists for this vehicle and year"):
    return ApiError("ERR_DUPLICATE_REGISTRATION", 409, msg)


def err_inspection_not_passed(msg="No latest finalized inspection in PASSED status"):
    return ApiError("ERR_INSPECTION_NOT_PASSED", 422, msg)


def err_insurance_missing(msg="No ACTIVE insurance policy covers the vehicle"):
    return ApiError("ERR_INSURANCE_MISSING", 422, msg)


def err_coverage_low(msg="Liability coverage below community minimum"):
    return ApiError("ERR_INSURANCE_COVERAGE_LOW", 422, msg)


def err_holder_not_eligible(msg="Permit holder is not ELIGIBLE"):
    return ApiError("ERR_HOLDER_NOT_ELIGIBLE", 422, msg)


def err_holder_barred(msg="Permit holder compliance_status is BARRED"):
    return ApiError("ERR_HOLDER_BARRED", 422, msg)


def err_route_not_designated(msg="Route is not DESIGNATED"):
    return ApiError("ERR_ROUTE_NOT_DESIGNATED", 422, msg)


def err_route_vehicle_class(msg="GOLF_CART_ONLY route booked by an LSV registration"):
    return ApiError("ERR_ROUTE_VEHICLE_CLASS", 422, msg)


def err_route_pass_overlap(msg="Pass window overlaps another ACTIVE pass on this registration"):
    return ApiError("ERR_ROUTE_PASS_OVERLAP", 409, msg)


def err_charging_overlap(msg="Reservation collides with another BOOKED reservation on this station and slot"):
    return ApiError("ERR_CHARGING_OVERLAP", 409, msg)


def err_dispatch_overlap(msg="Shift window collides with another non-terminal dispatch on this vehicle"):
    return ApiError("ERR_DISPATCH_WINDOW_OVERLAP", 409, msg)


def err_station_offline(msg="Charging station is OFFLINE"):
    return ApiError("ERR_STATION_OFFLINE", 409, msg)


def err_insufficient_funds(msg="Wallet balance below the amount to be debited"):
    return ApiError("ERR_INSUFFICIENT_FUNDS", 402, msg)


def err_renewal_window(msg="Renew attempted outside renewal window and late grace period"):
    return ApiError("ERR_RENEWAL_WINDOW_CLOSED", 422, msg)


def err_fleet_unavailable(msg="Fleet vehicle is not AVAILABLE"):
    return ApiError("ERR_FLEET_UNAVAILABLE", 409, msg)
