"""Error catalog: error IDs, HTTP statuses, and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"            # 400
ERR_PERMS = "ERR_INSUFFICIENT_PERMISSIONS"                         # 403
ERR_PROPERTY_NOT_FOUND = "ERR_PROPERTY_NOT_FOUND"                  # 404
ERR_BUILDING_NOT_FOUND = "ERR_BUILDING_NOT_FOUND"                  # 404
ERR_UNIT_NOT_FOUND = "ERR_UNIT_NOT_FOUND"                          # 404
ERR_ASSET_NOT_FOUND = "ERR_ASSET_NOT_FOUND"                        # 404
ERR_TEMPLATE_NOT_FOUND = "ERR_TEMPLATE_NOT_FOUND"                  # 404
ERR_PLAN_NOT_FOUND = "ERR_PLAN_NOT_FOUND"                          # 404
ERR_BATCH_NOT_FOUND = "ERR_BATCH_NOT_FOUND"                        # 404
ERR_VISIT_NOT_FOUND = "ERR_VISIT_NOT_FOUND"                        # 404
ERR_DEFICIENCY_NOT_FOUND = "ERR_DEFICIENCY_NOT_FOUND"              # 404
ERR_WORK_ORDER_NOT_FOUND = "ERR_WORK_ORDER_NOT_FOUND"              # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                        # 400
ERR_PROPERTY_ARCHIVED = "ERR_PROPERTY_ARCHIVED"                    # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                            # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                            # 412
ERR_VISIT_TOO_EARLY = "ERR_VISIT_TOO_EARLY"                        # 409
ERR_NOTICE_LEAD_VIOLATION = "ERR_NOTICE_LEAD_VIOLATION"            # 409
ERR_WINDOW_IN_PAST = "ERR_WINDOW_IN_PAST"                          # 409
ERR_VISIT_OUTSIDE_WINDOW = "ERR_VISIT_OUTSIDE_WINDOW"              # 409
ERR_BATCH_NOT_MUTABLE = "ERR_BATCH_NOT_MUTABLE"                    # 409
ERR_EMPTY_BATCH = "ERR_EMPTY_BATCH"                                # 409
ERR_UNIT_ENTRY_OVERLAP = "ERR_UNIT_ENTRY_OVERLAP"                  # 409
ERR_COMPONENT_MISMATCH = "ERR_COMPONENT_MISMATCH"                  # 422
ERR_CROSS_PROPERTY_REFERENCE = "ERR_CROSS_PROPERTY_REFERENCE"      # 422
ERR_DEFICIENCY_ASSET_MISMATCH = "ERR_DEFICIENCY_ASSET_MISMATCH"    # 422
ERR_EVIDENCE_REQUIRED = "ERR_EVIDENCE_REQUIRED"                    # 422
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"            # 422
ERR_EMERGENCY_NOT_WAIVABLE = "ERR_EMERGENCY_NOT_WAIVABLE"          # 422
ERR_PLAN_NOT_ADOPTED = "ERR_PLAN_NOT_ADOPTED"                      # 402
ERR_BUDGET_EXCEEDED = "ERR_BUDGET_EXCEEDED"                        # 402
ERR_PLAN_HAS_OPEN_WORK = "ERR_PLAN_HAS_OPEN_WORK"                  # 409
ERR_DUPLICATE_ACTIVE_PLAN = "ERR_DUPLICATE_ACTIVE_PLAN"            # 409
ERR_ASSET_HAS_OPEN_WORK = "ERR_ASSET_HAS_OPEN_WORK"                # 409


def err(error_id, status, message):
    return ApiError(error_id, status, message)
