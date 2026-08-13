"""Fishery Observer & Catch Monitoring Program API — entry point.

Flask app wiring: blueprints, error handlers, and the foreground server.
Storage is in-memory only and starts empty on every boot.
"""

import os

from flask import Flask

from core import ApiError, err_response

import routes_billing
import routes_deployments
import routes_em
import routes_harassment
import routes_plans
import routes_registries

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    routes_registries,
    routes_plans,
    routes_deployments,
    routes_harassment,
    routes_em,
    routes_billing,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "The requested resource does not exist"))


@app.errorhandler(405)
def handle_405(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "The requested resource does not exist"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e)
    return err_response(ApiError("ERR_INVALID_REQUEST", 400, "Malformed request"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
