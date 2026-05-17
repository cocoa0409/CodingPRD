"""Error catalog and Flask error handlers."""
from flask import Flask, jsonify

from app.responses import error_envelope


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience constructors for the catalog
def err_unauthenticated(msg: str = "Missing X-User-Role or X-User-ID header.") -> ApiError:
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg: str = "Role is not authorized for this endpoint.") -> ApiError:
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg: str = "Resource not found.") -> ApiError:
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg: str = "Resource not in a state that permits this transition.") -> ApiError:
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_version_conflict(msg: str = "Version mismatch.") -> ApiError:
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


def err_no_valid_license(msg: str = "Physician has no ACTIVE state license for the patient's present state.") -> ApiError:
    return ApiError("ERR_NO_VALID_LICENSE", 422, msg)


def err_dea_requirements(msg: str = "DEA number or EPCS token missing for controlled-substance issuance.") -> ApiError:
    return ApiError("ERR_DEA_REQUIREMENTS_NOT_MET", 422, msg)


def err_schedule_ii_refills(msg: str = "Schedule II prescriptions cannot have refills > 0.") -> ApiError:
    return ApiError("ERR_SCHEDULE_II_REFILLS_FORBIDDEN", 422, msg)


def err_compliance_score_low(msg: str = "Compliance score is below 80.") -> ApiError:
    return ApiError("ERR_COMPLIANCE_SCORE_TOO_LOW", 422, msg)


def err_physician_mismatch(msg: str = "prescribing_physician_id must equal Consult.physician_id.") -> ApiError:
    return ApiError("ERR_PHYSICIAN_MISMATCH", 422, msg)


def err_insurance_not_enrolled(msg: str = "Patient lacks insurance_payer_id or insurance_member_id.") -> ApiError:
    return ApiError("ERR_INSURANCE_NOT_ENROLLED", 422, msg)


def err_rx_field_out_of_range(msg: str = "days_supply or refills is out of allowed range.") -> ApiError:
    return ApiError("ERR_RX_FIELD_OUT_OF_RANGE", 422, msg)


def err_followup_window_empty(msg: str = "Computed FollowUp due_by is not strictly later than now.") -> ApiError:
    return ApiError("ERR_FOLLOWUP_WINDOW_EMPTY", 422, msg)


def err_billing_not_terminal(msg: str = "Billing or follow-up is not in a terminal status.") -> ApiError:
    return ApiError("ERR_BILLING_NOT_TERMINAL", 409, msg)


def err_claim_already_exists(msg: str = "An InsuranceClaim already exists for this Consult.") -> ApiError:
    return ApiError("ERR_CLAIM_ALREADY_EXISTS", 409, msg)


def err_patient_has_active_consult(msg: str = "Patient already has a non-terminal Consult.") -> ApiError:
    return ApiError("ERR_PATIENT_HAS_ACTIVE_CONSULT", 409, msg)


def err_license_period_overlap(msg: str = "New license interval overlaps an existing one for the same (physician, state).") -> ApiError:
    return ApiError("ERR_LICENSE_PERIOD_OVERLAP", 409, msg)


def err_pagination_invalid(msg: str = "Pagination parameters out of bounds.") -> ApiError:
    return ApiError("ERR_PAGINATION_INVALID", 400, msg)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed for this path.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(exc):
        # Bad JSON or malformed body — surface as a generic 400 for upstream tests.
        body = error_envelope("ERR_PAGINATION_INVALID", str(exc))
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_other(exc):
        # Fall back: treat unknown exceptions as 500. Tests should not trigger
        # this path, but having it avoids HTML traceback responses.
        body = error_envelope("ERR_INTERNAL", str(exc))
        return jsonify(body), 500
