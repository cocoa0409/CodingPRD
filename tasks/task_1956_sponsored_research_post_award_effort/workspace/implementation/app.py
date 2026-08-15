"""Entry point: Flask app, error handlers, blueprint registration.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. Storage is in-memory
only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_resp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_resp(e)


@app.errorhandler(404)
def handle_404(e):
    return error_resp(ApiError("ERR_INVALID_REQUEST", 404, "Resource path not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_resp(ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_resp(e)
    return error_resp(ApiError("ERR_INVALID_REQUEST", 500, "Internal error: %s" % e))


import routes_cash
import routes_core
import routes_effort
import routes_exp
import routes_mods
import routes_sub

for module in (routes_core, routes_exp, routes_effort, routes_sub, routes_cash, routes_mods):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
