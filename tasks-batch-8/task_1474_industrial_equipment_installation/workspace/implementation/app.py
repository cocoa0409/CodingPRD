"""Entry point: Flask app assembly, error handlers, route registration."""
import os
import threading

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error as error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize requests: the in-memory store is plain dicts, and per-test reboots
# run concurrently against their own processes.
_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    _LOCK.release()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return error_response(ERR_NOT_FOUND, 404, "resource not found")


@app.errorhandler(405)
def _handle_405(e):
    return error_response(ERR_NOT_FOUND, 404, "resource not found")


@app.errorhandler(Exception)
def _handle_unexpected(e):
    return error_response("ERR_INTERNAL", 500, str(e))


from routes.alignments import bp as alignments_bp
from routes.checklists import bp as checklists_bp
from routes.clock import bp as clock_bp
from routes.invoices import bp as invoices_bp
from routes.labor import bp as labor_bp
from routes.lifts import bp as lifts_bp
from routes.lockouts import bp as lockouts_bp
from routes.projects import bp as projects_bp
from routes.rigging import bp as rigging_bp
from routes.safety import bp as safety_bp
from routes.site_surveys import bp as surveys_bp

for _bp in (projects_bp, surveys_bp, safety_bp, lockouts_bp, rigging_bp,
            lifts_bp, alignments_bp, checklists_bp, labor_bp, invoices_bp,
            clock_bp):
    app.register_blueprint(_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
