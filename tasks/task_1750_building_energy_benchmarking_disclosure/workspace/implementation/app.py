"""Building Energy Benchmarking & Disclosure API — Flask entry point."""
import os
import threading
import traceback

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes import (registry, cycles, buildings, tenant_units, consents,
                    utility, reports, verifications, anomalies, fines,
                    exemptions, disclosures, clock)

app = Flask(__name__)
app.url_map.strict_slashes = False

_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    if _LOCK._is_owned():
        _LOCK.release()


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, "Unexpected request failure"))


for module in (registry, cycles, buildings, tenant_units, consents, utility,
               reports, verifications, anomalies, fines, exemptions,
               disclosures, clock):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
