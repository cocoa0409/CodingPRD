"""Supermarket refrigerant management and leak-compliance API.

Entry point: registers every blueprint, installs the envelope-shaped error
handlers, and serves on 0.0.0.0:$PORT. Storage is in-memory and starts empty
on every boot -- nothing is seeded here or anywhere else.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (cylinders, extension_requests, inspections, leak_events, ops,
                    recovery_equipment, regulatory_reports, repair_attempts,
                    retrofit_plans, service_records, stores, systems,
                    technicians, verification_tests)

BLUEPRINTS = (
    stores.bp,
    systems.bp,
    technicians.bp,
    recovery_equipment.bp,
    cylinders.bp,
    service_records.bp,
    leak_events.bp,
    repair_attempts.bp,
    verification_tests.bp,
    extension_requests.bp,
    retrofit_plans.bp,
    regulatory_reports.bp,
    inspections.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(response.error_body(error)), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            mapped = ApiError("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        elif error.code == 405:
            mapped = ApiError("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this route.", 405)
        else:
            mapped = ApiError("ERR_INVALID_REQUEST", error.description or "Bad request",
                              error.code or 400)
        return jsonify(response.error_body(mapped)), mapped.http_status

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        mapped = ApiError("ERR_INTERNAL", "%s: %s" % (type(error).__name__, error), 500)
        return jsonify(response.error_body(mapped)), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
