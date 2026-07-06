import os

from flask import Flask

from errors import ApiError
from response import error_body

from routes.customers import bp as customers_bp
from routes.skus import bp as skus_bp
from routes.lots import bp as lots_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.orders import bp as orders_bp
from routes.bulk_quotes import bp as bulk_quotes_bp
from routes.referrals import bp as referrals_bp
from routes.winback import bp as winback_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(skus_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(bulk_quotes_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(winback_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_body(e.error_id, e.message)
        return body, e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return error_body("ERR_NOT_FOUND", "Resource not found"), 404

    @app.errorhandler(405)
    def handle_405(e):
        return error_body("ERR_NOT_FOUND", "Method not allowed"), 404

    @app.errorhandler(400)
    def handle_400(e):
        return error_body("ERR_INVALID_REQUEST", "Bad request"), 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        return error_body("ERR_INVALID_REQUEST", str(e)), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
