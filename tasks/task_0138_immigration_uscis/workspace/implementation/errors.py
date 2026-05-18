"""Custom error type and constructor helpers.

Every error_id and HTTP status comes from SCAFFOLD §1.6 — do not invent new
codes or alter statuses without verifying against the catalog.
"""
from __future__ import annotations


class ApiError(Exception):
    """Raised by any layer to signal an API-level failure with an error_id."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ── Auth / RBAC ─────────────────────────────────────────────────────────────
def err_auth_missing(msg="X-User-ID or X-User-Role header is missing or empty."):
    return ApiError("ERR_AUTH_MISSING_HEADERS", 401, msg)


def err_auth_unknown_role(msg="X-User-Role value is not a recognised role."):
    return ApiError("ERR_AUTH_UNKNOWN_ROLE", 401, msg)


def err_forbidden(msg="Caller role is not permitted to perform this operation."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


# ── Existence ───────────────────────────────────────────────────────────────
def err_not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_referenced_not_found(msg="A referenced resource in the request body could not be resolved."):
    return ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", 422, msg)


# ── Validation / shape ──────────────────────────────────────────────────────
def err_validation(msg="Request body validation failed."):
    return ApiError("ERR_VALIDATION", 422, msg)


def err_invalid_pagination(msg="Pagination parameters are out of range."):
    return ApiError("ERR_INVALID_PAGINATION", 422, msg)


# ── State / concurrency ─────────────────────────────────────────────────────
def err_invalid_state(msg="Target resource is not in a state where the requested transition is permitted."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_version_conflict(msg="Optimistic concurrency control: provided version does not match the stored version."):
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


# ── Business rules ──────────────────────────────────────────────────────────
def err_rfe_already_outstanding(msg="An OUTSTANDING RFE already exists for this case."):
    return ApiError("ERR_RFE_ALREADY_OUTSTANDING", 409, msg)


def err_biometrics_already_scheduled(msg="A SCHEDULED biometrics appointment already exists for this case."):
    return ApiError("ERR_BIOMETRICS_ALREADY_SCHEDULED", 409, msg)


def err_biometrics_too_soon(msg="scheduled_at must be at least 7 days in the future."):
    return ApiError("ERR_BIOMETRICS_TOO_SOON", 422, msg)


def err_interview_too_soon(msg="scheduled_at must be at least 14 days in the future."):
    return ApiError("ERR_INTERVIEW_TOO_SOON", 422, msg)


def err_interview_not_applicable(msg="Interviews are only permitted on I-485 cases."):
    return ApiError("ERR_INTERVIEW_NOT_APPLICABLE", 422, msg)


def err_biometrics_reschedule_limit(msg="Biometrics reschedule count would exceed the maximum (3)."):
    return ApiError("ERR_BIOMETRICS_RESCHEDULE_LIMIT", 409, msg)


def err_biometrics_reschedule_too_late(msg="Reschedule must arrive at least 24 hours before the existing appointment."):
    return ApiError("ERR_BIOMETRICS_RESCHEDULE_TOO_LATE", 422, msg)


def err_rfe_deadline_passed(msg="RFE response received after deadline_at."):
    return ApiError("ERR_RFE_DEADLINE_PASSED", 409, msg)


def err_i485_missing_approved_i130(msg="I-485 filing requires a linked_i130_case_id whose status is APPROVED (non-IR)."):
    return ApiError("ERR_I485_MISSING_APPROVED_I130", 422, msg)


def err_priority_date_not_current(msg="APPROVE requires priority_date_status == CURRENT for this case type."):
    return ApiError("ERR_PRIORITY_DATE_NOT_CURRENT", 409, msg)


def err_receipt_number_collision(msg="Receipt number collision occurred during minting."):
    return ApiError("ERR_RECEIPT_NUMBER_COLLISION", 409, msg)
