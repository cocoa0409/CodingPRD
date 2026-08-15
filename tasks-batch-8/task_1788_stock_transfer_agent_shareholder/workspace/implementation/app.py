"""Stock Transfer Agent API — Flask entry point."""
import os

from flask import Flask, jsonify

from db import lock
from errors import ApiError
from response import error_body

app = Flask(__name__)
app.url_map.strict_slashes = False


# Serialize request handling so concurrent clients cannot interleave mutations.
@app.before_request
def _acquire_lock():
    lock.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_not_found(err):
    return jsonify(error_body("ERR_INVALID_REQUEST", "route not found")), 404


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return jsonify(error_body("ERR_INVALID_REQUEST", "method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return jsonify(error_body("ERR_INVALID_REQUEST", "internal error: %s" % err)), 500


from routes import issuers, accounts, positions, certificates, claims, transfers, \
    dividends, legends, escheatment, inquiries, misc  # noqa: E402

for module in (issuers, accounts, positions, certificates, claims, transfers,
               dividends, legends, escheatment, inquiries, misc):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
