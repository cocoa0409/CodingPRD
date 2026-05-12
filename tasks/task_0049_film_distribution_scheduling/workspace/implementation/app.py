"""Flask entry point — wires blueprints and error handlers."""

import os

from flask import Flask

from errors import APIError, ERR_BAD_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.distributors import bp as distributors_bp
from routes.films import bp as films_bp
from routes.cinemas import bp as cinemas_bp
from routes.screens import bp as screens_bp
from routes.showtimes import bp as showtimes_bp
from routes.tickets import bp as tickets_bp
from routes.settlements import bp as settlements_bp
from routes.reports import bp as reports_bp
from routes.harness import bp as harness_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response(ERR_NOT_FOUND, 404, "route not found")

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(ERR_NOT_FOUND, 404, "method not allowed")

    @app.errorhandler(400)
    def handle_400(_):
        return error_response(ERR_BAD_REQUEST, 400, "bad request")

    @app.errorhandler(Exception)
    def handle_exception(e):
        # Re-raise APIError so the dedicated handler picks it up
        if isinstance(e, APIError):
            return error_response(e.error_id, e.http_status, e.message)
        # Otherwise 500 framed as ERR_BAD_REQUEST is not ideal — log and return ERR_BAD_REQUEST
        # Return a generic 500 message in our envelope.
        return error_response("ERR_INTERNAL", 500, str(e))

    app.register_blueprint(distributors_bp)
    app.register_blueprint(films_bp)
    app.register_blueprint(cinemas_bp)
    app.register_blueprint(screens_bp)
    app.register_blueprint(showtimes_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(harness_bp)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
