"""Aircraft Management & Owner Services API — Flask entry point.

In-memory store; boots empty on every invocation (no seeding).
"""
import os

from flask import Flask

from errors import ApiError, ERR_VALIDATION, ERR_NOT_FOUND
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.owners import bp as owners_bp
from routes.aircraft import bp as aircraft_bp
from routes.agreements import bp as agreements_bp
from routes.budgets import bp as budgets_bp
from routes.expenses import bp as expenses_bp
from routes.statements import bp as statements_bp
from routes.crew import bp as crew_bp
from routes.trips import bp as trips_bp
from routes.assignments import bp as assignments_bp
from routes.programs import bp as programs_bp
from routes.events import bp as events_bp
from routes.filings import bp as filings_bp
from routes.contracts import bp as contracts_bp
from routes.clock_routes import bp as clock_bp

for bp in (owners_bp, aircraft_bp, agreements_bp, budgets_bp, expenses_bp,
           statements_bp, crew_bp, trips_bp, assignments_bp, programs_bp,
           events_bp, filings_bp, contracts_bp, clock_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response(ERR_VALIDATION, str(err), 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
