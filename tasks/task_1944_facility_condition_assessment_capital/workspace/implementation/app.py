"""Facility Condition Assessment & Capital Planning API.

Entry point: registers blueprints, installs envelope-shaped error handlers,
and serves on 0.0.0.0:$PORT (default 10000). Storage is in-memory only and
starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError
from response import err
from routes import asset_systems, clients, deficiencies, facilities, misc, plans

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (clients, facilities, asset_systems, deficiencies, plans, misc):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return err(exc.error_id, exc.message, exc.status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return err("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return err("ERR_NOT_FOUND", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return err("ERR_INTERNAL", f"Internal server error: {exc}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
