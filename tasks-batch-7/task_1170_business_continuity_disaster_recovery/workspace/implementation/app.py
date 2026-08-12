"""BC/DR Program API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. Storage is in-memory
only; the store starts empty on every boot.
"""
import os

from flask import Flask, jsonify

from core import ApiError, LOCK, err_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize all requests: the in-memory store is single-writer.
@app.before_request
def _acquire_lock():
    LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(error):
    return err_response(error)


@app.errorhandler(404)
def _not_found(error):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _method_not_allowed(error):
    return err_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405,
                                 "Method not allowed"))


@app.errorhandler(500)
def _internal_error(error):
    return err_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


from routes_registry import bp as registry_bp
from routes_analysis import bp as analysis_bp
from routes_vendor_site import bp as vendor_site_bp
from routes_exercise import bp as exercise_bp
from routes_capability import bp as capability_bp
from routes_crisis import bp as crisis_bp

for blueprint in (registry_bp, analysis_bp, vendor_site_bp, exercise_bp,
                  capability_bp, crisis_bp):
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
