"""Ambient Air Monitoring Network Operations API.

Flask entry point: blueprint registration and the error envelope handlers.
Storage is in-memory only and starts completely empty on every boot -- no
entity is ever seeded, preloaded or hardcoded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import assessments, batches, change_requests, clock_routes, demos
from routes import design_values, monitors, networks, packages, pollutants, sites

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for blueprint in (
    pollutants.bp,
    networks.bp,
    sites.bp,
    monitors.bp,
    batches.bp,
    demos.bp,
    design_values.bp,
    packages.bp,
    assessments.bp,
    change_requests.bp,
    clock_routes.bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return response.error_response("ERR_INVALID_REQUEST", "The requested route does not exist.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return response.error_response(
        "ERR_INVALID_REQUEST", "The method is not allowed for the requested route.", 405)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    status = exc.code or 500
    if status == 400:
        return response.error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.", 400)
    return response.error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return response.error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
