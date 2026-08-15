"""Charity Thrift Store API — Flask entry point.

Storage is in-memory only (module-level dicts). No seeding: the store starts
empty on every boot; every entity is built through the declared API surface.
"""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)

from routes import clock, donors, batches, items, guidelines, salvage, till, pickups, workforce, cycles

app.register_blueprint(clock.bp)
app.register_blueprint(donors.bp)
app.register_blueprint(batches.bp)
app.register_blueprint(items.bp)
app.register_blueprint(guidelines.bp)
app.register_blueprint(salvage.bp)
app.register_blueprint(till.bp)
app.register_blueprint(pickups.bp)
app.register_blueprint(workforce.bp)
app.register_blueprint(cycles.bp)


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
    # Malformed JSON and similar client faults must surface as 400s, not 500s.
    from werkzeug.exceptions import BadRequest
    if isinstance(e, BadRequest):
        return error_response(ERR_INVALID_REQUEST, "Malformed request body", 400)
    return error_response(ERR_INVALID_REQUEST, "Unexpected error: %s" % e, 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
