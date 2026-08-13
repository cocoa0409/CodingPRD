"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_HAZARD_CRITICAL_BLOCK = "ERR_HAZARD_CRITICAL_BLOCK"  # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_SENIOR_REQUIRED = "ERR_SENIOR_REQUIRED"          # 403
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"            # 422
ERR_CLOSURE_CONFLICT = "ERR_CLOSURE_CONFLICT"        # 409
ERR_CLOSURE_DURATION_EXCEEDED = "ERR_CLOSURE_DURATION_EXCEEDED"  # 422
ERR_TAKE_PERMIT_REQUIRED = "ERR_TAKE_PERMIT_REQUIRED"  # 422
ERR_FEDERAL_PERMIT_REQUIRED = "ERR_FEDERAL_PERMIT_REQUIRED"  # 422
ERR_PERMIT_OUTSIDE_WINDOW = "ERR_PERMIT_OUTSIDE_WINDOW"  # 422
ERR_TAKE_BUDGET_EXCEEDED = "ERR_TAKE_BUDGET_EXCEEDED"  # 422
ERR_PLAN_DUPLICATE_YEAR = "ERR_PLAN_DUPLICATE_YEAR"  # 409
ERR_ID_METHOD_PENDING = "ERR_ID_METHOD_PENDING"      # 422
ERR_MITIGATION_REQUIRED = "ERR_MITIGATION_REQUIRED"  # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_ENUM = "ERR_INVALID_ENUM"                # 400
ERR_CROSS_FACILITY_FORBIDDEN = "ERR_CROSS_FACILITY_FORBIDDEN"  # 403


def err(error_id, message, http_status):
    return ApiError(error_id, message, http_status)


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, f"{what} not found", 404)


def fk_not_found(field):
    return ApiError(ERR_FK_NOT_FOUND, f"foreign key '{field}' references a non-existent record", 422)


def invalid_request(msg):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_enum(field, value):
    return ApiError(ERR_INVALID_ENUM, f"invalid value for enum field '{field}': {value!r}", 400)


def invalid_state(msg):
    return ApiError(ERR_INVALID_STATE, msg, 409)
