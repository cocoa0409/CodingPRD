"""Store Closing Liquidation API. Flask app factory and error plumbing.

Storage is in-memory only and starts completely empty on every boot; the test
harness reboots this process before every single test.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes_augmentation
import routes_engagement
import routes_license
import routes_money
import routes_staffing
import routes_store
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_engagement.bp)
    app.register_blueprint(routes_store.bp)
    app.register_blueprint(routes_license.bp)
    app.register_blueprint(routes_augmentation.bp)
    app.register_blueprint(routes_staffing.bp)
    app.register_blueprint(routes_money.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return response.error(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be routed",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
