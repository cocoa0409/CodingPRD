"""Lead Service Line Inventory & Replacement API.

Storage is entirely in-process: `core.Store` is a bag of plain dicts that starts
empty on every boot.  Nothing is persisted, cached on disk or seeded.
"""

import os
import subprocess
import sys

try:
    from flask import Flask
except ImportError:  # pragma: no cover - first boot on a bare interpreter only
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r",
                           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "requirements.txt")])
    from flask import Flask

from core import ApiError, respond_error
import routes_field
import routes_inventory
import routes_orders
import routes_publication
import routes_water


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_water.bp)
    app.register_blueprint(routes_inventory.bp)
    app.register_blueprint(routes_field.bp)
    app.register_blueprint(routes_publication.bp)
    app.register_blueprint(routes_orders.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return respond_error("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return respond_error("ERR_METHOD_NOT_ALLOWED",
                             "This method is not allowed on this route.", 405)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return respond_error("ERR_INVALID_REQUEST",
                             "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return respond_error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return respond_error("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
