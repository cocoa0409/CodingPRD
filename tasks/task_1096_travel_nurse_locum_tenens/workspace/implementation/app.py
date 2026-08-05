import os

from flask import Flask, jsonify

from common import ApiError, error_response, _meta
from store import store

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _not_found(e):
    return error_response(ApiError("ERR_VALIDATION", 400, "Unknown route"))


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response(ApiError("ERR_VALIDATION", 400, "Method not allowed"))


@app.errorhandler(500)
def _server_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


# Register routes (import for side effects).
import views_core        # noqa: E402,F401
import views_assignment  # noqa: E402,F401
import views_credential  # noqa: E402,F401
import views_finance     # noqa: E402,F401


if __name__ == "__main__":
    # When launched as `python3 app.py`, this module is named __main__, but the
    # view modules import the app via `from app import app`, which loads a second
    # copy of this module under the name "app" and registers all routes on THAT
    # instance. Run that fully-configured instance instead of the routeless
    # __main__ one.
    import app as _appmod
    port = int(os.environ.get("PORT", "10000"))
    _appmod.app.run(host="0.0.0.0", port=port, threaded=True)
