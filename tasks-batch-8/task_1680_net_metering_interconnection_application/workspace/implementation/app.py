"""Entry point: Flask app, error handlers, blueprint registration."""

import os
import traceback

from flask import Flask

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_accounts
    import routes_applications
    import routes_core
    import routes_engineering
    import routes_field
    import routes_metering

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_accounts.bp)
    app.register_blueprint(routes_applications.bp)
    app.register_blueprint(routes_engineering.bp)
    app.register_blueprint(routes_field.bp)
    app.register_blueprint(routes_metering.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return envelope.error("ERR_NOT_FOUND", "The referenced resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return envelope.error("ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return envelope.error("ERR_INTERNAL", "An internal error occurred.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
