"""Curriculum Approval & Catalog Publication API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import err

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_catalog
import routes_core
import routes_proposals
import routes_teachout

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_proposals.bp)
app.register_blueprint(routes_teachout.bp)
app.register_blueprint(routes_catalog.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_not_found(e):
    return err("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return err("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    return err("ERR_INTERNAL", 500, str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
