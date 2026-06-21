"""Custom Picture Framing API — Flask entry point.

In-memory storage only (db.db). No seeding at startup: the store starts empty
on every boot and tests build all preconditions via the declared API surface.
"""
import os
import subprocess
import sys

try:
    from flask import Flask, request
except ImportError:
    # First boot only: install dependencies, then import. Subsequent per-test
    # reboots skip this branch (flask already importable), so the hot restart
    # path stays a single fast process spawn.
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    from flask import Flask, request

from errors import ApiError
from middleware import get_auth
from response import error_response

# Blueprints
from routes.customers import bp as customers_bp
from routes.workbenches import bp as workbenches_bp
from routes.orders import bp as orders_bp
from routes.frame_lines import bp as frame_lines_bp
from routes.production_tasks import bp as production_tasks_bp
from routes.payments import bp as payments_bp
from routes.notifications import bp as notifications_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(customers_bp)
app.register_blueprint(workbenches_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(frame_lines_bp)
app.register_blueprint(production_tasks_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(notifications_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    # Unknown route. Auth is still the highest-priority concern; if auth headers
    # are missing/malformed, report that, otherwise a not-found.
    try:
        get_auth()
    except ApiError as e:
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_ORDER_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    try:
        get_auth()
    except ApiError as e:
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(err), 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
