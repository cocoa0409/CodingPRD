"""UL 508A Panel Shop API — Flask entry point.

In-memory only; a fresh process is a pristine server. All data is created
via API calls; nothing is seeded at startup.
"""

import os

from flask import Flask, jsonify

from core import (
    ApiError,
    envelope_error,
    err_not_found,
    err_invalid_request,
)
from store import db  # noqa: F401  (module-level empty store)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_panels
    import routes_catalog
    import routes_subst
    import routes_testing
    import routes_programs
    import routes_startup
    import routes_changeorders
    import routes_warranty
    import routes_asbuilt

    for module in (
        routes_core,
        routes_panels,
        routes_catalog,
        routes_subst,
        routes_testing,
        routes_programs,
        routes_startup,
        routes_changeorders,
        routes_warranty,
        routes_asbuilt,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body, code = envelope_error(e)
        return jsonify(body), code

    @app.errorhandler(404)
    def handle_404(e):
        body, code = envelope_error(err_not_found("Resource not found."))
        return jsonify(body), code

    @app.errorhandler(405)
    def handle_405(e):
        body, code = envelope_error(err_not_found("Resource not found."))
        return jsonify(body), code

    @app.errorhandler(400)
    def handle_400(e):
        if isinstance(e, ApiError):
            body, code = envelope_error(e)
        else:
            body, code = envelope_error(err_invalid_request("Bad request."))
        return jsonify(body), code

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            body, code = envelope_error(e)
            return jsonify(body), code
        import traceback

        traceback.print_exc()
        from core import err_bad_body

        body, code = envelope_error(
            ApiError("ERR_INVALID_REQUEST", 400, "Unexpected server error.")
        )
        return jsonify(body), code

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
