"""Entry point: app factory, error handlers, blueprint registration."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.challenges import bp as challenges_bp
from routes.orders import bp as orders_bp
from routes.testdrive import bp as testdrive_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(challenges_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(testdrive_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed.")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request.")

    @app.errorhandler(HTTPException)
    def handle_http(e):
        return error_response("ERR_INVALID_REQUEST", e.code or 400, str(e))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", 400, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
