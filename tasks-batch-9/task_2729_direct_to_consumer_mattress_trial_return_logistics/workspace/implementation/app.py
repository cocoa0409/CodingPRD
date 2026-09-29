"""Direct-to-Consumer Mattress Trial & Return Logistics API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import failure
from routes.attribution import bp as attribution_bp
from routes.catalog import bp as catalog_bp
from routes.claims import bp as claims_bp
from routes.customers import bp as customers_bp
from routes.exchanges import bp as exchanges_bp
from routes.logistics import bp as logistics_bp
from routes.orders import bp as orders_bp
from routes.refunds import bp as refunds_bp
from routes.returns import bp as returns_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    # Every collection is top level: there is no shared API prefix.
    for blueprint in (catalog_bp, customers_bp, orders_bp, claims_bp,
                      exchanges_bp, returns_bp, logistics_bp, refunds_bp,
                      attribution_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return failure(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return failure("ERR_INVALID_REQUEST",
                       exc.description or "Invalid request",
                       exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return failure("ERR_INVALID_REQUEST", "Invalid request: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
