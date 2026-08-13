"""Flask entry point: error handlers and route registration.

The store starts empty on every boot — no seeding of any kind.
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error as error_response
from routes import models, hard_parts, interchange, orders, dyno, cores, warranty, clock


def create_app():
    app = Flask(__name__)

    app.register_blueprint(models.bp)
    app.register_blueprint(hard_parts.bp)
    app.register_blueprint(interchange.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(dyno.bp)
    app.register_blueprint(cores.bp)
    app.register_blueprint(warranty.bp)
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_INVALID_REQUEST, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ERR_INVALID_REQUEST, str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
