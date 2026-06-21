"""Error catalogue and the ApiError exception class.

Every error_id / http_status pair is taken verbatim from PRD §5 and
SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Authentication / authorization
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403

# Existence / referential integrity
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"  # 404

# Request well-formedness
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422

# State legality
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409

# Business safety / constraint
ERR_ORDER_EMPTY = "ERR_ORDER_EMPTY"                  # 409
ERR_FILE_NOT_PRINTABLE = "ERR_FILE_NOT_PRINTABLE"    # 409
ERR_MATERIAL_RETIRED = "ERR_MATERIAL_RETIRED"        # 409
ERR_PROCESS_MISMATCH = "ERR_PROCESS_MISMATCH"        # 409
ERR_MACHINE_OFFLINE = "ERR_MACHINE_OFFLINE"          # 409
ERR_MACHINE_BUSY = "ERR_MACHINE_BUSY"                # 409
ERR_MACHINE_SLOT_CONFLICT = "ERR_MACHINE_SLOT_CONFLICT"            # 409
ERR_MACHINE_CAPACITY_EXCEEDED = "ERR_MACHINE_CAPACITY_EXCEEDED"    # 409
ERR_STATION_SLOT_CONFLICT = "ERR_STATION_SLOT_CONFLICT"            # 409
ERR_SPOOL_INSUFFICIENT = "ERR_SPOOL_INSUFFICIENT"    # 409
ERR_ORDER_NOT_ESCROWED = "ERR_ORDER_NOT_ESCROWED"    # 409
ERR_ORDER_NOT_READY = "ERR_ORDER_NOT_READY"          # 409
ERR_NO_SHIPMENT = "ERR_NO_SHIPMENT"                  # 409
ERR_PRODUCTION_STARTED = "ERR_PRODUCTION_STARTED"    # 409

# Fiscal
ERR_INSUFFICIENT_WALLET = "ERR_INSUFFICIENT_WALLET"  # 402

# Optimistic concurrency
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412


def unauthenticated(msg="Missing X-User-ID or X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="Referenced resource not found within bureau"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg)


def insufficient_wallet(msg="Wallet balance is insufficient"):
    return ApiError(ERR_INSUFFICIENT_WALLET, 402, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
