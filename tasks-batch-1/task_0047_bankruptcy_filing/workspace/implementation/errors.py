"""Error catalog and the ApiError exception.

Error IDs and HTTP statuses are taken verbatim from PRD section 5 (Error Code
Catalogue) and SCAFFOLD section 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id, http_status) pairs straight from PRD section 5.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_CLAIM_CREDITOR_MISMATCH = ("ERR_CLAIM_CREDITOR_MISMATCH", 409)
ERR_RELIEF_TARGET_NOT_SECURED = ("ERR_RELIEF_TARGET_NOT_SECURED", 409)
# Meeting-conflict errors: named in PRD section 3.5 prose and SCAFFOLD
# validations[priority=9,10], both HTTP 409.
ERR_TRUSTEE_DOUBLE_BOOKED = ("ERR_TRUSTEE_DOUBLE_BOOKED", 409)
ERR_ROOM_BUFFER_CONFLICT = ("ERR_ROOM_BUFFER_CONFLICT", 409)
ERR_MEANS_TEST_ABUSE = ("ERR_MEANS_TEST_ABUSE", 409)
ERR_PRIOR_DISCHARGE_BAR = ("ERR_PRIOR_DISCHARGE_BAR", 409)
ERR_STAY_TERMINATED = ("ERR_STAY_TERMINATED", 409)
ERR_EXEMPTION_EXCEEDS_ASSET = ("ERR_EXEMPTION_EXCEEDS_ASSET", 422)
ERR_NOT_CHAPTER_13 = ("ERR_NOT_CHAPTER_13", 409)
ERR_PLAN_INFEASIBLE = ("ERR_PLAN_INFEASIBLE", 409)
ERR_PLAN_OVERPAYMENT = ("ERR_PLAN_OVERPAYMENT", 422)
ERR_STALE_CASE_VERSION = ("ERR_STALE_CASE_VERSION", 412)


def err(pair, message=None):
    return ApiError(pair[0], pair[1], message)
