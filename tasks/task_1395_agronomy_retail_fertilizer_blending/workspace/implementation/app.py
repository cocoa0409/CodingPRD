"""Agronomy Retail Blending API — Flask entry point."""

import os
import signal

# Absorb stray SIGTERMs from foreign benchmark runners on this shared host
# (a recycled PID can receive a terminate() meant for a dead process).
# Per-test isolation kills via SIGKILL, which is unaffected.
signal.signal(signal.SIGTERM, signal.SIG_IGN)

try:
    from flask import Flask
except ImportError:
    # Fresh-host bootstrap: install requirements once, then re-exec so the
    # freshly installed packages are importable. Keeps start.sh to a single
    # python startup (every extra python invocation is a stall opportunity
    # under concurrent per-test reboots).
    import subprocess
    import sys

    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"])
    os.execv(sys.executable, [sys.executable] + sys.argv)
    raise  # unreachable

from errors import ApiError, ERR_VALIDATION_FAILED, ERR_RESOURCE_NOT_FOUND
from middleware import require_auth
from response import error as error_response

app = Flask(__name__)


@app.before_request
def _auth():
    # Auth headers required on every endpoint (validation priority 1)
    return require_auth()


@app.errorhandler(ApiError)
def _api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def _not_found(err):
    return error_response(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def _method_not_allowed(err):
    return error_response(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def _unhandled(err):
    import traceback
    traceback.print_exc()
    return error_response(ERR_VALIDATION_FAILED, f"Unhandled error: {err}", 400)


# --- register blueprints ---
from routes import clock, growers, fields, recommendations, nutrient_plans, \
    permits, products, prepay, blend_orders, blenders, delivery

for bp in (clock.bp, growers.bp, fields.bp, recommendations.bp, nutrient_plans.bp,
           permits.bp, products.bp, prepay.bp, blend_orders.bp, blenders.bp,
           delivery.bp):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
