"""Entry point: Flask app, JSON encoding, error handlers, route registration."""
import os
from decimal import Decimal

from flask import Flask, g, jsonify
from flask.json.provider import DefaultJSONProvider

from errors import ApiError
from response import error_response


class DecimalJSONProvider(DefaultJSONProvider):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def create_app():
    app = Flask(__name__)
    app.json = DecimalJSONProvider(app)

    @app.before_request
    def _init_request_state():
        g._dirty = set()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(Exception)
    def _internal(e):
        return error_response("ERR_INTERNAL", str(e), 500)

    from routes.core import bp as core_bp
    from routes.models import bp as models_bp
    from routes.cycles import bp as cycles_bp
    from routes.people import bp as people_bp
    from routes.instruments import bp as instruments_bp
    from routes.observations import bp as observations_bp
    from routes.quality import bp as quality_bp
    from routes.reports import bp as reports_bp
    from routes.vendors import bp as vendors_bp
    from routes.improvements import bp as improvements_bp

    for bp in (
        core_bp,
        models_bp,
        cycles_bp,
        people_bp,
        instruments_bp,
        observations_bp,
        quality_bp,
        reports_bp,
        vendors_bp,
        improvements_bp,
    ):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
