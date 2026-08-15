"""Error catalog: IDs and HTTP statuses from the scaffold/PRD."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"        # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_HOS_LIMIT_EXCEEDED = "ERR_HOS_LIMIT_EXCEEDED"      # 422
ERR_REST_NOT_SATISFIED = "ERR_REST_NOT_SATISFIED"      # 422
ERR_TEMPORAL_WINDOW = "ERR_TEMPORAL_WINDOW"            # 422
ERR_LEAVE_CONFLICT = "ERR_LEAVE_CONFLICT"              # 422
ERR_JOB_ALREADY_FILLED = "ERR_JOB_ALREADY_FILLED"      # 422
ERR_REFERENTIAL_MISMATCH = "ERR_REFERENTIAL_MISMATCH"  # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                        # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_PAY_INCOMPLETE = "ERR_PAY_INCOMPLETE"              # 422
ERR_CALL_POOL_EXHAUSTED = "ERR_CALL_POOL_EXHAUSTED"    # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
