"""Entry point: Flask app, error handlers, blueprint registration."""

import os

from flask import Flask

import errors as errmod
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import (agreements, bookings, cases, clock, comms, crew, elections,
                    events, flights, passengers, vouchers)

app.register_blueprint(clock.bp)
app.register_blueprint(passengers.bp)
app.register_blueprint(flights.bp)
app.register_blueprint(events.bp)
app.register_blueprint(bookings.bp)
app.register_blueprint(cases.bp)
app.register_blueprint(agreements.bp)
app.register_blueprint(vouchers.bp)
app.register_blueprint(crew.bp)
app.register_blueprint(elections.bp)
app.register_blueprint(comms.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
