"""Error catalogue: error_id -> HTTP status, exactly as declared by the spec."""

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_REBUILDER_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_DAMAGE_REPORT_NOT_FOUND": 404,
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_PARTS_DOCUMENT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_RECOGNITION_REQUEST_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    # well-formedness / uniqueness
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_NATURAL_KEY": 409,
    # optimistic concurrency
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_TITLE_VERSION": 412,
    # state machine admissibility
    "ERR_APPLICATION_NOT_DRAFT": 409,
    "ERR_INVALID_APPLICATION_STATE": 409,
    "ERR_INSPECTION_NOT_SCHEDULED": 409,
    "ERR_INSPECTION_NOT_IN_PROGRESS": 409,
    "ERR_PARTS_DOCUMENT_STATE_INVALID": 409,
    "ERR_TITLE_NOT_ACTIVE": 409,
    "ERR_APPEAL_STATE_INVALID": 409,
    "ERR_REFERRAL_STATE_INVALID": 409,
    "ERR_LICENSE_ACTION_INVALID": 409,
    "ERR_RECOGNITION_ALREADY_DECIDED": 409,
    # business safety
    "ERR_VEHICLE_FRAUD_HOLD": 409,
    "ERR_NON_REPAIRABLE_BRAND": 409,
    "ERR_STOLEN_COMPONENT_UNRESOLVED": 409,
    # referential integrity
    "ERR_REBUILDER_LICENSE_INACTIVE": 403,
    "ERR_INSPECTOR_CREDENTIAL_EXPIRED": 409,
    "ERR_SALVAGE_TITLE_REQUIRED": 409,
    "ERR_DONOR_TITLE_NOT_TRACEABLE": 422,
    "ERR_STATION_NOT_FLOOD_CAPABLE": 409,
    # quantitative constraints
    "ERR_DUPLICATE_ACTIVE_APPLICATION": 409,
    "ERR_DOCUMENTATION_INCOMPLETE": 422,
    "ERR_PHOTO_SET_INCOMPLETE": 422,
    "ERR_ATTEMPT_LIMIT_EXCEEDED": 409,
    "ERR_APPEAL_PENDING_BLOCKS_SCHEDULING": 409,
    "ERR_INSPECTOR_INTERVAL_CONFLICT": 409,
    "ERR_STATION_CAPACITY_EXCEEDED": 409,
    # temporal
    "ERR_SUBMISSION_WINDOW_EXPIRED": 422,
    "ERR_INSPECTION_SLOT_IN_PAST": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_TRANSFER_PREDATES_TITLE": 422,
    # identity / brand
    "ERR_VIN_MISMATCH": 422,
    "ERR_BRAND_ESCALATION_FORBIDDEN": 422,
    # fiscal
    "ERR_INSUFFICIENT_FEE_BALANCE": 402,
    "ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_ROLE_NOT_PERMITTED": "The caller role is not permitted to perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the targeted resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this action.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_DUPLICATE_NATURAL_KEY": "A row with this natural key already exists.",
}


class ApiError(Exception):
    """Raised anywhere in a handler to abort with a catalogued error."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
