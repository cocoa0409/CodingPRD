"""Entry point: Flask app, JSON encoding, error handlers, route registration."""
import os
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider

from errors import ApiError, ERR_NOT_FOUND, ERR_INTERNAL
from response import error_response


class DecimalJSONProvider(DefaultJSONProvider):
    @staticmethod
    def _convert(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(
            "Object of type %s is not JSON serializable" % type(obj).__name__)

    def __init__(self, app):
        super().__init__(app)
        self.default = self._convert


def create_app():
    app = Flask(__name__)
    app.json = DecimalJSONProvider(app)

    from routes_suppliers import bp as suppliers_bp, clock_bp
    from routes_entries import bp as entries_bp
    from routes_processing import bp as processing_bp
    from routes_compliance import bp as compliance_bp

    app.register_blueprint(suppliers_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(processing_bp)
    app.register_blueprint(compliance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ERR_INTERNAL, "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
