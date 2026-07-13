"""Special Assessment District API — Flask entry point."""
import os

from flask import Flask

from web import ApiError, error_response
from logic import promote_all

from routes.districts import bp as districts_bp
from routes.parcels import bp as parcels_bp
from routes.rolls import bp as rolls_bp
from routes.bonds import bp as bonds_bp
from routes.installments import bp as installments_bp
from routes.payments import bp as payments_bp
from routes.quotes import bp as quotes_bp
from routes.foreclosures import bp as foreclosures_bp
from routes.liens import bp as liens_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _promote():
        promote_all()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    for bp in (districts_bp, parcels_bp, rolls_bp, bonds_bp, installments_bp,
               payments_bp, quotes_bp, foreclosures_bp, liens_bp, clock_bp):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
