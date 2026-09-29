"""Assortment Planning & Open-to-Buy API — entry point.

The in-memory store starts EMPTY on every boot; nothing is ever seeded.
"""
import os
import threading

from flask import Flask, g

from common import ApiError, respond_error
import routes_commit
import routes_gov
import routes_item
import routes_plan
import routes_ref

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_ref.bp)
app.register_blueprint(routes_plan.bp)
app.register_blueprint(routes_item.bp)
app.register_blueprint(routes_commit.bp)
app.register_blueprint(routes_gov.bp)

# One request at a time: every multi-link cascade is applied atomically (§2.10).
_LOCK = threading.Lock()


@app.before_request
def _acquire():
    _LOCK.acquire()
    g._holds_lock = True


@app.teardown_request
def _release(exc=None):
    if getattr(g, "_holds_lock", False):
        g._holds_lock = False
        try:
            _LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _api_error(err):
    return respond_error(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def _not_found(err):
    return respond_error("ERR_INVALID_REQUEST", "no such route", 404)


@app.errorhandler(405)
def _not_allowed(err):
    return respond_error("ERR_INVALID_REQUEST", "method not allowed for this route", 405)


@app.errorhandler(400)
def _bad_request(err):
    return respond_error("ERR_INVALID_REQUEST", "malformed request", 400)


@app.errorhandler(Exception)
def _unhandled(err):
    if isinstance(err, ApiError):
        return _api_error(err)
    app.logger.exception("unhandled error")
    return respond_error("ERR_INVALID_REQUEST", "unhandled server error: %s" % err, 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
