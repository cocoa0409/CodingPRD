"""Export Trade Documentation API — entry point."""
import os
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response


class Provider(DefaultJSONProvider):
    sort_keys = False

    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return float(value)
        return DefaultJSONProvider.default(value)


def create_app():
    app = Flask(__name__)
    app.json = Provider(app)
    app.url_map.strict_slashes = False

    import routes_buyers
    import routes_orders
    import routes_compliance
    import routes_lc
    import routes_reviews
    import routes_docs
    import routes_freight
    import routes_present
    import routes_finance

    for module in (routes_buyers, routes_orders, routes_compliance, routes_lc,
                   routes_reviews, routes_docs, routes_freight, routes_present,
                   routes_finance):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error_response(ApiError("ERR_VALIDATION", exc.code or 400,
                                       exc.description or "request could not be handled"))

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover
        return error_response(ApiError("ERR_VALIDATION", 500, str(exc)))

    return app


application = create_app()

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
                    threaded=False, debug=False, use_reloader=False)
