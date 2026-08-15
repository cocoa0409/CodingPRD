"""Error classes and the error-ID catalog (SCAFFOLD.yaml §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_MISSING_AUTH = "ERR_MISSING_AUTH"                    # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                          # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                          # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                    # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"              # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                  # 409
ERR_SITE_FROZEN = "ERR_SITE_FROZEN"                      # 409
ERR_PERMIT_EXPIRED = "ERR_PERMIT_EXPIRED"                # 409
ERR_STALE_SCIENCE = "ERR_STALE_SCIENCE"                  # 409
ERR_SCIENCE_EXPIRED = "ERR_SCIENCE_EXPIRED"              # 409
ERR_VARIANCE_REQUIRED = "ERR_VARIANCE_REQUIRED"          # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_HOLD_POINT_NOT_PASSED = "ERR_HOLD_POINT_NOT_PASSED"  # 409
ERR_MATERIALS_UNVERIFIED = "ERR_MATERIALS_UNVERIFIED"    # 409
ERR_PERMIT_NOT_ISSUED = "ERR_PERMIT_NOT_ISSUED"          # 409
ERR_REPLACEMENT_DESIGN_NOT_APPROVED = "ERR_REPLACEMENT_DESIGN_NOT_APPROVED"  # 409
ERR_INSPECTION_TOO_EARLY = "ERR_INSPECTION_TOO_EARLY"    # 409
ERR_VISIT_OUTSIDE_CONTRACT = "ERR_VISIT_OUTSIDE_CONTRACT"  # 409
ERR_SCHEDULING_CONFLICT = "ERR_SCHEDULING_CONFLICT"      # 409
ERR_INSUFFICIENT_NOTE = "ERR_INSUFFICIENT_NOTE"          # 400
ERR_MATERIAL_BUDGET_EXCEEDED = "ERR_MATERIAL_BUDGET_EXCEEDED"  # 402
ERR_FREEZE_IN_PAST = "ERR_FREEZE_IN_PAST"                # 409
ERR_INVALID_RENEWAL = "ERR_INVALID_RENEWAL"              # 400
ERR_OPEN_WORK_REMAINS = "ERR_OPEN_WORK_REMAINS"          # 409
ERR_INSTALLATION_NOT_READY = "ERR_INSTALLATION_NOT_READY"  # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                  # 412
ERR_PINNED_BY_LIVE_DESIGN = "ERR_PINNED_BY_LIVE_DESIGN"  # 409
ERR_REMEDIATION_NOT_STARTED = "ERR_REMEDIATION_NOT_STARTED"  # 409
ERR_INVALID_DECISION = "ERR_INVALID_DECISION"            # 400


def raise_err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def not_found(message="Resource not found"):
    raise ApiError(ERR_NOT_FOUND, 404, message)


def fk_not_found(message="Referenced resource does not exist in this scope"):
    raise ApiError(ERR_FK_NOT_FOUND, 422, message)


def invalid_request(message):
    raise ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message):
    raise ApiError(ERR_INVALID_STATE, 409, message)
