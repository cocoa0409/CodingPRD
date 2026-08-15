"""Natural Gas Meter Set & Service Line Installation API — Flask entrypoint.

In-memory storage only; every boot starts with an empty store and the logical
clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.json.sort_keys = False

# --- Blueprint registration ---
from routes import (  # noqa: E402
    appliance_loads,
    builders,
    ciac,
    clock,
    crews,
    gis,
    inspections,
    main_extensions,
    meter_sets,
    permits,
    purge_leak_tests,
    service_applications,
    timeline_commitments,
    turn_on_events,
)

app.register_blueprint(builders.bp)
app.register_blueprint(service_applications.bp)
app.register_blueprint(appliance_loads.bp)
app.register_blueprint(main_extensions.bp)
app.register_blueprint(ciac.bp)
app.register_blueprint(permits.bp)
app.register_blueprint(crews.bp)
app.register_blueprint(inspections.bp)
app.register_blueprint(meter_sets.bp)
app.register_blueprint(purge_leak_tests.bp)
app.register_blueprint(turn_on_events.bp)
app.register_blueprint(timeline_commitments.bp)
app.register_blueprint(gis.bp)
app.register_blueprint(clock.bp)


# --- Error handlers ---

@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_INVALID_REQUEST", "Resource or route not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
