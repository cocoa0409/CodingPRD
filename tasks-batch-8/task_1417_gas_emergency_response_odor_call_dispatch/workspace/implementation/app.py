"""Gas Emergency Response & Odor Call Dispatch API — Flask entry point."""
import os
import threading

from flask import Flask

import response
from errors import ApiError
from routes import (calls, clock_routes, crews, determinations, dispatches,
                    incidents, notifications, pauses, reports, shutoffs,
                    technicians, territories, workorders)

app = Flask(__name__)
app.json.sort_keys = False

# Serialize request handling: the in-memory store is plain dicts, and multi-step
# operations must be atomic with respect to concurrent requests.
_lock = threading.RLock()


@app.before_request
def _acquire():
    _lock.acquire()


@app.teardown_request
def _release(exc=None):
    _lock.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error(err)


@app.errorhandler(404)
def handle_404(err):
    return response.error(ApiError("ERR_INVALID_REQUEST", "Unknown route", 404))


@app.errorhandler(405)
def handle_405(err):
    return response.error(ApiError("ERR_INVALID_REQUEST", "Method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return response.error(err)
    app.logger.exception("unexpected error")
    return response.error(ApiError("ERR_INVALID_REQUEST", "Internal error: %s" % err, 400))


for bp in (clock_routes.bp, territories.bp, technicians.bp, crews.bp, calls.bp,
           incidents.bp, dispatches.bp, pauses.bp, shutoffs.bp, determinations.bp,
           workorders.bp, reports.bp, notifications.bp):
    app.register_blueprint(bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
