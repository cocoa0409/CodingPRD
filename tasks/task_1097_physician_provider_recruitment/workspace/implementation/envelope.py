"""Response envelope + error type. Field names taken verbatim from the
scaffold response_envelope / PRD 2.2."""
from flask import jsonify

from store import S, gen_request_id

# Error IDs + HTTP status (scaffold 1.6 / PRD 5)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_INTERVIEWER_INVALID = ("ERR_INTERVIEWER_INVALID", 422)
ERR_SPECIALTY_MISMATCH = ("ERR_SPECIALTY_MISMATCH", 422)
ERR_INTERVIEWER_DOUBLE_BOOKED = ("ERR_INTERVIEWER_DOUBLE_BOOKED", 409)
ERR_CANDIDATE_TRAVEL_CONFLICT = ("ERR_CANDIDATE_TRAVEL_CONFLICT", 409)
ERR_OPENING_NOT_OPEN = ("ERR_OPENING_NOT_OPEN", 409)
ERR_COMP_OUT_OF_RANGE = ("ERR_COMP_OUT_OF_RANGE", 422)
ERR_NO_COMPLETED_SITE_VISIT = ("ERR_NO_COMPLETED_SITE_VISIT", 409)
ERR_CREDENTIALING_NOT_CLEARED = ("ERR_CREDENTIALING_NOT_CLEARED", 409)
ERR_GUARANTEE_WINDOW_EXPIRED = ("ERR_GUARANTEE_WINDOW_EXPIRED", 422)
ERR_NO_ELIGIBLE_RECRUITER = ("ERR_NO_ELIGIBLE_RECRUITER", 409)
ERR_OPENING_FILLED = ("ERR_OPENING_FILLED", 409)
ERR_FINAL_COMP_REQUIRED = ("ERR_FINAL_COMP_REQUIRED", 422)


class ApiError(Exception):
    def __init__(self, err, message=None):
        self.error_id = err[0]
        self.http_status = err[1]
        self.message = message or err[0]
        super().__init__(self.message)


def _meta(extra=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": S.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(err_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err_id, "message": message},
    }
    return body
