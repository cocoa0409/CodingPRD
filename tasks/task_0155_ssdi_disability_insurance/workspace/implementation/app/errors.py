"""Domain exception class carrying error_id, HTTP status, and message.

The error catalog is defined in SCAFFOLD.yaml §1.6 and PRD §5.
"""

from __future__ import annotations


class APIError(Exception):
    """Raised by services/routes to signal a structured failure."""

    def __init__(self, error_id: str, http_status: int, message: str = "") -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience constructors per the scaffold error catalog.

def auth_required(message: str = "Missing X-User-ID or X-User-Role header") -> APIError:
    return APIError("ERR_AUTH_REQUIRED", 401, message)


def invalid_role(message: str = "X-User-Role is not a recognized role") -> APIError:
    return APIError("ERR_INVALID_ROLE", 401, message)


def forbidden(message: str = "Role not permitted for this endpoint") -> APIError:
    return APIError("ERR_FORBIDDEN", 403, message)


def segregation_of_duties(message: str = "Reconsideration examiner equals the initial-review examiner") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", 403, message)


def claimant_not_found(message: str = "Claimant not found") -> APIError:
    return APIError("ERR_CLAIMANT_NOT_FOUND", 404, message)


def application_not_found(message: str = "Application not found") -> APIError:
    return APIError("ERR_APPLICATION_NOT_FOUND", 404, message)


def resource_not_found(message: str = "Referenced resource not found") -> APIError:
    return APIError("ERR_RESOURCE_NOT_FOUND", 404, message)


def invalid_state(message: str = "Resource not in a valid state for this transition") -> APIError:
    return APIError("ERR_INVALID_STATE", 409, message)


def version_mismatch(message: str = "Optimistic concurrency check failed") -> APIError:
    return APIError("ERR_VERSION_MISMATCH", 409, message)


def hearing_slot_conflict(message: str = "Hearing slot conflicts with another booked/held slot") -> APIError:
    return APIError("ERR_HEARING_SLOT_CONFLICT", 409, message)


def application_already_scheduled(message: str = "Application already scheduled on another slot") -> APIError:
    return APIError("ERR_APPLICATION_ALREADY_SCHEDULED", 409, message)


def appeal_window_expired(message: str = "Appeal window has expired") -> APIError:
    return APIError("ERR_APPEAL_WINDOW_EXPIRED", 409, message)


def hearing_not_reached(message: str = "Hearing slot start time not reached, or already passed") -> APIError:
    return APIError("ERR_HEARING_NOT_REACHED", 422, message)


def hearing_not_held(message: str = "No HELD hearing slot for this application") -> APIError:
    return APIError("ERR_HEARING_NOT_HELD", 422, message)


def qc_insufficient(message: str = "Quarter-of-Coverage requirement not met") -> APIError:
    return APIError("ERR_QC_INSUFFICIENT", 422, message)


def evidence_insufficient(message: str = "No accepted medical evidence on file") -> APIError:
    return APIError("ERR_EVIDENCE_INSUFFICIENT", 422, message)


def aod_after_filing(message: str = "alleged_onset_date is after filing_date") -> APIError:
    return APIError("ERR_AOD_AFTER_FILING", 422, message)


def child_ineligible(message: str = "Child auxiliary eligibility rules failed") -> APIError:
    return APIError("ERR_CHILD_INELIGIBLE", 422, message)


def ssi_resources_exceeded(message: str = "countable_resources_cents exceeds SSI resource limit") -> APIError:
    return APIError("ERR_SSI_RESOURCES_EXCEEDED", 422, message)


def cdr_not_due(message: str = "CDR cannot be scheduled this early") -> APIError:
    return APIError("ERR_CDR_NOT_DUE", 422, message)


def invalid_pagination(message: str = "Invalid pagination parameter") -> APIError:
    return APIError("ERR_INVALID_PAGINATION", 422, message)


def bad_request(message: str = "Malformed request body") -> APIError:
    return APIError("ERR_BAD_REQUEST", 400, message)
