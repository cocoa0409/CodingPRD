"""Massage Therapy Practice API — Flask entry point.

In-memory only. No seeding. Boots clean on every process start.
"""
import os

from flask import Flask

import response
from errors import ApiError
from routes import (
    modalities, therapists, tables, plans, clients, packages,
    appointments, soap_notes, superbills, clock_route,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(modalities.bp)
app.register_blueprint(therapists.bp)
app.register_blueprint(tables.bp)
app.register_blueprint(plans.bp)
app.register_blueprint(clients.bp)
app.register_blueprint(packages.bp)
app.register_blueprint(appointments.bp)
app.register_blueprint(soap_notes.bp)
app.register_blueprint(superbills.bp)
app.register_blueprint(clock_route.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return response.error(e.error_id, e.message, e.http_status)
    # Surface as a generic invalid-request so the envelope is preserved.
    return response.error("ERR_INVALID_REQUEST", str(e), 422)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
