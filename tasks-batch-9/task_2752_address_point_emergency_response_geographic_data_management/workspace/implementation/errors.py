"""Error catalog (§1.6 / PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


HTTP_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_AGENCY_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SELF_CONCURRENCE": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # not found
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_COVERAGE_CELL_NOT_FOUND": 404,
    "ERR_ROAD_NOT_FOUND": 404,
    "ERR_ADDRESS_POINT_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_BOUNDARY_NOT_FOUND": 404,
    "ERR_CELL_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_DEFECT_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_PROPOSAL_NOT_FOUND": 404,
    # state
    "ERR_ROAD_INVALID_STATE": 409,
    "ERR_ADDRESS_POINT_INVALID_STATE": 409,
    "ERR_REQUEST_INVALID_STATE": 409,
    "ERR_REQUEST_NOT_READY": 409,
    "ERR_BOUNDARY_INVALID_STATE": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_DEFECT_INVALID_STATE": 409,
    "ERR_PACKAGE_INVALID_STATE": 409,
    "ERR_CASE_INVALID_STATE": 409,
    # optimistic concurrency
    "ERR_STALE_ROAD_VERSION": 412,
    "ERR_STALE_BOUNDARY_VERSION": 412,
    "ERR_STALE_CASE_VERSION": 412,
    # business
    "ERR_ROAD_FROZEN_BY_DISCREPANCY": 409,
    "ERR_COVERAGE_GAP_BLOCKS_E911": 409,
    "ERR_SUBADDRESS_PARENT_INVALID": 422,
    "ERR_QC_REPORT_NOT_CERTIFIED": 409,
    "ERR_AGENCY_NOT_ACTIVE": 409,
    "ERR_COUNTERPARTY_INVALID": 422,
    "ERR_RANGE_GEOMETRY_INVALID": 422,
    "ERR_ADDRESS_PARITY_MISMATCH": 422,
    "ERR_ADDRESS_OUTSIDE_RANGE": 422,
    "ERR_DUPLICATE_ADDRESS": 409,
    "ERR_DUPLICATE_JURISDICTION_CODE": 409,
    "ERR_DUPLICATE_CELL_CODE": 409,
    "ERR_DUPLICATE_PERMIT_NUMBER": 409,
    "ERR_ROAD_RANGE_OVERLAP": 409,
    "ERR_SUBJECT_CASE_ALREADY_OPEN": 409,
    "ERR_HOUSE_NUMBER_UNAVAILABLE": 409,
    "ERR_NO_ASSIGNABLE_ADDRESS": 409,
    "ERR_QC_BLOCKING_DEFECTS_OPEN": 409,
    "ERR_PACKAGE_EMPTY": 422,
    "ERR_PACKAGE_PINS_STALE": 409,
    "ERR_QC_SCORE_BELOW_THRESHOLD": 422,
    "ERR_NO_PUBLISHED_PREDECESSOR": 409,
    "ERR_BOUNDARY_WINDOW_INVALID": 422,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_CADENCE_WINDOW_NOT_OPEN": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-ID header is absent or empty.",
    "ERR_UNAUTHORIZED": "The caller's role is not authorised for this operation.",
    "ERR_AGENCY_IDENTITY_MISMATCH": "The acting agency does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this action.",
    "ERR_SELF_CONCURRENCE": "An agency may not concur with or counter its own proposal.",
    "ERR_INVALID_REQUEST": "The request payload or query parameters are invalid.",
    "ERR_ROAD_FROZEN_BY_DISCREPANCY": "The centerline is frozen by an unresolved discrepancy case.",
}
