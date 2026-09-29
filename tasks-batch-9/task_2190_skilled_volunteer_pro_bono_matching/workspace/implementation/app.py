"""Application factory and process entry point.

State is entirely in-memory (see store.py): a fresh process is a fresh, empty
program.  Nothing is ever seeded -- every entity the tests use is created
through the declared endpoints.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request  # noqa: E402

import guards as G  # noqa: E402
import response as R  # noqa: E402
from errors import ApiError  # noqa: E402
from routes.cycles import bp as cycles_bp  # noqa: E402
from routes.engagements import bp as engagements_bp  # noqa: E402
from routes.offers import bp as offers_bp  # noqa: E402
from routes.partners import bp as partners_bp  # noqa: E402
from routes.requests import bp as requests_bp  # noqa: E402
from routes.volunteers import bp as volunteers_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(partners_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(volunteers_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(engagements_bp)

    @app.before_request
    def _authenticate():
        if request.url_rule is None:
            return None  # let the router answer 404/405 first
        # priority 1 then priority 2 of the rejection ladder
        G.g01_auth_headers()
        G.g02_role_permitted(G.ROLE_REGISTRY.get(request.endpoint))
        return None

    @app.errorhandler(ApiError)
    def _api_error(err):
        return R.error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return R.error_response(ApiError("ERR_NOT_FOUND", "Unknown resource path"))

    @app.errorhandler(405)
    def _not_allowed(_err):
        return R.error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed on this path")
        )

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return R.error_response(err)
        return R.error_response(ApiError("ERR_INTERNAL", str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # threaded=True only affects how connections are accepted; the request handling
    # itself remains effectively serial for a single sequential client.  A serial
    # accept loop makes the boot-adjacent window fragile under heavy parallel load.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
