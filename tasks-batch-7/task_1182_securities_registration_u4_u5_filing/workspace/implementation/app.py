"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__, static_folder=None)

from routes import clock, firms, applicants, registration_requests, jurisdictions  # noqa: E402
from routes import fingerprints, background, exams, events, amendments  # noqa: E402
from routes import terminations, comments, affiliations, renewals, inquiries  # noqa: E402

for module in (
    clock, firms, applicants, registration_requests, jurisdictions,
    fingerprints, background, exams, events, amendments,
    terminations, comments, affiliations, renewals, inquiries,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.status)


@app.errorhandler(404)
def handle_not_found(exc):
    return error_response("ERR_NOT_FOUND", "Path id or body foreign key references a non-existent entity", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_response("ERR_NOT_FOUND", "Method not allowed for this path", 405)


@app.errorhandler(500)
def handle_internal_error(exc):
    return error_response("ERR_INVALID_REQUEST", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
