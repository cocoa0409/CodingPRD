import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.brands import bp as brands_bp
from routes.creators import bp as creators_bp
from routes.campaigns import bp as campaigns_bp
from routes.offers import bp as offers_bp
from routes.contracts import bp as contracts_bp
from routes.content import bp as content_bp
from routes.attribution import bp as attribution_bp
from routes.payouts import bp as payouts_bp
from routes.tax_forms import bp as tax_forms_bp
from routes.brand_safety import bp as brand_safety_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(brands_bp)
    app.register_blueprint(creators_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(attribution_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(tax_forms_bp)
    app.register_blueprint(brand_safety_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        resp = error_response(e.error_id, e.message)
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(e):
        resp = error_response("ERR_NOT_FOUND", "Resource not found")
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(e):
        resp = error_response("ERR_NOT_FOUND", "Method not allowed")
        resp.status_code = 404
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        resp = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
        resp.status_code = 422
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
