"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

app = Flask(__name__)

from routes.setup import bp as setup_bp
from routes.applications import bp as applications_bp
from routes.people import bp as people_bp
from routes.reports import bp as reports_bp
from routes.disputes import bp as disputes_bp
from routes.notices import bp as notices_bp

app.register_blueprint(setup_bp)
app.register_blueprint(applications_bp)
app.register_blueprint(people_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(disputes_bp)
app.register_blueprint(notices_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response(ERR_INVALID_REQUEST, f"Malformed request: {e}", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
