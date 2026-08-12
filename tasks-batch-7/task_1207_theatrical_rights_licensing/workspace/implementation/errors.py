"""Error classes carrying error_id, message, http_status per the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing X-User-Role or X-User-ID header, or role undeclared"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def err_forbidden_owner(msg="X-User-ID does not match the resource's owning entity id"):
    return ApiError("ERR_FORBIDDEN_OWNER_MISMATCH", msg, 403)


def err_not_found(msg="Resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_referenced_not_found(msg="Body FK references a non-existent resource"):
    return ApiError("ERR_REFERENCED_NOT_FOUND", msg, 422)


def err_invalid_request(msg="Required field missing, type mismatch, invalid enum, or out-of-range integer"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_temporal(msg="Malformed datetime, window_start >= window_end, or due_date not in future"):
    return ApiError("ERR_INVALID_TEMPORAL", msg, 400)


def err_invalid_state(msg="Resource not in valid from-state for requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_org_suspended(msg="Organization is SUSPENDED"):
    return ApiError("ERR_ORG_SUSPENDED", msg, 409)


def err_title_withdrawn(msg="Title is WITHDRAWN"):
    return ApiError("ERR_TITLE_WITHDRAWN", msg, 409)


def err_title_unavailable(msg="Availability verdict false"):
    return ApiError("ERR_TITLE_UNAVAILABLE", msg, 409)


def err_territory_restricted(msg="Active TerritoryRestriction covers the requested window"):
    return ApiError("ERR_TERRITORY_RESTRICTED", msg, 409)


def err_exclusive_run_conflict(msg="An ACTIVE exclusive-run LicenseAgreement overlaps the requested window"):
    return ApiError("ERR_EXCLUSIVE_RUN_CONFLICT", msg, 409)


def err_alteration_prohibited(msg="Restricted-material title blocks the requested alteration_kind"):
    return ApiError("ERR_ALTERATION_PROHIBITED", msg, 409)


def err_recording_prohibited(msg="PUBLIC_FREE streaming on restricted-material title"):
    return ApiError("ERR_RECORDING_PROHIBITED", msg, 409)


def err_streaming_classification_block(msg="STREAMING_VIDEO grant requires AMATEUR classification"):
    return ApiError("ERR_STREAMING_CLASSIFICATION_BLOCK", msg, 409)


def err_rental_kind_mismatch(msg="scores_qty > 0 on a PLAY title, or scripts_qty + scores_qty == 0"):
    return ApiError("ERR_RENTAL_KIND_MISMATCH", msg, 422)


def err_performance_outside_window(msg="performance_at outside agreement window or duplicate performance_at"):
    return ApiError("ERR_PERFORMANCE_OUTSIDE_WINDOW", msg, 409)


def err_performance_already_held(msg="Cancellation refused: a HELD performance exists"):
    return ApiError("ERR_PERFORMANCE_ALREADY_HELD", msg, 409)


def err_report_too_early(msg="Performance report attempted before performance_at"):
    return ApiError("ERR_REPORT_TOO_EARLY", msg, 409)


def err_payment_amount_invalid(msg="Payment amount_cents < 1 or exceeds royalty_balance_cents"):
    return ApiError("ERR_PAYMENT_AMOUNT_INVALID", msg, 422)


def err_fine_not_waivable(msg="Waiver attempted on a non-waivable fine"):
    return ApiError("ERR_FINE_NOT_WAIVABLE", msg, 409)


def err_write_off_too_early(msg="Write-off attempted on fine younger than 180 days"):
    return ApiError("ERR_WRITE_OFF_TOO_EARLY", msg, 409)


def err_rental_not_due_lost(msg="declare_lost attempted before due_date + 30 days"):
    return ApiError("ERR_RENTAL_NOT_DUE_LOST", msg, 409)


def err_deposit_not_held(msg="Ship attempted when deposit_status != HELD"):
    return ApiError("ERR_DEPOSIT_NOT_HELD", msg, 409)


def err_amendment_on_terminal(msg="Amendment attempted on terminal agreement"):
    return ApiError("ERR_AMENDMENT_ON_TERMINAL", msg, 409)
