"""Partnership K-1 Administration API — Flask entry point."""
import os
import traceback

from flask import Flask, jsonify

from db import db, now, fmt_ts
from util import ApiError, error_envelope, new_request_id

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes
import routes_transfers_alloc
import routes_state_wh
import routes_k1

app.register_blueprint(routes.bp)
app.register_blueprint(routes_transfers_alloc.bp)
app.register_blueprint(routes_state_wh.bp)
app.register_blueprint(routes_k1.bp)


@app.before_request
def acquire_lock():
    db.lock.acquire()


@app.teardown_request
def release_lock(exc):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_envelope(err)


@app.errorhandler(404)
def handle_not_found(err):
    return error_envelope(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_envelope(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    return error_envelope(ApiError("ERR_INTERNAL", 500, "Internal server error: %s" % err))


@app.get("/")
def root():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
