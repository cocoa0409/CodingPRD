"""Entry point: Flask app, error handlers, route registration. No seeding at startup."""
import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import advisors, appointments, assignments, degree_plans, dropin, holds, interventions, notes, ops, referrals, students

app.register_blueprint(advisors.bp)
app.register_blueprint(students.bp)
app.register_blueprint(assignments.bp)
app.register_blueprint(appointments.bp)
app.register_blueprint(dropin.bp)
app.register_blueprint(referrals.bp)
app.register_blueprint(interventions.bp)
app.register_blueprint(holds.bp)
app.register_blueprint(degree_plans.bp)
app.register_blueprint(notes.bp)
app.register_blueprint(ops.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return error_response(errors.ERR_VALIDATION, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_response(errors.ERR_VALIDATION, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response(errors.ERR_VALIDATION, f"Internal error: {exc}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
