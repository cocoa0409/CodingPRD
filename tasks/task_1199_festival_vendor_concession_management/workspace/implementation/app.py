"""Festival Vendor & Concession Management API — entry point.

Flask app wiring: blueprints, envelope-consistent error handlers, and the
foreground server. Storage is in-memory only and starts empty on every boot.
"""
import os
import traceback

from flask import Flask

from util import ApiError, error_response

app = Flask(__name__)

import routes_meta
import routes_apps
import routes_site
import routes_ops
import routes_money
import routes_compliance

app.register_blueprint(routes_meta.bp)
app.register_blueprint(routes_apps.bp)
app.register_blueprint(routes_site.bp)
app.register_blueprint(routes_ops.bp)
app.register_blueprint(routes_money.bp)
app.register_blueprint(routes_compliance.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.status, e.message)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_INVALID_REQUEST", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.status, e.message)
    traceback.print_exc()
    return error_response("ERR_INTERNAL", 500, f"Internal error: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
