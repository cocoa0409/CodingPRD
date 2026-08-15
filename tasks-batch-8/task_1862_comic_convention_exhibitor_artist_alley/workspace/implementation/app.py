"""Comic Convention Exhibitor Management API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERRORS
from response import error_response
from routes import clock, conventions, spaces, exhibitors, applications, jury
from routes import placements, neighbors, staff, freight, issues, sales

app = Flask(__name__)

app.register_blueprint(clock.bp)
app.register_blueprint(conventions.bp)
app.register_blueprint(spaces.bp)
app.register_blueprint(exhibitors.bp)
app.register_blueprint(applications.bp)
app.register_blueprint(jury.bp)
app.register_blueprint(placements.bp)
app.register_blueprint(neighbors.bp)
app.register_blueprint(staff.bp)
app.register_blueprint(freight.bp)
app.register_blueprint(issues.bp)
app.register_blueprint(sales.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response("ERR_INVALID_REQUEST", str(exc), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
