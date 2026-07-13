"""Response envelope helpers and the ApiError exception.

Envelope shape (from SCAFFOLD §1.0 / PRD §2.2):
  success: { "meta": {api_request_id, api_request_timestamp, [pagination...]},
             "response_type": "object"|"array", "data": {} | [] }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

from store import now_iso


# Complete HTTP-status map for every error id in the catalog (SCAFFOLD §1.6).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_PUBLISHER_NOT_FOUND": 404,
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_FORMAT_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_ISBN_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_PROOF_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_PRICE_NOT_FOUND": 404,
    "ERR_SALESLINE_NOT_FOUND": 404,
    "ERR_ASSET_INVALID_STATE": 409,
    "ERR_FORMAT_INVALID_STATE": 409,
    "ERR_PROOF_INVALID_STATE": 409,
    "ERR_DISTRIBUTION_INVALID_STATE": 409,
    "ERR_STATEMENT_INVALID_STATE": 409,
    "ERR_MANUSCRIPT_NOT_VALIDATED": 409,
    "ERR_COVER_NOT_APPROVED": 409,
    "ERR_ISBN_NOT_ASSIGNED": 409,
    "ERR_ISBN_NOT_AVAILABLE": 409,
    "ERR_FORMAT_NOT_PUBLISHED": 409,
    "ERR_NO_SALES_IN_PERIOD": 409,
    "ERR_PERIOD_NOT_ENDED": 409,
    "ERR_INVALID_EFFECTIVE_WINDOW": 422,
    "ERR_PRICE_WINDOW_OVERLAP": 409,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
    "ERR_CHANNEL_FORMAT_UNSUPPORTED": 422,
    "ERR_PAGE_COUNT_TOO_LOW": 422,
    "ERR_SPINE_MISMATCH": 422,
    "ERR_PRICE_OUT_OF_BOUNDS": 422,
    "ERR_NO_VALID_PRICE": 409,
    "ERR_STALE_FORMAT_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, response_type="array", meta_extra=meta_extra)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
