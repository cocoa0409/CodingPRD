"""Athletic Training Injury Management API — Flask entry point."""
import os

from flask import Flask

import db
from errors import ApiError
from response import error_response
from routes.clock import bp as clock_bp
from routes.core import bp as core_bp
from routes.medical import bp as medical_bp
from routes.supplies import bp as supplies_bp
from routes.venues_events import bp as venues_events_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(core_bp)
app.register_blueprint(venues_events_bp)
app.register_blueprint(medical_bp)
app.register_blueprint(supplies_bp)
app.register_blueprint(clock_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_NOT_FOUND", "The requested resource was not found.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_NOT_FOUND", "The requested resource was not found.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    app.logger.exception("Unhandled error")
    return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 400)


@app.before_request
def serialize_requests():
    db.lock.acquire()


@app.teardown_request
def release_lock(exc=None):
    db.lock.release()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
