"""Remote Cardiac Monitoring API -- Flask entry point."""
import os

from flask import Flask

from bp import bp
from errors import ApiError
from response import error_response

# Route modules register themselves on bp at import time.
import routes_registry  # noqa: F401
import routes_orders  # noqa: F401
import routes_episodes  # noqa: F401
import routes_alerts  # noqa: F401
import routes_reports  # noqa: F401
import routes_billing  # noqa: F401
import routes_ops  # noqa: F401

app = Flask(__name__)
app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.status, e.message)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.status, e.message)
    return error_response("ERR_INTERNAL", 500, str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
