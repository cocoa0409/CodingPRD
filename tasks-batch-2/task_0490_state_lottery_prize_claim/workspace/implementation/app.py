"""Entry point: app factory, error handlers, blueprint registration."""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response

from routes_games import games_bp
from routes_retailers import retailers_bp
from routes_terminals import terminals_bp
from routes_players import players_bp
from routes_tickets import tickets_bp
from routes_claims import claims_bp
from routes_second_chance import sc_bp
from routes_settlements import settlements_bp
from routes_escheat import escheat_bp
from routes_clock import clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(games_bp)
    app.register_blueprint(retailers_bp)
    app.register_blueprint(terminals_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(sc_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(escheat_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
