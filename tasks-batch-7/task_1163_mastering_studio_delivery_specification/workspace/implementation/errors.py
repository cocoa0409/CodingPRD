"""Error catalog and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=''):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERR_UNAUTHENTICATED = 'ERR_UNAUTHENTICATED'            # 401
ERR_UNAUTHORIZED = 'ERR_UNAUTHORIZED'                  # 403
ERR_NOT_FOUND = 'ERR_NOT_FOUND'                        # 404
ERR_INVALID_REQUEST = 'ERR_INVALID_REQUEST'            # 400
ERR_INVALID_FORMAT = 'ERR_INVALID_FORMAT'              # 400
ERR_INVALID_TIME_BOUNDARY = 'ERR_INVALID_TIME_BOUNDARY'  # 400
ERR_INVALID_STATE = 'ERR_INVALID_STATE'                # 409
ERR_ALREADY_TERMINAL = 'ERR_ALREADY_TERMINAL'          # 409
ERR_STALE_VERSION = 'ERR_STALE_VERSION'                # 412
ERR_ENTITY_NOT_ACTIVE = 'ERR_ENTITY_NOT_ACTIVE'        # 422
ERR_SLOT_CONFLICT = 'ERR_SLOT_CONFLICT'                # 409
ERR_CAPACITY_EXCEEDED = 'ERR_CAPACITY_EXCEEDED'        # 422
ERR_DUPLICATE_ASSET = 'ERR_DUPLICATE_ASSET'            # 409
ERR_DUPLICATE_UPC = 'ERR_DUPLICATE_UPC'                # 409
ERR_METADATA_MISMATCH = 'ERR_METADATA_MISMATCH'        # 422
ERR_INSUFFICIENT_CREDIT = 'ERR_INSUFFICIENT_CREDIT'    # 402
ERR_SLA_BREACH = 'ERR_SLA_BREACH'                      # 422
ERR_HOLD_EXPIRED = 'ERR_HOLD_EXPIRED'                  # 410
ERR_NO_SUPERSEDING_DELIVERABLE = 'ERR_NO_SUPERSEDING_DELIVERABLE'  # 409
ERR_QC_FAILED = 'ERR_QC_FAILED'                        # 422
ERR_SOURCE_BELOW_SPEC = 'ERR_SOURCE_BELOW_SPEC'        # 422
ERR_NO_ACTIVE_ROUND = 'ERR_NO_ACTIVE_ROUND'            # 409
ERR_ENGINEER_NOT_ASSIGNED = 'ERR_ENGINEER_NOT_ASSIGNED'  # 403
ERR_CLIENT_NOT_OWNER = 'ERR_CLIENT_NOT_OWNER'          # 403


def raise_err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def not_found(msg='Referenced resource does not exist'):
    raise ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_format(msg):
    raise ApiError(ERR_INVALID_FORMAT, 400, msg)


def invalid_state(msg):
    raise ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg):
    raise ApiError(ERR_ALREADY_TERMINAL, 409, msg)
