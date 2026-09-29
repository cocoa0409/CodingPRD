"""Branch Network Optimization API - entry point.

The store is in-memory and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded here.  Every resource is created by the caller
through the declared endpoints.
"""
import os

from flask import Flask, g

from core import ApiError, LOCK, error_response
import routes_network
import routes_cases
import routes_regulatory
import routes_disposition
import routes_growth

app = Flask(__name__)
app.json.sort_keys = False
app.url_map.strict_slashes = False

app.register_blueprint(routes_network.bp)
app.register_blueprint(routes_cases.bp)
app.register_blueprint(routes_regulatory.bp)
app.register_blueprint(routes_disposition.bp)
app.register_blueprint(routes_growth.bp)


@app.before_request
def _serialize_request():
    LOCK.acquire()
    g._locked = True
    g._touched = set()


@app.teardown_request
def _release_request(_exc=None):
    if getattr(g, "_locked", False):
        g._locked = False
        try:
            LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def _handle_not_found(_err):
    return error_response("ERR_RESOURCE_NOT_FOUND", "The requested resource was not found.", 404)


@app.errorhandler(405)
def _handle_method_not_allowed(_err):
    return error_response("ERR_RESOURCE_NOT_FOUND",
                          "The requested resource was not found.", 404)


@app.errorhandler(400)
def _handle_bad_request(_err):
    return error_response("ERR_INVALID_REQUEST", "The request could not be understood.", 400)


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return _handle_api_error(err)
    app.logger.exception("unhandled error")
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % err, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
