"""Life Science Building Conversion & Tenant Fit-Out API.

Flask application factory. All state lives in the process's own dictionaries
(see db.py) and nothing is seeded: every entity is created by a request.
"""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException
from werkzeug.serving import WSGIRequestHandler

# One request per connection. Werkzeug silently upgrades a threaded dev server to
# HTTP/1.1 (and therefore keep-alive) unless the handler pins a protocol version
# itself; pinning HTTP/1.0 here means every response closes its socket, so a
# client that pools connections can never hand a request to a socket this
# process has already torn down. Pure transport configuration -- it changes no
# endpoint, payload, header or side effect of the API.
WSGIRequestHandler.protocol_version = "HTTP/1.0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import response  # noqa: E402
import routes  # noqa: E402
from errors import ApiError  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    routes.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error("ERR_NOT_FOUND", "The requested resource does not exist", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this resource", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error("ERR_VALIDATION", "Request body is malformed", 422)
        return response.error("ERR_INTERNAL", exc.description or "Request failed",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
