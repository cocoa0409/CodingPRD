"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error
from routes import (
    animals, booking_children, bookings, clock, customers, handlers, permits,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(customers.bp)
app.register_blueprint(animals.bp)
app.register_blueprint(handlers.bp)
app.register_blueprint(bookings.bp)
app.register_blueprint(booking_children.bp)
app.register_blueprint(permits.bp)
app.register_blueprint(clock.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(500)
def handle_internal(_err):
    return error("ERR_INTERNAL", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
