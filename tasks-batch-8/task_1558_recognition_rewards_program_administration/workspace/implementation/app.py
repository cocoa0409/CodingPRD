"""Recognition & Rewards Program Administration API — entry point.

Flask app wiring: blueprint registration, envelope-shaped error handlers, and
the foreground server (0.0.0.0:$PORT, default 10000).
"""
import os
import traceback

from flask import Flask

from errors import ApiError
from response import error
import routes_core
import routes_nominations
import routes_commerce
import routes_finance

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_nominations.bp)
app.register_blueprint(routes_commerce.bp)
app.register_blueprint(routes_finance.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(exc):
    return error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error("ERR_NOT_FOUND", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc()
    return error("ERR_INTERNAL", 500, "Internal server error: %s" % exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
