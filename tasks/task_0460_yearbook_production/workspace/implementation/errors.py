"""Error catalog and the ApiError exception carrying error_id + http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Foundational (ordered) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                     # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                     # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"        # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"            # 412

# --- Domain-specific business rules ---
ERR_PRESALE_NOT_OPEN = "ERR_PRESALE_NOT_OPEN"                  # 409
ERR_AD_PAGE_NOT_ADS_SECTION = "ERR_AD_PAGE_NOT_ADS_SECTION"   # 409
ERR_AD_PAGE_NOT_APPROVED = "ERR_AD_PAGE_NOT_APPROVED"         # 409
ERR_PLANT_FROZEN = "ERR_PLANT_FROZEN"                          # 409
ERR_SUBMISSIONS_INCOMPLETE = "ERR_SUBMISSIONS_INCOMPLETE"     # 409
ERR_PAGE_UNASSIGNED = "ERR_PAGE_UNASSIGNED"                    # 409
ERR_PAGE_LOCKED_FOR_SUBMISSIONS = "ERR_PAGE_LOCKED_FOR_SUBMISSIONS"  # 409
ERR_LADDER_INCOMPLETE = "ERR_LADDER_INCOMPLETE"               # 409
ERR_PAGES_NOT_ALL_APPROVED = "ERR_PAGES_NOT_ALL_APPROVED"     # 409
ERR_PAGE_NUMBER_CONFLICT = "ERR_PAGE_NUMBER_CONFLICT"         # 409
ERR_PAGE_NUMBER_OUT_OF_BOUNDS = "ERR_PAGE_NUMBER_OUT_OF_BOUNDS"  # 409
ERR_DEADLINE_IN_PAST = "ERR_DEADLINE_IN_PAST"                 # 409
ERR_ALREADY_DISTRIBUTED = "ERR_ALREADY_DISTRIBUTED"           # 409
