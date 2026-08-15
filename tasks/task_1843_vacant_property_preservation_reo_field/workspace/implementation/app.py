"""Vacant Property Preservation API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import err

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_core
import routes_work
import routes_inspection
import routes_muni
import routes_damage
import routes_invoice

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_work.bp)
app.register_blueprint(routes_inspection.bp)
app.register_blueprint(routes_muni.bp)
app.register_blueprint(routes_damage.bp)
app.register_blueprint(routes_invoice.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return err("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return err("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(500)
def handle_500(e):
    return err("ERR_INVALID_REQUEST", "Internal server error", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
