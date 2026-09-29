"""Private Fleet Operations & Backhaul Optimization API.

Entry point: blueprint registration and the error envelope. The in-memory store
starts completely empty on every boot -- nothing is seeded, preloaded or
hardcoded here or in any imported module.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_backhaul
import routes_board
import routes_fleet
import routes_network
import routes_orders
import routes_pay
import routes_trips

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (
    routes_network,
    routes_fleet,
    routes_orders,
    routes_trips,
    routes_backhaul,
    routes_pay,
    routes_board,
):
    app.register_blueprint(module.bp, url_prefix="/fleet")


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return respond_error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return respond_error("ERR_INVALID_REQUEST", "No such route.", 404)
    if exc.code == 405:
        return respond_error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
    if exc.code == 400:
        return respond_error("ERR_INVALID_REQUEST", "Malformed request.", 400)
    return respond_error("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return respond_error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
