"""Beehive Hosting API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error as error_response

app = Flask(__name__)


@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def _not_found(err):
    return error_response(ERR_NOT_FOUND[0], 404, "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(err):
    return error_response(ERR_NOT_FOUND[0], 404, "Resource not found")


@app.errorhandler(Exception)
def _unhandled(err):
    if isinstance(err, HTTPException):
        return error_response(ERR_INVALID_REQUEST[0], err.code or 400, err.description)
    return error_response(ERR_INVALID_REQUEST[0], 500, "Internal server error: %s" % err)


from routes_core import bp as core_bp
from routes_agreements import bp as agreements_bp
from routes_field import bp as field_bp
from routes_ops import bp as ops_bp

app.register_blueprint(core_bp)
app.register_blueprint(agreements_bp)
app.register_blueprint(field_bp)
app.register_blueprint(ops_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
