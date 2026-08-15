"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask
from werkzeug.exceptions import BadRequest, NotFound, MethodNotAllowed

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock import bp as clock_bp
from routes.players import bp as players_bp
from routes.pools import bp as pools_bp
from routes.contracts import bp as contracts_bp
from routes.orders import bp as orders_bp
from routes.kits import bp as kits_bp
from routes.gear import bp as gear_bp
from routes.reconditioning import bp as reconditioning_bp
from routes.events import bp as events_bp
from routes.claims import bp as claims_bp
from routes.dispositions import bp as dispositions_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        players_bp,
        pools_bp,
        contracts_bp,
        orders_bp,
        kits_bp,
        gear_bp,
        reconditioning_bp,
        events_bp,
        claims_bp,
        dispositions_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(NotFound)
    def handle_not_found(err):
        return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "resource not found")

    @app.errorhandler(MethodNotAllowed)
    def handle_method_not_allowed(err):
        return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "method not allowed")

    @app.errorhandler(BadRequest)
    def handle_bad_request(err):
        return error_response(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
