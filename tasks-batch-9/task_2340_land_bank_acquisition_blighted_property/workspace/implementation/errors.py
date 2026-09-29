"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_APPLICATION_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # not found
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_FUNDING_SOURCE_NOT_FOUND": 404,
    "ERR_PACKET_NOT_FOUND": 404,
    "ERR_TITLE_ACTION_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_PROPERTY_VERSION": 412,
    "ERR_STALE_FUNDING_SOURCE_VERSION": 412,
    # state
    "ERR_PACKET_INVALID_STATE": 409,
    "ERR_TITLE_ACTION_ALREADY_ADJUDICATED": 409,
    "ERR_TITLE_ACTION_OPEN": 409,
    "ERR_TITLE_NOT_CLEAR": 409,
    "ERR_PROPERTY_NOT_IN_INVENTORY": 409,
    "ERR_PROPERTY_NOT_LISTED": 409,
    "ERR_ORDER_NOT_SCHEDULED": 409,
    "ERR_FUNDING_SOURCE_EXPIRED": 409,
    "ERR_RUN_NOT_PLANNED": 409,
    "ERR_APPLICATION_INVALID_STATE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    # safety exclusions
    "ERR_APPLICANT_TAX_DELINQUENT": 422,
    "ERR_APPLICANT_CODE_VIOLATOR": 422,
    "ERR_CONTRACTOR_DEBARRED": 422,
    # referential / programme pairing
    "ERR_APPLICANT_TYPE_NOT_ELIGIBLE": 422,
    "ERR_NONPROFIT_REGISTRATION_REQUIRED": 422,
    "ERR_SIDE_LOT_REQUIRES_VACANT": 422,
    "ERR_NOT_ADJACENT_OWNER": 422,
    "ERR_CONTRACTOR_SPECIALTY_MISMATCH": 422,
    # temporal
    "ERR_WINDOW_INVALID": 422,
    "ERR_CONTRACTOR_LICENSE_EXPIRED": 422,
    "ERR_HEARING_STALE": 422,
    "ERR_HEARING_SUPPORT_INSUFFICIENT": 422,
    "ERR_DEADLINE_IN_PAST": 422,
    # interval / aggregate
    "ERR_PROPERTY_WINDOW_CONFLICT": 409,
    "ERR_DEMOLITION_BUFFER_VIOLATION": 409,
    "ERR_CONTRACTOR_CAPACITY_EXCEEDED": 409,
    "ERR_SELF_ADJACENCY": 422,
    "ERR_ADJACENCY_DUPLICATE": 409,
    "ERR_PARCEL_ID_DUPLICATE": 409,
    "ERR_DEMOLITION_REQUIRES_STRUCTURE": 422,
    "ERR_OFFER_BELOW_QUOTE": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 422,
    "ERR_HOMEOWNER_LIMIT_EXCEEDED": 422,
    "ERR_MILESTONE_OVERFLOW": 422,
    "ERR_AGREEMENT_ALREADY_EXISTS": 409,
    "ERR_ABATEMENT_YEARS_EXCEED_CAP": 422,
    "ERR_EMPTY_RUN": 422,
    # fiscal
    "ERR_FUNDING_RESTRICTION_VIOLATION": 422,
    "ERR_FUNDING_CONSTRAINED": 422,
    "ERR_FUNDING_INSUFFICIENT": 422,
    "ERR_RUN_BUDGET_EXCEEDS_AVAILABLE": 422,
    # routing fallbacks (not part of the catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = status if status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    text = error_id
    if text.startswith("ERR_"):
        text = text[4:]
    return text.replace("_", " ").capitalize() + "."


def bad_request(message="The request payload is malformed or violates a field constraint."):
    return ApiError("ERR_INVALID_REQUEST", message)
