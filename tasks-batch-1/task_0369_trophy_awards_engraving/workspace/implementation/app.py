import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.customers import bp as customers_bp
from routes.catalog import bp as catalog_bp
from routes.components import bp as components_bp
from routes.policies import bp as policies_bp
from routes.clock import bp as clock_bp
from routes.orders import bp as orders_bp
from routes.payments import bp as payments_bp
from routes.proofs import bp as proofs_bp
from routes.production import bp as production_bp
from routes.fulfillment import bp as fulfillment_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(components_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(proofs_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(fulfillment_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request")

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", e.code or 400, str(e))
        return error_response("ERR_INVALID_REQUEST", 500, "Internal error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
