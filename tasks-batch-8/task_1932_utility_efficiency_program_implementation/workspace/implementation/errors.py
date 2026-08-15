"""Error types and error-ID constants for the API."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error IDs (from scaffold §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCED_NOT_FOUND = "ERR_REFERENCED_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_PROGRAM_VERSION = "ERR_STALE_PROGRAM_VERSION"
ERR_STALE_LEAD_VERSION = "ERR_STALE_LEAD_VERSION"
ERR_INSPECTOR_CONFLICT = "ERR_INSPECTOR_CONFLICT"
ERR_CERTIFICATION_MISSING = "ERR_CERTIFICATION_MISSING"
ERR_PROGRAM_NOT_ACTIVE = "ERR_PROGRAM_NOT_ACTIVE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_SCHEDULE_CONFLICT = "ERR_SCHEDULE_CONFLICT"
ERR_NO_ELIGIBLE_CONTRACTOR = "ERR_NO_ELIGIBLE_CONTRACTOR"
ERR_NO_INSPECTOR_AVAILABLE = "ERR_NO_INSPECTOR_AVAILABLE"
ERR_START_TOO_EARLY = "ERR_START_TOO_EARLY"
ERR_REMEDIATION_WINDOW_EXPIRED = "ERR_REMEDIATION_WINDOW_EXPIRED"
ERR_SEVERITY_TOO_LOW = "ERR_SEVERITY_TOO_LOW"
ERR_BUDGET_EXCEEDED = "ERR_BUDGET_EXCEEDED"
ERR_NOTHING_TO_RECONCILE = "ERR_NOTHING_TO_RECONCILE"
ERR_INVALID_INSPECTION_PAYLOAD = "ERR_INVALID_INSPECTION_PAYLOAD"
ERR_PROGRAM_HAS_OPEN_PROJECTS = "ERR_PROGRAM_HAS_OPEN_PROJECTS"
ERR_CONTRACTOR_BUSY = "ERR_CONTRACTOR_BUSY"


def unauthenticated(msg: str = "Missing or empty X-User-Role / X-User-ID header") -> ApiError:
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg: str = "Role not authorized for endpoint") -> ApiError:
    return ApiError(ERR_UNAUTHORIZED, msg, 403)


def not_found(msg: str = "Resource not found") -> ApiError:
    return ApiError(ERR_NOT_FOUND, msg, 404)


def referenced_not_found(msg: str = "Referenced resource does not exist") -> ApiError:
    return ApiError(ERR_REFERENCED_NOT_FOUND, msg, 404)


def invalid_state(msg: str = "Resource is not in a state allowing this transition") -> ApiError:
    return ApiError(ERR_INVALID_STATE, msg, 409)


def stale_program_version(msg: str = "expected_program_version does not match current Program.version") -> ApiError:
    return ApiError(ERR_STALE_PROGRAM_VERSION, msg, 412)


def stale_lead_version(msg: str = "expected_lead_version does not match current Lead.version") -> ApiError:
    return ApiError(ERR_STALE_LEAD_VERSION, msg, 412)


def inspector_conflict(msg: str = "Inspector is excluded from this work order's contractor") -> ApiError:
    return ApiError(ERR_INSPECTOR_CONFLICT, msg, 422)


def certification_missing(msg: str = "Contractor lacks an ACTIVE certification for the required measure_type") -> ApiError:
    return ApiError(ERR_CERTIFICATION_MISSING, msg, 422)


def program_not_active(msg: str = "Program is not ACTIVE") -> ApiError:
    return ApiError(ERR_PROGRAM_NOT_ACTIVE, msg, 422)


def not_resource_owner(msg: str = "Acting user does not own this resource") -> ApiError:
    return ApiError(ERR_NOT_RESOURCE_OWNER, msg, 403)


def schedule_conflict(msg: str = "WorkOrder overlaps another SCHEDULED/IN_PROGRESS WorkOrder for same contractor") -> ApiError:
    return ApiError(ERR_SCHEDULE_CONFLICT, msg, 422)


def no_eligible_contractor(msg: str = "No contractor satisfies the lead-distribution eligibility filter") -> ApiError:
    return ApiError(ERR_NO_ELIGIBLE_CONTRACTOR, msg, 422)


def no_inspector_available(msg: str = "No active inspector available for this work order") -> ApiError:
    return ApiError(ERR_NO_INSPECTOR_AVAILABLE, msg, 422)


def start_too_early(msg: str = "Current clock date precedes scheduled_on date") -> ApiError:
    return ApiError(ERR_START_TOO_EARLY, msg, 422)


def remediation_window_expired(msg: str = "Re-inspection requested after remediation_required_by") -> ApiError:
    return ApiError(ERR_REMEDIATION_WINDOW_EXPIRED, msg, 422)


def severity_too_low(msg: str = "Escalation requires severity HIGH or CRITICAL") -> ApiError:
    return ApiError(ERR_SEVERITY_TOO_LOW, msg, 422)


def budget_exceeded(msg: str = "Program.committed_cents + provisional incentive would exceed budget_cents") -> ApiError:
    return ApiError(ERR_BUDGET_EXCEEDED, msg, 422)


def nothing_to_reconcile(msg: str = "reconciliation_delta_cents is zero") -> ApiError:
    return ApiError(ERR_NOTHING_TO_RECONCILE, msg, 422)


def invalid_inspection_payload(msg: str = "Invalid inspection record payload") -> ApiError:
    return ApiError(ERR_INVALID_INSPECTION_PAYLOAD, msg, 400)


def program_has_open_projects(msg: str = "Program has projects in non-terminal states") -> ApiError:
    return ApiError(ERR_PROGRAM_HAS_OPEN_PROJECTS, msg, 422)


def contractor_busy(msg: str = "Contractor has SCHEDULED or IN_PROGRESS work orders") -> ApiError:
    return ApiError(ERR_CONTRACTOR_BUSY, msg, 422)
