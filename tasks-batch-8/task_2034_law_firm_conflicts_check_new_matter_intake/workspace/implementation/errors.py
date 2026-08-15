"""Error classes and error-ID constants (scaffold 1.6 / PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"              # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                          # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                          # 404
ERR_WALL_EXCLUDED = "ERR_WALL_EXCLUDED"                  # 403
ERR_NOT_RESPONSIBLE_ATTORNEY = "ERR_NOT_RESPONSIBLE_ATTORNEY"  # 403
ERR_SOD_SELF_APPROVAL = "ERR_SOD_SELF_APPROVAL"          # 403
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"              # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                  # 412
ERR_MATTER_NOT_INTAKE = "ERR_MATTER_NOT_INTAKE"          # 409
ERR_MATTER_NOT_OPEN = "ERR_MATTER_NOT_OPEN"              # 409
ERR_MATTER_TERMINAL = "ERR_MATTER_TERMINAL"              # 409
ERR_CHECK_SUPERSEDED = "ERR_CHECK_SUPERSEDED"            # 409
ERR_HIT_NOT_PENDING = "ERR_HIT_NOT_PENDING"              # 409
ERR_HIT_NOT_CONFIRMED = "ERR_HIT_NOT_CONFIRMED"          # 422
ERR_WAIVER_INVALID_STATE = "ERR_WAIVER_INVALID_STATE"    # 409
ERR_WAIVER_ACTIVE_EXISTS = "ERR_WAIVER_ACTIVE_EXISTS"    # 409
ERR_LETTER_INVALID_STATE = "ERR_LETTER_INVALID_STATE"    # 409
ERR_LETTER_STALE = "ERR_LETTER_STALE"                    # 422
ERR_MATTER_CLEARANCE_BLOCKED = "ERR_MATTER_CLEARANCE_BLOCKED"  # 422
ERR_CREDIT_MISSING = "ERR_CREDIT_MISSING"                # 422
ERR_CREDIT_STALE = "ERR_CREDIT_STALE"                    # 422
ERR_RETAINER_UNFUNDED = "ERR_RETAINER_UNFUNDED"          # 422
ERR_REFUND_EXCEEDS_BALANCE = "ERR_REFUND_EXCEEDS_BALANCE"  # 422
ERR_WALL_INVALID_STATE = "ERR_WALL_INVALID_STATE"        # 409
ERR_ATTORNEY_ALREADY_EXCLUDED = "ERR_ATTORNEY_ALREADY_EXCLUDED"  # 409
ERR_ATTORNEY_NOT_EXCLUDED = "ERR_ATTORNEY_NOT_EXCLUDED"  # 409
ERR_ATTORNEY_ADVERSE_OVERLAP = "ERR_ATTORNEY_ADVERSE_OVERLAP"  # 422
ERR_ATTORNEY_NOT_ACTIVE = "ERR_ATTORNEY_NOT_ACTIVE"      # 422
ERR_PARTY_ALREADY_ON_MATTER = "ERR_PARTY_ALREADY_ON_MATTER"  # 409


def unauthenticated(msg="X-User-ID and X-User-Role headers are required"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role is not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid(msg="Malformed request payload"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
