"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.programs import bp as programs_bp
from routes.employees import bp as employees_bp
from routes.lots import bp as lots_bp
from routes.permits import bp as permits_bp
from routes.routes_trips import bp as routes_trips_bp
from routes.notices import bp as notices_bp
from routes.violations import bp as violations_bp
from routes.tow_events import bp as tow_events_bp
from routes.billing import bp as billing_bp
from routes.peak_windows import bp as peak_windows_bp

for bp in (programs_bp, employees_bp, lots_bp, permits_bp, routes_trips_bp,
           notices_bp, violations_bp, tow_events_bp, billing_bp, peak_windows_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", str(err), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
