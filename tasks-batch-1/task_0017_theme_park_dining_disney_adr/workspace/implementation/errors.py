"""Custom error class and the full error catalog (scaffold §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# (error_id, http_status) tuples. Names and codes are exactly as the scaffold
# §1.6 and PRD §5 catalog list them — do not rename.
ERR_UNAUTHENTICATED              = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN                    = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND                    = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND                 = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_STATE                = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION                = ("ERR_STALE_VERSION", 412)
ERR_GUEST_SUSPENDED              = ("ERR_GUEST_SUSPENDED", 403)
ERR_INVALID_ALLERGEN             = ("ERR_INVALID_ALLERGEN", 422)
ERR_OUTSIDE_BOOKING_WINDOW       = ("ERR_OUTSIDE_BOOKING_WINDOW", 422)
ERR_PAST_DINING_DATE             = ("ERR_PAST_DINING_DATE", 422)
ERR_SLOT_OUTSIDE_HOURS           = ("ERR_SLOT_OUTSIDE_HOURS", 422)
ERR_SLOT_MISALIGNED              = ("ERR_SLOT_MISALIGNED", 422)
ERR_SLOT_CAPACITY_EXCEEDED       = ("ERR_SLOT_CAPACITY_EXCEEDED", 409)
ERR_GUEST_DOUBLE_BOOKING         = ("ERR_GUEST_DOUBLE_BOOKING", 409)
ERR_PARK_SESSION_MISMATCH        = ("ERR_PARK_SESSION_MISMATCH", 409)
ERR_INSUFFICIENT_CREDITS         = ("ERR_INSUFFICIENT_CREDITS", 422)
ERR_PLAN_NOT_COVERING            = ("ERR_PLAN_NOT_COVERING", 409)
ERR_ADDON_ALREADY_EXISTS         = ("ERR_ADDON_ALREADY_EXISTS", 409)
ERR_PARTY_SIZE_PATCH_INFEASIBLE  = ("ERR_PARTY_SIZE_PATCH_INFEASIBLE", 422)
ERR_INVALID_REQUEST              = ("ERR_INVALID_REQUEST", 400)


def raise_err(spec, message: str = ""):
    eid, http = spec
    raise ApiError(eid, http, message or eid)
