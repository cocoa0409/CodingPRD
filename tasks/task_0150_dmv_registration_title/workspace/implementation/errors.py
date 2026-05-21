"""Custom ApiError class and error catalog (SCAFFOLD §1.6 / PRD §5).

Each domain error is raised as an ApiError and translated to the standard
error envelope by the global Flask error handler. The error_id strings and
HTTP status codes here match the SCAFFOLD §1.6 catalog exactly.
"""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Pre-defined error definitions keyed by error_id (SCAFFOLD §1.6 + PRD §5).
ERROR_DEFINITIONS = {
    "ERR_AUTH_REQUIRED": (401, "X-User-ID or X-User-Role header missing."),
    "ERR_INVALID_ROLE": (403, "X-User-Role is not a recognized role."),
    "ERR_ROLE_FORBIDDEN": (403, "Role is not authorized to invoke this endpoint."),
    "ERR_RESOURCE_NOT_FOUND": (404, "Path-resolved resource does not exist."),
    "ERR_VIN_ON_HOLD": (409, "Vehicle.vin_verification_status is HOLD; verification is blocked."),
    "ERR_INVALID_STATE": (409, "Resource is not in a state from which this transition is permitted."),
    "ERR_VEHICLE_SALVAGE_LOCKED": (409, "Vehicle.title_status blocks this operation."),
    "ERR_EMISSIONS_EXPIRED": (409, "Vehicle.emissions_expires_at is null or past."),
    "ERR_OWNER_REAL_ID_REVOKED": (409, "Owner.real_id_status is REVOKED."),
    "ERR_LIEN_ACTIVE": (409, "Vehicle.lien_status is ACTIVE; assessment is blocked."),
    "ERR_INSPECTION_SLOT_OVERLAP": (409, "Inspection slot overlaps an existing booking at this station."),
    "ERR_PLATE_NUMBER_TAKEN": (409, "plate_number is already in use among active plates."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same user-id ran assess-fees on this application."),
    "ERR_REVISION_LIMIT_EXCEEDED": (409, "RealIDApplication.revision_count has reached the maximum."),
    "ERR_ODOMETER_ROLLBACK": (409, "Odometer reading is lower than a prior PASSED inspection."),
    "ERR_PAYMENT_REQUIRED": (402, "TransferApplication.paid_at is null."),
    "ERR_OWNER_HAS_HOLDS": (409, "Owner.outstanding_holds_count is greater than zero."),
    "ERR_RELEASE_REFERENCE_REQUIRED": (422, "release_reference body field is missing or empty."),
    "ERR_LIEN_ALREADY_RELEASED": (409, "LienRecord.status is already RELEASED."),
    "ERR_VERSION_CONFLICT": (409, "Supplied version does not match the current resource version."),
    "ERR_VALIDATION": (422, "Request body shape, type, or numeric range invalid."),
}


def make_error(error_id: str, message: str | None = None) -> ApiError:
    """Build an ApiError for one of the cataloged errors."""
    http, default_msg = ERROR_DEFINITIONS.get(error_id, (500, "Internal error"))
    return ApiError(error_id, http, message or default_msg)
