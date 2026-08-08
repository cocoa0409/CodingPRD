"""Error catalog and API exception type."""

ERR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SOD_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_GRANT_VERSION": 412,
    "ERR_QUALIFYING_TEST_MISMATCH": 422,
    "ERR_BLL_BELOW_THRESHOLD": 422,
    "ERR_CONTRACTOR_NOT_CERTIFIED": 409,
    "ERR_UNIT_UNAVAILABLE": 409,
    "ERR_CASE_NOT_ACTIVE": 409,
    "ERR_INSPECTOR_DOUBLE_BOOKED": 409,
    "ERR_RELOCATION_OVERLAP": 409,
    "ERR_CASE_NOT_RESOLVABLE": 409,
    "ERR_GRANT_INSUFFICIENT": 402,
    "ERR_CHILD_NOT_FOUND": 404,
    "ERR_DWELLING_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERR_HTTP.get(error_id, 400)
        self.message = message or error_id
