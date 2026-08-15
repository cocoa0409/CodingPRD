"""Temporary Power & Climate Rental API — entry point.

Boots a Flask server bound to 0.0.0.0:$PORT (default 10000). All state is
in-memory and empty at startup; the logical clock starts at
2026-08-01T00:00:00Z and advances only via POST /_clock/set_current_utc.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response, error_from_spec
from routes.contracts import bp as contracts_bp
from routes.core import bp as core_bp
from routes.ops import bp as ops_bp

app = Flask(__name__)
app.register_blueprint(core_bp)
app.register_blueprint(contracts_bp)
app.register_blueprint(ops_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_from_spec(ERR_NOT_FOUND, "Resource not found.")


@app.errorhandler(405)
def handle_405(err):
    return error_from_spec(ERR_NOT_FOUND, "Resource not found.")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", str(err), 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
