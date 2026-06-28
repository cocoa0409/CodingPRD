"""Error catalog. Error IDs and HTTP statuses taken verbatim from PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_DUPLICATE_KEY = ("ERR_DUPLICATE_KEY", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_UNIT_VERSION = ("ERR_STALE_UNIT_VERSION", 412)
ERR_UNIT_NOT_RESERVABLE = ("ERR_UNIT_NOT_RESERVABLE", 409)
ERR_TRADEIN_NOT_OFFERED = ("ERR_TRADEIN_NOT_OFFERED", 409)
ERR_RECALL_CANNOT_DENY = ("ERR_RECALL_CANNOT_DENY", 409)
ERR_AUCTION_WINDOW = ("ERR_AUCTION_WINDOW", 409)
ERR_BID_TOO_LOW = ("ERR_BID_TOO_LOW", 409)
ERR_CURTAILMENT_SHORT = ("ERR_CURTAILMENT_SHORT", 409)
ERR_PARTS_SHORTAGE = ("ERR_PARTS_SHORTAGE", 409)
ERR_NO_MATCHING_UNIT = ("ERR_NO_MATCHING_UNIT", 409)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
