"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from db import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_resp, error_body

app = Flask(__name__)

# Serialize all request handling within the process (single-writer simplicity).
@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    db.lock.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_resp(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_body_resp(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_e):
    return error_body_resp(ERR_INVALID_REQUEST, "Method not allowed", 405)


def error_body_resp(error_id, message, status):
    from flask import jsonify
    return jsonify(error_body(error_id, message)), status


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_resp(err)
    import traceback
    traceback.print_exc()
    return error_body_resp(ERR_INVALID_REQUEST, f"Unexpected error: {err}", 400)


from routes import (
    clock, technicians, accounts, meters, periods, routes as routes_mod,
    stops, reads, hazards, workorders, investigations, campaigns, snapshots,
)

for mod in (
    clock, technicians, accounts, meters, periods, routes_mod,
    stops, reads, hazards, workorders, investigations, campaigns, snapshots,
):
    app.register_blueprint(mod.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
