import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.clients import bp as clients_bp
from routes.programs import bp as programs_bp
from routes.accounts import bp as accounts_bp
from routes.debts import bp as debts_bp
from routes.deposits import bp as deposits_bp
from routes.offers import bp as offers_bp
from routes.settlements import bp as settlements_bp
from routes.fees import bp as fees_bp
from routes.lawsuits import bp as lawsuits_bp
from routes.tax_events import bp as tax_events_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, clients_bp, programs_bp, accounts_bp, debts_bp,
        deposits_bp, offers_bp, settlements_bp, fees_bp, lawsuits_bp, tax_events_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        body = error_response(err.error_id, err.message)
        return body, err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found"), 404

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed"), 404

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Bad request"), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return handle_api_error(err)
        return error_response("ERR_INVALID_REQUEST", str(err)), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
