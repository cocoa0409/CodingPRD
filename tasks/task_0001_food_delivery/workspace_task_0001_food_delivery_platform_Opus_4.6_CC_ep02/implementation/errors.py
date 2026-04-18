from flask import jsonify
from response_envelope import make_error_response


ERROR_CODES = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_ORDER_ALREADY_ASSIGNED": 409,
    "ERR_DUPLICATE_RETURN": 409,
    "ERR_RESTAURANT_UNAVAILABLE": 422,
    "ERR_SUSPEND_CRITERIA_NOT_MET": 422,
    "ERR_RETURN_WINDOW_EXPIRED": 422,
    "ERR_REFUND_AMOUNT_INVALID": 422,
    "ERR_ORDER_INVALID": 422,
    "ERR_RELATED_RETURN_UNRESOLVED": 422,
    "ERR_VALIDATION": 422,
}


class APIError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.status_code = ERROR_CODES.get(error_id, 400)
        self.message = message or error_id
        super().__init__(self.message)


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(e):
        return make_error_response(e.error_id, e.message, e.status_code)

    @app.errorhandler(404)
    def handle_404(e):
        return make_error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return make_error_response("ERR_NOT_FOUND", "Resource not found", 404)
