"""Error classes and error ID constants from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_EXTRA_LABEL_USE = "ERR_EXTRA_LABEL_USE"          # 422
ERR_SPECIES_CLASS_MISMATCH = "ERR_SPECIES_CLASS_MISMATCH"  # 422
ERR_VCPR_NOT_VERIFIED = "ERR_VCPR_NOT_VERIFIED"      # 422
ERR_RESIDUE_CASE_OPEN = "ERR_RESIDUE_CASE_OPEN"      # 422
ERR_VFD_EXPIRED = "ERR_VFD_EXPIRED"                  # 409
ERR_VFD_NOT_USABLE = "ERR_VFD_NOT_USABLE"            # 409
ERR_VFD_DURATION_EXCEEDED = "ERR_VFD_DURATION_EXCEEDED"  # 422
ERR_VFD_QUOTA_EXCEEDED = "ERR_VFD_QUOTA_EXCEEDED"    # 409
ERR_PRODUCER_SUSPENDED = "ERR_PRODUCER_SUSPENDED"    # 409
ERR_VET_INACTIVE = "ERR_VET_INACTIVE"                # 409
ERR_ACK_MISSING = "ERR_ACK_MISSING"                  # 422
ERR_AUDIT_INCOMPLETE = "ERR_AUDIT_INCOMPLETE"        # 409
ERR_DUPLICATE_DRUG_CODE = "ERR_DUPLICATE_DRUG_CODE"  # 409
ERR_DUPLICATE_PREMISE = "ERR_DUPLICATE_PREMISE"      # 409
ERR_DUPLICATE_FDA_REG = "ERR_DUPLICATE_FDA_REG"      # 409
ERR_DUPLICATE_CLINIC_LICENSE = "ERR_DUPLICATE_CLINIC_LICENSE"  # 409


def unauthenticated(message="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, message, 401)


def unauthorized(message="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, message, 403)


def forbidden(message="Entity-backed identity mismatch"):
    return ApiError(ERR_FORBIDDEN, message, 403)


def not_found(message="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, message, 404)


def invalid_request(message="Missing required field, malformed payload, or invalid enum value"):
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def invalid_state(message="Target resource is in a state that does not permit this transition"):
    return ApiError(ERR_INVALID_STATE, message, 409)
