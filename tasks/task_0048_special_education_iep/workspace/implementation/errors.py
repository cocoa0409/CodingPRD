"""Custom error class + error catalog (scaffold §1.6 / PRD §5).

Each catalog entry is a (error_id, http_status) tuple; raise via raise_err().
"""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# (error_id, http_status) tuples — names and codes taken verbatim from PRD §5.
ERR_UNAUTHENTICATED        = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN              = ("ERR_FORBIDDEN", 403)
ERR_SEGREGATION_OF_DUTIES  = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_NOT_FOUND             = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND          = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_REQUEST       = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_RANGE         = ("ERR_INVALID_RANGE", 422)
ERR_INVALID_STATE         = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION         = ("ERR_STALE_VERSION", 412)
ERR_CONSENT_NOT_GRANTED   = ("ERR_CONSENT_NOT_GRANTED", 409)
ERR_STUDENT_NOT_ELIGIBLE  = ("ERR_STUDENT_NOT_ELIGIBLE", 409)
ERR_IEP_NOT_ACTIVE        = ("ERR_IEP_NOT_ACTIVE", 409)
ERR_TRANSITION_AGE_NOT_MET = ("ERR_TRANSITION_AGE_NOT_MET", 409)
ERR_ACTIVE_IEP_EXISTS     = ("ERR_ACTIVE_IEP_EXISTS", 409)


def raise_err(spec, message: str = ""):
    eid, http = spec
    raise ApiError(eid, http, message or eid)
