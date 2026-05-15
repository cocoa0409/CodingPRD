"""Error catalog and Flask error handlers.

The error envelope is defined by the scaffold's `response_envelope.error`:
    {
      "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." }
    }
"""
from __future__ import annotations

from werkzeug.exceptions import HTTPException

from .response import error_envelope


class APIError(Exception):
    """Domain error carrying an `error_id`, message, and HTTP status."""

    def __init__(self, error_id: str, http_status: int, message: str = "") -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical error catalog (id -> default http status & message)
ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": (401, "Missing or unparseable authentication headers"),
    "ERR_FORBIDDEN": (403, "Role not permitted to invoke this endpoint"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_INVALID_STATE": (409, "Target entity not in a state from which this transition is permitted"),
    "ERR_VERSION_CONFLICT": (409, "Supplied version does not match stored version"),
    "ERR_ORCID_NOT_VERIFIED": (422, "Author orcid_id is not verified"),
    "ERR_DECLARATION_INCOMPLETE": (422, "One or more required declarations or files are missing"),
    "ERR_REVIEWER_CONFLICT": (422, "Reviewer conflict-of-interest score above threshold"),
    "ERR_REVIEWER_EXCLUDED_BY_AUTHOR": (422, "Reviewer is in the manuscript's excluded list"),
    "ERR_EDITOR_TOPIC_MISMATCH": (422, "Associate editor does not handle this topic_tag"),
    "ERR_INVITATION_DEADLINE_PASSED": (422, "Invitation response deadline has passed"),
    "ERR_REVISION_DEADLINE_PASSED": (422, "Revision deadline has passed"),
    "ERR_INSUFFICIENT_REVIEWS": (422, "Insufficient submitted reviews to recommend"),
    "ERR_DESK_REJECT_REASON_REQUIRED": (422, "Desk-reject requires a reason"),
    "ERR_REVIEW_INCOMPLETE": (422, "Review missing required fields"),
    "ERR_PUBLICATION_NOT_READY": (422, "Publication is not ready to be issued"),
    "ERR_COAUTHOR_LIST_INVALID": (422, "co_author_ids list is invalid"),
    "ERR_REVIEWER_LISTS_OVERLAP": (422, "suggested_reviewer_ids and excluded_reviewer_ids overlap"),
    "ERR_REVIEW_ROUND_MISMATCH": (409, "EditorDecision.revision_round does not match Manuscript.revision_round"),
    "ERR_INVITATION_ALREADY_EXISTS": (409, "Invitation already exists for this reviewer at this round"),
    "ERR_PUBLICATION_ALREADY_EXISTS": (409, "Publication already exists for this manuscript"),
    "ERR_VALIDATION": (400, "Request is malformed or missing required fields"),
    "ERR_REVIEWER_OVERLOADED": (422, "Accepting this invitation would exceed reviewer capacity"),
    "ERR_EDITOR_WINDOW_OVERLAP": (422, "Associate editor already has an open assignment window"),
}


def api_error(error_id: str, message: str | None = None) -> APIError:
    http_status, default_message = ERROR_CATALOG.get(error_id, (500, "Internal error"))
    return APIError(error_id=error_id, http_status=http_status, message=message or default_message)


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        body, status = error_envelope(err.error_id, err.message, err.http_status)
        return body, status

    @app.errorhandler(404)
    def handle_404(err):
        body, status = error_envelope("ERR_NOT_FOUND", "Resource not found", 404)
        return body, status

    @app.errorhandler(405)
    def handle_405(err):
        body, status = error_envelope("ERR_VALIDATION", "Method not allowed", 400)
        return body, status

    @app.errorhandler(400)
    def handle_400(err):
        body, status = error_envelope("ERR_VALIDATION", "Bad request", 400)
        return body, status

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        body, status = error_envelope("ERR_VALIDATION", err.description or "Bad request", err.code or 400)
        return body, status

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):  # pragma: no cover - defensive
        body, status = error_envelope("ERR_VALIDATION", f"Internal error: {err}", 500)
        return body, status
