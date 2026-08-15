"""Entry point: Flask app, error handlers, request serialization, route registration."""

import os
from flask import Flask

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


# Serialize all requests through one lock: cascades touch many resources per
# call and must never interleave with another request.
@app.before_request
def _acquire_store_lock():
    store.lock.acquire()


@app.teardown_request
def _release_store_lock(exc):
    store.lock.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_INVALID_REQUEST, 400, "Bad request")


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    import traceback
    traceback.print_exc()
    return error_response(ERR_INVALID_REQUEST, 400, f"Unhandled error: {err}")


# register blueprints
from routes.clock import bp as clock_bp
from routes.contractors import bp as contractors_bp
from routes.technicians import bp as technicians_bp
from routes.properties import bp as properties_bp
from routes.systems import bp as systems_bp
from routes.devices import bp as devices_bp
from routes.plans import bp as plans_bp
from routes.events import bp as events_bp
from routes.deficiencies import bp as deficiencies_bp
from routes.impairments import bp as impairments_bp
from routes.reports import bp as reports_bp
from routes.specialty_tests import bp as specialty_tests_bp
from routes.alarms import bp as alarms_bp
from routes.permits import bp as permits_bp

app.register_blueprint(clock_bp)
app.register_blueprint(contractors_bp)
app.register_blueprint(technicians_bp)
app.register_blueprint(properties_bp)
app.register_blueprint(systems_bp)
app.register_blueprint(devices_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(events_bp)
app.register_blueprint(deficiencies_bp)
app.register_blueprint(impairments_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(specialty_tests_bp)
app.register_blueprint(alarms_bp)
app.register_blueprint(permits_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
