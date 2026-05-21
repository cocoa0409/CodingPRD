"""Error catalogue and Flask error handlers."""
from flask import jsonify

from .envelope import make_meta


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalogue — id -> (http_status, default message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Missing or malformed authentication headers"),
    "ERR_FORBIDDEN": (403, "Role not permitted for this operation"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_REFERENCE_NOT_FOUND": (422, "Referenced resource does not exist"),
    "ERR_INVALID_STATE": (409, "Operation not allowed in current state"),
    "ERR_VERSION_CONFLICT": (409, "Version mismatch"),
    "ERR_HAZMAT_HUB_NOT_CERTIFIED": (422, "Hub is not hazmat certified"),
    "ERR_DRIVER_NO_HAZMAT_ENDORSEMENT": (422, "Driver lacks hazmat endorsement"),
    "ERR_DRIVER_RELEASE_NOT_AUTHORIZED": (422, "Driver release not authorized"),
    "ERR_SIGNATURE_MISSING": (422, "Signature reference missing"),
    "ERR_OUTSIDE_TIME_WINDOW": (422, "Attempt outside parcel time window"),
    "ERR_APPOINTMENT_WINDOW_INVALID": (422, "Appointment window invalid"),
    "ERR_TIME_WINDOW_INFEASIBLE": (422, "Time window infeasible for stop"),
    "ERR_PARCEL_ALREADY_ON_ROUTE": (409, "Parcel already on a route"),
    "ERR_ROUTE_NOT_PLANNED": (409, "Route is not in PLANNED state"),
    "ERR_HUB_NOT_SERVICING_POSTAL": (422, "Hub does not service this postal area"),
    "ERR_REDELIVERY_LIMIT_EXCEEDED": (422, "Redelivery limit exceeded"),
    "ERR_CUSTOMER_REDELIVERY_CAP_REACHED": (422, "Customer redelivery cap reached"),
    "ERR_PARCEL_WEIGHT_OUT_OF_RANGE": (422, "Parcel weight out of range"),
    "ERR_DECLARED_VALUE_OUT_OF_RANGE": (422, "Declared value out of range"),
    "ERR_CLOCK_BACKWARDS": (422, "Clock cannot move backwards"),
}


def raise_error(error_id: str, message: str = None):
    http_status, default_message = ERRORS[error_id]
    raise APIError(error_id, message or default_message, http_status)


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": err.error_id,
                "message": err.message,
            },
        }
        return jsonify(body), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_NOT_FOUND",
                "message": "Resource not found",
            },
        }
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(err):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_NOT_FOUND",
                "message": "Method not allowed",
            },
        }
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(err):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_REFERENCE_NOT_FOUND",
                "message": "Bad request",
            },
        }
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        body = {
            "meta": make_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_STATE",
                "message": f"Internal error: {type(err).__name__}: {err}",
            },
        }
        return jsonify(body), 500
